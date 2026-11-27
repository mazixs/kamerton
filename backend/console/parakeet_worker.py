"""Локальный процесс parakeet.cpp. Один загруженный ASR и один запрос за раз."""

import asyncio
import ctypes as c
import json
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path
from typing import Protocol

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .audio_decode import RATE, decode_audio
from .catalog import has_weight, head_directory
from .engine import wait_uninterrupted
from .errors import ApiError, api_error_handler
from .model_assets import ALTERNATE_ASSETS, DIARIZATION, SILERO
from .proxy import parse_upload
from .settings import Settings


class Parakeet:
    def __init__(self, library: str, model_dir: Path, variant: str, *, max_segment: int = 30, language: str = "auto"):
        self.lib = c.CDLL(library)
        self.directory = model_dir
        self.streaming = variant == "nemotron_35_asr"
        self.default_language = language
        self.vad_options = json.dumps({"max_segment": max_segment}).encode("ascii")
        pointer, string, integer = c.c_void_p, c.c_char_p, c.c_int
        pcm_pointer = c.POINTER(c.c_float)
        functions = {
            "load": (pointer, string),
            "free": (None, pointer),
            "free_string": (None, pointer),
            "transcribe_path_json_vad_with": (pointer, pointer, pointer, string, integer, string),
            "stream_begin_lang": (pointer, pointer, string),
            "stream_feed_json": (pointer, pointer, pcm_pointer, integer),
            "stream_finalize_json": (pointer, pointer),
            "stream_free": (None, pointer),
            "diarize_path": (pointer, pointer, string),
        }
        for name, (result, *arguments) in functions.items():
            function = getattr(self.lib, f"parakeet_capi_{name}")
            function.restype = result
            function.argtypes = arguments
            setattr(self, name, function)

        self.model = self.vad = None
        if variant != "t_one":
            path = head_directory(variant, model_dir) / ALTERNATE_ASSETS[variant].name
            self.model = self._load(path)
            if not self.streaming:
                self.vad = self._load(model_dir / SILERO.name)

    def _load(self, path: Path):
        # В API движка путь никогда не берется из запроса.
        if not path.is_file() or not (context := self.load(os.fsencode(path))):
            raise RuntimeError("Не удалось открыть веса parakeet.cpp.")
        return context

    def _json(self, result) -> dict:
        if not result:
            raise RuntimeError("Ошибка распознавания parakeet.cpp.")
        try:
            return json.loads(c.string_at(result))
        finally:
            self.free_string(result)

    def _stream(self, wav: Path, language: str) -> dict:
        stream = self.stream_begin_lang(self.model, language.encode("ascii"))
        if not stream:
            raise ApiError(400, "Язык не поддерживается моделью.", "unsupported_language")
        responses = []
        try:
            with wave.open(str(wav), "rb") as audio:
                while block := audio.readframes(RATE * 5):
                    samples = memoryview(block).cast("h")
                    pcm = (c.c_float * len(samples))(*(sample / 32768 for sample in samples))
                    responses.append(self._json(self.stream_feed_json(stream, pcm, len(pcm))))
            responses.append(self._json(self.stream_finalize_json(stream)))
        finally:
            self.stream_free(stream)
        return {
            "text": " ".join(response["text"].strip() for response in responses if response.get("text")),
            "words": [word for response in responses for word in response.get("words", [])],
        }

    def recognize(self, wav: Path, language: str) -> dict:
        if self.streaming:
            return self._stream(wav, language)
        return self._json(self.transcribe_path_json_vad_with(
            self.model, self.vad, os.fsencode(wav), 0, self.vad_options,
        ))

    def diarize(self, wav: Path) -> list[dict]:
        diarization = self._load(self.directory / DIARIZATION.name)
        try:
            return self._json(self.diarize_path(diarization, os.fsencode(wav)))["segments"]
        finally:
            self.free(diarization)


