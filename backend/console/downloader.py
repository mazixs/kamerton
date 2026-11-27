"""Download model weights and report progress to the console.

The bundled models use `gigastt download --progress json`. The October revision
is pinned separately because the engine downloads the June package by default.
"""

import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx

from .catalog import HEADS, OCTOBER_E2E, OCTOBER_E2E_ASSETS, OCTOBER_E2E_RELEASE, head_directory
from .model_assets import ALTERNATE_ASSETS, Asset, SILERO, alternate_assets
from .settings import Settings

EventSink = Callable[[dict[str, Any]], None]

_MESSAGES = {
    "checksum": (
        "Контрольная сумма скачанного файла не совпала — файл повреждён. "
        "Нажмите «Развернуть» ещё раз, битый файл будет перекачан."
    ),
    "network": (
        "Ошибка сети при скачивании модели. Проверьте доступ в интернет с сервера "
        "и попробуйте снова."
    ),
    "disk": (
        "Не удалось записать модель на диск. Проверьте свободное место и права "
        "на папку ./models."
    ),
    "interrupted": "Скачивание модели прервано.",
}

_EXIT_KINDS = {65: "checksum", 69: "network", 74: "disk", 130: "interrupted"}


class DownloadError(RuntimeError):
    def __init__(self, kind: str, message: str, exit_code: int, http_status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.exit_code = exit_code
        self.http_status = http_status


# Движок пишет цветной вывод и на скачивании, и на `serve`, а консоль показывает
# его в <pre>: без чистки в логах видны квадратики ESC[2m вместо текста. Флага
# отключения цвета у CLI нет, зато NO_COLOR он уважает (замер 05.09.2026), и обе
# меры стоят вместе: переменная убирает цвет у источника, чистка страхует.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(line: str) -> str:
    return _ANSI.sub("", line)


def engine_env(settings: Settings) -> dict[str, str]:
    """Окружение для дочернего процесса движка."""
    private = {"API_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_PASSWORD_FILE"}
    env = {name: value for name, value in os.environ.items() if name.upper() not in private}
    env["NO_COLOR"] = "1"
    if settings.hf_token:
        env["HF_TOKEN"] = settings.hf_token
    return env


def engine_command(settings: Settings, *args: str) -> list[str]:
    """Command line for the engine binary; `.py` doubles run through this interpreter."""
    if settings.engine_bin.endswith(".py"):
        return [sys.executable, settings.engine_bin, *args]
    return [settings.engine_bin, *args]


class _Progress:
    """Turns per-file byte counters into one monotonic 0..100 percentage."""

    def __init__(self, expected_files: int) -> None:
        self.expected_files = max(expected_files, 1)
        self.fractions: dict[str, float] = {}
        self.last = -1

    def update(self, name: str, done: int, total: int) -> int | None:
        fraction = 1.0 if total <= 0 else min(done / total, 1.0)
        self.fractions[name] = max(self.fractions.get(name, 0.0), fraction)
        overall = sum(self.fractions.values()) / self.expected_files
        percent = max(self.last, min(int(overall * 100), 100))
        if percent == self.last:
            return None
        self.last = percent
        return percent

    def finish(self) -> int | None:
        if self.last >= 100:
            return None
        self.last = 100
        return 100


def matches_asset(path: Path, size: int, checksum: str) -> bool:
    try:
        with path.open("rb") as stream:
            return (
                os.fstat(stream.fileno()).st_size == size
                and hashlib.file_digest(stream, "sha256").hexdigest() == checksum
            )
    except FileNotFoundError:
        return False


async def download_assets(targets: list[tuple[Path, Asset]], on_event: EventSink) -> None:
    progress = _Progress(len(targets))
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            for directory, asset in targets:
                name, size, checksum = asset.name, asset.size, asset.sha256
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / name
                if not await asyncio.to_thread(matches_asset, target, size, checksum):
                    with TemporaryDirectory(dir=directory) as staging:
                        temporary = Path(staging) / name
                        digest = hashlib.sha256()
                        received = 0
                        async with client.stream("GET", asset.url) as response:
                            response.raise_for_status()
                            with temporary.open("wb") as stream:
                                async for chunk in response.aiter_bytes(256 * 1024):
                                    received += len(chunk)
                                    if received > size:
                                        raise DownloadError("checksum", _MESSAGES["checksum"], 65)
                                    stream.write(chunk)
                                    digest.update(chunk)
                                    if (percent := progress.update(name, received, size)) is not None:
                                        on_event({"phase": "progress", "percent": percent})
                        if received != size or digest.hexdigest() != checksum:
                            raise DownloadError("checksum", _MESSAGES["checksum"], 65)
                        temporary.replace(target)
                if (percent := progress.update(name, size, size)) is not None:
                    on_event({"phase": "progress", "percent": percent})
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise DownloadError("http", f"Сервер весов вернул HTTP {status}.", 69, status) from exc
    except httpx.HTTPError as exc:
        raise DownloadError("network", _MESSAGES["network"], 69) from exc
    except OSError as exc:
        raise DownloadError("disk", _MESSAGES["disk"], 74) from exc


async def download(settings: Settings, variant: str, on_event: EventSink) -> None:
    """Download the weights for `variant`, relaying progress events to `on_event`.

    Idempotent: the engine skips files that are already present and verified.
    """
    head = HEADS.get(variant)
    if head is None:
        raise ValueError(f"unknown head: {variant}")
    if variant == OCTOBER_E2E:
        directory = head_directory(variant, settings.model_dir)
        await download_assets([
            (directory, Asset(OCTOBER_E2E_RELEASE, name, size, checksum))
            for name, (size, checksum) in OCTOBER_E2E_ASSETS.items()
        ], on_event)
        return
    if variant in ALTERNATE_ASSETS:
        directory = head_directory(variant, settings.model_dir)
        targets = [(directory, asset) for asset in alternate_assets(variant)]
        if head.runtime == "parakeet" and variant != "nemotron_35_asr":
            targets.append((settings.model_dir, SILERO))
        await download_assets(targets, on_event)
        return

    try:
        settings.model_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DownloadError("disk", _MESSAGES["disk"], 74) from exc
    argv = engine_command(
        settings,
        "download",
        "--model-dir",
        str(settings.model_dir),
        "--model-variant",
        variant,
        "--progress",
        "json",
    )

    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=engine_env(settings),
    ))
    try:
        process = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        with suppress(OSError):
            process = await spawn
            with suppress(ProcessLookupError):
                process.kill()
            await process.communicate()
        raise
    except OSError as exc:
        raise DownloadError("other", f"Не удалось запустить движок: {exc}", 1) from exc

    progress = _Progress(len(head.files))
    reported_error: dict[str, Any] = {}

    async def pump_stderr() -> None:
        assert process.stderr is not None
        async for raw in process.stderr:
            line = strip_ansi(raw.decode("utf-8", "replace")).rstrip()
            if line:
                on_event({"phase": "log", "line": line})

    async def pump_stdout() -> None:
        assert process.stdout is not None
        async for raw in process.stdout:
            line = strip_ansi(raw.decode("utf-8", "replace")).strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                on_event({"phase": "log", "line": line})
                continue
            if not isinstance(event, dict):
                continue
            phase = event.get("phase")
            if phase == "error":
                reported_error.update(event)
            on_event(event)
            if phase == "download":
                percent = progress.update(
                    str(event.get("file") or ""),
                    int(event.get("bytes_done") or 0),
                    int(event.get("bytes_total") or 0),
                )
                if percent is not None:
                    on_event({"phase": "progress", "percent": percent})
            elif phase == "done":
                percent = progress.finish()
                if percent is not None:
                    on_event({"phase": "progress", "percent": percent})

    pumps = [asyncio.create_task(pump_stdout()), asyncio.create_task(pump_stderr())]
    try:
        await asyncio.gather(*pumps)
        code = await process.wait()
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            await process.communicate()
    if code == 0:
        return

    status = reported_error.get("http_status")
    if type(status) is int and 400 <= status <= 599:
        raise DownloadError("http", f"Сервер весов вернул HTTP {status}.", code, status)
    kind = reported_error.get("kind")
    if not isinstance(kind, str) or kind not in _MESSAGES:
        kind = _EXIT_KINDS.get(code, "other")
    message = _MESSAGES.get(kind) or f"Скачивание модели не удалось (код {code})."
    raise DownloadError(kind, message, code)
