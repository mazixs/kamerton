"""Lifecycle of the `gigastt serve` child process.

The console owns the process: it builds the command line from an `EngineConfig`,
starts it on loopback, waits until the engine reports a loaded model, and stops it
on SIGTERM with a hard kill as the backstop. Nothing here knows about audio.
"""

import asyncio
import contextlib
import os
import shutil
import signal
import socket
import sys
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import httpx

from .catalog import HEADS, engine_head_id, head_directory
from .downloader import engine_command, engine_env, strip_ansi
from .model_assets import ALTERNATE_ASSETS
from .settings import Settings
from .state import EngineConfig


class EngineStartupError(RuntimeError):
    def __init__(self, message: str, kind: str = "other") -> None:
        super().__init__(message)
        self.kind = kind


def runtime_available(settings: Settings, variant: str) -> bool:
    runtime = HEADS[variant].runtime
    if runtime == "whisper":
        return bool(settings.whisper_bin and shutil.which(settings.whisper_bin) and shutil.which("ffmpeg"))
    if runtime == "parakeet":
        return Path(settings.parakeet_lib).is_file() and bool(shutil.which("ffmpeg"))
    if runtime == "sherpa":
        return Path(settings.parakeet_lib).is_file() and bool(shutil.which("ffmpeg")) and all(
            find_spec(name) is not None for name in ("sherpa_onnx", "onnxruntime", "tokenizers", "numpy")
        )
    if runtime == "gigaam_v4":
        if not shutil.which("ffmpeg"):
            return False
        if settings.gigaam_v4_python:
            return bool(shutil.which(settings.gigaam_v4_python))
        return all(
            find_spec(name) is not None
            for name in ("torch", "torchaudio", "transformers", "omegaconf", "soundfile", "sentencepiece")
        )
    return True


