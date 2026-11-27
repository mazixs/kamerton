"""Декодирование локальной загрузки для CPU-движков."""

import asyncio
import subprocess
import tempfile
import wave
from pathlib import Path

from .engine import wait_uninterrupted
from .errors import ApiError


RATE = 16000
MAX_AUDIO_SECONDS = 1800


def decode_audio(source: Path, wav: Path) -> float:
    try:
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file",
            "-format_whitelist", "wav,mp3,matroska,webm,ogg,mov,flac,aac",
            "-i", str(source), "-map", "0:a:0", "-vn", "-t", str(MAX_AUDIO_SECONDS + 1),
            "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(wav),
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=True, timeout=90)
        with wave.open(str(wav), "rb") as stream:
            duration = stream.getnframes() / RATE
    except (OSError, EOFError, wave.Error, subprocess.SubprocessError) as exc:
        raise ApiError(400, "Не удалось прочитать аудиофайл.", "invalid_audio") from exc
    if duration > MAX_AUDIO_SECONDS:
        raise ApiError(413, "Запись длиннее 30 минут.", "audio_too_long")
    return duration


async def whisper_audio(data: bytes) -> bytes:
    def prepare() -> bytes:
        with tempfile.TemporaryDirectory(prefix="kamerton-audio-") as tmp:
            source, wav = Path(tmp) / "audio", Path(tmp) / "audio.wav"
            source.write_bytes(data)
            decode_audio(source, wav)
            return wav.read_bytes()

    return await wait_uninterrupted(asyncio.create_task(asyncio.to_thread(prepare)))
