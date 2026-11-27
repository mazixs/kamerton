"""Короткоживущие результаты распознавания в памяти процесса."""

import asyncio
import hashlib
import io
import json
import time
import wave
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import PurePath


TTL_SECONDS = 3600
MAX_BYTES = 32 * 1024**2
MAX_ENTRY_BYTES = 2 * 1024**2
MAX_ENTRIES = 256


@dataclass(frozen=True)
class CachedResponse:
    body: bytes
    status: int = 200
    headers: tuple[tuple[str, str], ...] = ()
    duration: float | None = None

    @property
    def size(self) -> int:
        return len(self.body) + sum(len(key) + len(value) for key, value in self.headers)


def _audio_digest(data: bytes, filename: str, media_type: str) -> bytes:
    # Метаданные обычного PCM WAV не участвуют в распознавании. Разрядность,
    # частота и каналы важны, даже если последовательность байтов совпала.
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        try:
            with wave.open(io.BytesIO(data)) as audio:
                channels, width, rate, frames, *_ = audio.getparams()
                digest = hashlib.sha256(f"pcm:{channels}:{width}:{rate}:".encode())
                total = 0
                while chunk := audio.readframes(32768):
                    digest.update(chunk)
                    total += len(chunk)
                if total == channels * width * frames:
                    return digest.digest()
        except (EOFError, OSError, wave.Error):
            pass
    digest = hashlib.sha256(json.dumps([PurePath(filename).suffix.lower(), media_type]).encode())
    digest.update(data)
    return digest.digest()


def transcription_key(data: bytes, filename: str, media_type: str, *, scope: str,
                      config: dict, fields: list[tuple[str, str]], glossary: str) -> bytes:
    digest = hashlib.sha256(_audio_digest(data, filename, media_type))
    digest.update(json.dumps([scope, config, sorted(fields, key=lambda field: field[0]), glossary],
                             sort_keys=True, ensure_ascii=True).encode())
    return digest.digest()


class TranscriptionCache:
    def __init__(self) -> None:
        self._entries: OrderedDict[bytes, tuple[float, CachedResponse]] = OrderedDict()
        self._locks: dict[bytes, tuple[asyncio.Lock, int]] = {}
        self._timer: asyncio.TimerHandle | None = None
        self._bytes = 0
        self._hits = 0

    @asynccontextmanager
    async def access(self, key: bytes):
        """Объединяем одновременные повторы, даже когда они ждут первый ответ."""
        lock, users = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = lock, users + 1
        try:
            async with lock:
                yield
        finally:
            _, users = self._locks[key]
            if users == 1:
                del self._locks[key]
            else:
                self._locks[key] = lock, users - 1

    def _remove_oldest(self) -> None:
        _, (_, response) = self._entries.popitem(last=False)
        self._bytes -= response.size

    def _prune(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        now = time.monotonic()
        while self._entries:
            expiry, _ = next(iter(self._entries.values()))
            if expiry > now:
                self._timer = asyncio.get_running_loop().call_later(expiry - now, self._prune)
                break
            self._remove_oldest()

    def get(self, key: bytes) -> CachedResponse | None:
        self._prune()
        found = self._entries.get(key)
        if found is not None:
            self._hits += 1
            return found[1]
        return None

    def put(self, key: bytes, response: CachedResponse) -> None:
        if response.size > MAX_ENTRY_BYTES:
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._bytes -= previous[1].size
        self._entries[key] = time.monotonic() + TTL_SECONDS, response
        self._bytes += response.size
        self._prune()
        while len(self._entries) > MAX_ENTRIES or self._bytes > MAX_BYTES:
            self._remove_oldest()

    def status(self) -> dict[str, int]:
        self._prune()
        return {"entries": len(self._entries), "bytes": self._bytes, "hits": self._hits,
                "ttl_seconds": TTL_SECONDS, "limit_bytes": MAX_BYTES}

    def close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._entries.clear()
        self._bytes = 0