async def wait_uninterrupted[T](task: asyncio.Future[T]) -> T:
    """Не освобождать ресурсы операции, пока она работает, даже при отмене запроса."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


def build_compare_argv(settings: Settings, audio: Path, model_dir: Path, variant: str, output: Path) -> list[str]:
    return engine_command(
        settings, "transcribe", str(audio), "--offline", "--model-dir", str(model_dir),
        "--model-variant", engine_head_id(variant), "--file-window-concurrency", "1",
        "--punctuation", "off", "--itn", "off", "--format", "json", "--output", str(output),
    )


def build_argv(settings: Settings, cfg: EngineConfig, *, alternate_port: int | None = None) -> list[str]:
    runtime = HEADS[cfg.variant].runtime
    if runtime != "gigastt":
        if not runtime_available(settings, cfg.variant):
            raise EngineStartupError(f"Движок {runtime} не установлен.", "missing")
        port = alternate_port if alternate_port is not None else settings.engine_port
        directory = head_directory(cfg.variant, settings.model_dir)
        threads = cfg.alternate_threads or settings.alternate_threads
        if runtime == "gigaam_v4":
            return [
                settings.gigaam_v4_python or sys.executable, "-m", "console.gigaam_v4_worker", str(port), str(directory),
                str(threads), str(settings.max_upload_mb), cfg.variant,
            ]
        if runtime == "whisper":
            model = directory / ALTERNATE_ASSETS[cfg.variant].name
            return [
                settings.whisper_bin, "--host", "127.0.0.1", "--port", str(port),
                "--inference-path", "/v1/audio/transcriptions", "--model", str(model),
                "--threads", str(threads), "--language", "auto",
                "--beam-size", str(cfg.whisper_beam_size), "--max-context", "0", "--no-gpu",
            ]
        return [
            sys.executable, "-m", "console.parakeet_worker", str(port),
            str(threads), settings.parakeet_lib, str(settings.model_dir),
            cfg.variant, str(settings.max_upload_bytes), cfg.punctuation,
            str(cfg.parakeet_max_segment), cfg.nemotron_language,
        ]
    if cfg != cfg.fit_window_concurrency():
        raise EngineStartupError("Число параллельных окон не может превышать размер пула.", "windows")
    argv = engine_command(
        settings,
        "serve",
        "--host",
        settings.engine_host,
        "--port",
        str(settings.engine_port),
        *([] if settings.owner_access else ["--bind-all"]),
        "--model-dir",
        str(head_directory(cfg.variant, settings.model_dir)),
        "--model-variant",
        engine_head_id(cfg.variant),
        "--punctuation",
        cfg.punctuation,
        "--itn",
        cfg.itn,
        "--pool-size",
        str(cfg.pool_size),
        "--hotwords-file",
        str(settings.hotwords_path),
        "--hotwords-boost",
        str(cfg.hotwords_boost),
        # Side models default to the engine user's home directory, which is not a
        # volume: without these two flags the punctuation and VAD models would be
        # re-downloaded on every container recreate.
        # Предел тела у движка свой, и по умолчанию он равен нашему — из-за чего
        # файл ровно в `MAX_UPLOAD_MB` не проходил: обёртка multipart добавляет
        # к нему несколько сотен байт. Считаем его от нашего лимита, чтобы
        # отказывала консоль понятным текстом, а не движок словами про multipart.
        "--body-limit-bytes",
        str(settings.engine_body_limit_bytes),
        "--punct-model-dir",
        str(settings.model_dir / "punct"),
        "--vad-model-dir",
        str(settings.model_dir / "vad"),
    )
    # Флаг добавляется только когда его действительно просили. Единица — это и
    # поведение движка по умолчанию, и argv, который был до 2.21.0: тот, кто
    # параллельность не включал, не должен получить в командной строке аргумент,
    # которого прежние версии движка не знают.
    if cfg.file_window_concurrency > 1:
        argv.extend(["--file-window-concurrency", str(cfg.file_window_concurrency)])
    if cfg.vad:
        argv.append("--vad")
    if cfg.hotwords_default:
        argv.append("--hotwords-default")
    if settings.enable_jobs:
        argv.append("--enable-jobs")
    return argv


class EngineProcess:
    def __init__(
        self,
        settings: Settings,
        on_log: Callable[[str], None] | None = None,
        on_exit: Callable[[int], None] | None = None,
    ) -> None:
        self.settings = settings
        self.on_log = on_log or (lambda line: None)
        self.on_exit = on_exit or (lambda code: None)
        self.config: EngineConfig | None = None
        self._alternate_port: int | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._generation = 0
        self._stop_task: asyncio.Task[None] | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._expected_exit = False
        self._startup_complete = False

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def base_url(self) -> str:
        if self._alternate_port is not None:
            return f"http://127.0.0.1:{self._alternate_port}"
        return self.settings.engine_base_url

    async def start(self, cfg: EngineConfig) -> None:
        if self.is_running or (self._stop_task is not None and not self._stop_task.done()):
            raise RuntimeError("engine already running or stopping")
        gigastt = HEADS[cfg.variant].runtime == "gigastt"
        alternate_port = None
        if not gigastt:
            # Whisper может не занять недавно освобожденный порт GigaSTT:
            # завершение процесса не обязано убирать TCP-соединения из TIME_WAIT.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                alternate_port = listener.getsockname()[1]
        argv = build_argv(self.settings, cfg, alternate_port=alternate_port)
        if gigastt:
            env = engine_env(self.settings)
            env["RUST_LOG"] = f"gigastt={self.settings.log_level}"
        else:
            names = ("PATH", "SystemRoot", "TMP", "TEMP", "TMPDIR", "LD_LIBRARY_PATH")
            env = {name: os.environ[name] for name in names if name in os.environ}
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            env["PARAKEET_DEVICE"] = "cpu"
        self.settings.model_dir.mkdir(parents=True, exist_ok=True)
        self.settings.hotwords_path.parent.mkdir(parents=True, exist_ok=True)

        self._expected_exit = False
        self._startup_complete = False
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._generation += 1
        self._alternate_port = alternate_port
        self.config = cfg
        self.on_log(f"engine started: pid={self._process.pid} variant={cfg.variant}")
        startup_variant = None if gigastt else cfg.variant
        self._tasks = [
            asyncio.create_task(self._pump(self._process.stdout, startup_variant)),
            asyncio.create_task(self._pump(self._process.stderr, startup_variant)),
            asyncio.create_task(self._watch(self._process)),
        ]

    async def _pump(self, stream: asyncio.StreamReader | None, startup_variant: str | None) -> None:
        if stream is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                if startup_variant is not None and self._startup_complete:
                    # После готовности сторонний движок может печатать содержимое записи.
                    # Читаем трубу до конца, чтобы она не заблокировала процесс.
                    while await stream.read(65536):
                        pass
                    return
                try:
                    raw = await stream.readline()
                except ValueError:
                    # Строка длиннее буфера StreamReader уже пропущена.
                    continue
                if not raw:
                    return
                if startup_variant is not None and self._startup_complete:
                    continue
                line = strip_ansi(raw.decode("utf-8", "replace")).rstrip()
                if line:
                    self.on_log(f"[{startup_variant}] {line[:2048]}" if startup_variant is not None else line)

    async def _watch(self, process: asyncio.subprocess.Process) -> None:
        code = await process.wait()
        if self._expected_exit:
            return
        self.on_log(f"engine exited unexpectedly with code {code}")
        self.on_exit(code)

    async def stop(self, timeout: float = 15.0) -> None:
        # Одна операция SIGTERM → kill → wait; отмена вызывающего не бросает процесс.
        if self._stop_task is None or self._stop_task.done():
            self._stop_task = asyncio.create_task(self._stop(timeout))
        await wait_uninterrupted(self._stop_task)

    async def _stop(self, timeout: float) -> None:
        process, self._process = self._process, None
        self._expected_exit = True
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
            except TimeoutError:
                self.on_log("engine did not stop in time, killing")
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []
        self.config = None
        self._alternate_port = None

    async def health(self, timeout: float = 2.0) -> dict[str, Any] | None:
        if not self.is_running:
            return None
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.get(f"{self.base_url}/health")
            if response.status_code != 200:
                return None
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def wait_healthy(self, timeout: float = 180.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if not self.is_running:
                raise EngineStartupError(
                    "Движок завершился при запуске — смотрите логи в разделе «Логи».", "exited"
                )
            payload = await self.health()
            if payload and payload.get("status") == "ok" and payload.get("model") != "loading":
                self._startup_complete = True
                return payload
            await asyncio.sleep(0.5)
        raise EngineStartupError(
            f"Движок не вышел в рабочее состояние за {int(timeout)} с "
            "(модель так и не загрузилась).", "timeout"
        )

    async def reload(self, timeout: float = 60.0) -> bool:
        """Ask the engine to rebuild itself from its boot recipe (re-reads hotwords)."""
        if not self.is_running:
            return False
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(f"{self.settings.engine_base_url}/v1/admin/reload")
            return response.status_code == 200
        except httpx.HTTPError:
            return False