class TOne(Parakeet):
    def __init__(self, library: str, model_dir: Path, variant: str, threads: int, *, punctuation: bool = True):
        super().__init__(library, model_dir, variant)
        import numpy
        import sherpa_onnx

        self.numpy = numpy
        directory = head_directory(variant, model_dir)
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_t_one_ctc(
            tokens=str(directory / "tokens.txt"), model=str(directory / "model.onnx"),
            num_threads=threads, sample_rate=8000,
        )
        self.punctuation = None
        if not punctuation:
            return
        import onnxruntime
        from tokenizers import Tokenizer

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        self.punctuation = onnxruntime.InferenceSession(
            str(directory / "rupunct_small_int8.onnx"), sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.labels = json.loads((directory / "config.json").read_bytes())["id2label"]

    def _format(self, words: list[str]) -> list[str]:
        marks = {
            "PERIOD": ".", "COMMA": ",", "QUESTION": "?", "TIRE": " -", "VOSKL": "!",
            "DVOETOCHIE": ":", "PERIODCOMMA": ";", "DEFIS": "-", "QUESTIONVOSKL": "?!",
            "MNOGOTOCHIE": "...", "O": "",
        }
        formatted = list(words)
        for start in range(0, len(words), 192):
            left, right = max(0, start - 24), min(len(words), start + 216)
            encoding = self.tokenizer.encode(words[left:right], is_pretokenized=True)
            model_input = {
                name: self.numpy.asarray([value], dtype="int64")
                for name, value in {
                    "input_ids": encoding.ids, "attention_mask": encoding.attention_mask,
                    "token_type_ids": encoding.type_ids,
                }.items()
            }
            scores = self.punctuation.run(None, model_input)[0][0]
            previous = None
            for word_index, scores_for_token in zip(encoding.word_ids, scores):
                if word_index is None or word_index == previous:
                    continue
                previous = word_index
                index = left + word_index
                if not start <= index < start + 192:
                    continue
                case, mark = self.labels[str(scores_for_token.argmax())].rsplit("_", 1)
                word = words[index]
                if case == "UPPER_TOTAL":
                    word = word.upper()
                elif case == "UPPER":
                    word = word[:1].upper() + word[1:]
                formatted[index] = word + marks[mark]
        return formatted

    def recognize(self, wav: Path, language: str) -> dict:
        if language not in ("auto", "ru", "ru-RU", "ru-ru"):
            raise ApiError(400, "T-one поддерживает русский язык.", "unsupported_language")
        stream = self.recognizer.create_stream()
        with wave.open(str(wav), "rb") as audio:
            duration = audio.getnframes() / RATE
            while block := audio.readframes(RATE):
                samples = self.numpy.frombuffer(block, dtype="<i2").astype("float32") / 32768
                stream.accept_waveform(RATE, samples)
                while self.recognizer.is_ready(stream):
                    self.recognizer.decode_stream(stream)
        stream.accept_waveform(RATE, self.numpy.zeros(RATE, dtype="float32"))
        stream.input_finished()
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)
        result = self.recognizer.get_result_all(stream)
        words = ctc_words(result.tokens, result.timestamps, duration)
        raw = result.text.split()
        formatted = self._format(raw) if self.punctuation is not None else raw
        if len(words) == len(formatted):
            for word, text in zip(words, formatted):
                word["word"] = text
        text = " ".join(formatted)
        return {"text": text.replace("- ", "-") if self.punctuation is not None else text, "words": words}


def ctc_words(tokens: list[str], timestamps: list[float], duration: float) -> list[dict]:
    words = []
    current = None
    for token, time in zip(tokens, timestamps):
        if not token.strip():
            if current is not None:
                words.append(current)
                current = None
        elif current is None:
            current = {"word": token, "start": min(time, duration), "end": min(time + 0.08, duration)}
        else:
            current["word"] += token
            current["end"] = min(time + 0.08, duration)
    if current is not None:
        words.append(current)
    return words


def speaker_utterances(words: list[dict], timeline: list[dict]) -> list[dict]:
    """Назначает слову говорящего с наибольшим пересечением по времени."""
    utterances = []
    for word in words:
        start, end = word["start"], word["end"]
        overlaps = [
            (min(end, interval["end"]) - max(start, interval["start"]), interval["speaker"])
            for interval in timeline if interval["end"] > start and interval["start"] < end
        ]
        speaker = f"speaker_{max(overlaps)[1] + 1}" if overlaps else "unknown"
        text = word.get("word", word.get("w", "")).strip()
        if not text:
            continue
        if utterances and utterances[-1]["speaker"] == speaker and start - utterances[-1]["end"] <= 0.5:
            utterances[-1]["text"] += " " + text
            utterances[-1]["end"] = max(utterances[-1]["end"], end)
        else:
            utterances.append({
                "id": len(utterances), "type": "transcript.text.segment",
                "start": start, "end": end, "speaker": speaker, "text": text,
            })
    return utterances


class SpeechEngine(Protocol):
    directory: Path
    default_language: str

    def recognize(self, wav: Path, language: str) -> dict: ...


def create_worker(engine: SpeechEngine, settings: Settings) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.add_exception_handler(ApiError, api_error_handler)
    slot = asyncio.Lock()
    progress: dict[str, str] = {}
    diarize_audio = getattr(engine, "diarize", None)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/internal/transcription-progress/{progress_id}")
    async def transcription_progress(progress_id: str):
        return {"stage": progress.get(progress_id)}

    @app.post("/v1/audio/transcriptions")
    async def transcribe(request: Request):
        if slot.locked():
            raise ApiError(429, "Движок уже распознает запись.", "engine_busy")
        async with slot, parse_upload(request) as (upload, form):
            format_ = form.get("response_format", "json")
            if format_ not in ("json", "text", "verbose_json", "diarized_json"):
                raise ApiError(400, "Формат ответа не поддерживается.", "invalid_response_format")
            language = form.get("language") or engine.default_language
            if not isinstance(language, str) or not language.isascii() or len(language) > 16:
                raise ApiError(400, "Некорректный код языка.", "unsupported_language")
            diarize = format_ == "diarized_json"
            if diarize and diarize_audio is None:
                raise ApiError(400, "Движок не поддерживает диаризацию.", "diarization_unsupported")
            if diarize and not has_weight(engine.directory / DIARIZATION.name, DIARIZATION.size):
                raise ApiError(409, "Сначала установите модель диаризации.", "diarization_not_installed")

            progress_id = request.headers.get("X-Kamerton-Progress")
            loop = asyncio.get_running_loop()

            def report(stage: str) -> None:
                if progress_id:
                    loop.call_soon_threadsafe(progress.__setitem__, progress_id, stage)

            def run() -> tuple[dict, float]:
                with tempfile.TemporaryDirectory(prefix="kamerton-audio-") as tmp:
                    source, wav = Path(tmp) / "audio", Path(tmp) / "audio.wav"
                    with source.open("wb") as buffer:
                        shutil.copyfileobj(upload.file, buffer, length=1024 * 1024)
                    report("decoding")
                    duration = decode_audio(source, wav)
                    try:
                        report("recognizing")
                        result = engine.recognize(wav, language) if duration else {"text": ""}
                        result["words"] = [
                            {
                                "word": word.get("word", word.get("w", "")),
                                "start": max(0, min(duration, word["start"])),
                                "end": max(0, min(duration, word["end"])),
                            }
                            for word in result.get("words", [])
                        ]
                        if diarize and duration:
                            report("diarizing")
                            timeline = diarize_audio(wav)
                            result["speaker_segments"] = timeline
                            result["segments"] = speaker_utterances(result.get("words", []), timeline)
                    except RuntimeError as exc:
                        raise ApiError(502, "Движок не смог обработать запись.", "engine_failed", "server_error") from exc
                    return result, duration

            try:
                result, duration = await wait_uninterrupted(asyncio.create_task(asyncio.to_thread(run)))
            finally:
                if progress_id:
                    progress.pop(progress_id, None)
        text = result.get("text", "").strip()
        if format_ == "text":
            return PlainTextResponse(text)
        payload = {"text": text}
        if format_ in ("verbose_json", "diarized_json"):
            payload.update({"duration": duration, "words": result["words"]})
        if diarize:
            payload.update({"segments": result.get("segments", []), "speaker_segments": result.get("speaker_segments", [])})
        return JSONResponse(payload)

    return app


def main() -> None:
    port, threads, library, directory, variant, limit, punctuation, max_segment, language = sys.argv[1:]
    settings = Settings(_env_file=None, max_upload_mb=int(limit) // 2**20)
    if variant == "t_one":
        engine = TOne(library, Path(directory), variant, int(threads), punctuation=punctuation != "off")
    else:
        engine = Parakeet(library, Path(directory), variant, max_segment=int(max_segment), language=language)
    worker = create_worker(engine, settings)
    uvicorn.run(worker, host="127.0.0.1", port=int(port), access_log=False, timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
