"""Размеры весов и файловых систем изнутри контейнера."""

import asyncio
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

from .catalog import HEADS, head_directory


def model_bytes(variant: str, model_dir: Path) -> int:
    directory = head_directory(variant, model_dir)
    total = 0
    for name in HEADS[variant].files:
        try:
            info = (directory / name).stat()
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
    return total


def _directory_bytes(path: Path) -> int | None:
    if not path.exists():
        return 0
    total = 0
    seen = set()

    def failed(error: OSError) -> None:
        raise error

    try:
        for directory, _, files in os.walk(path, onerror=failed):
            for name in files:
                try:
                    info = (Path(directory) / name).lstat()
                except FileNotFoundError:
                    continue
                key = (info.st_dev, info.st_ino)
                if stat.S_ISREG(info.st_mode) and key not in seen:
                    seen.add(key)
                    total += info.st_blocks * 512 if hasattr(info, "st_blocks") else info.st_size
    except OSError:
        return None
    return total


def _container_root_bytes() -> tuple[int | None, bool]:
    if os.name != "posix" or not any(Path(p).exists() for p in ("/.dockerenv", "/run/.containerenv")):
        return None, False
    try:
        result = subprocess.run(
            ["du", "-sx", "-B1", "/"], capture_output=True, text=True, timeout=4,
        )
        if result.returncode in (0, 1):
            return int(result.stdout.split(maxsplit=1)[0]), result.returncode != 0
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    return None, False


def _volume(path: Path) -> dict[str, int | None]:
    parent = next((candidate for candidate in (path, *path.parents) if candidate.exists()), path)
    try:
        usage = shutil.disk_usage(parent)
    except OSError:
        usage = None
    return {
        "bytes": _directory_bytes(path),
        "free_bytes": usage.free if usage is not None else None,
        "total_bytes": usage.total if usage is not None else None,
    }


class Storage:
    def __init__(self, model_dir: Path, data_dir: Path) -> None:
        self.model_dir = model_dir
        self.data_dir = data_dir
        self._snapshot: dict[str, Any] = {}
        self._sampled_at = -float("inf")
        self._lock = asyncio.Lock()

    def _read(self) -> dict[str, Any]:
        models = _volume(self.model_dir)
        data = _volume(self.data_dir)
        root, partial = _container_root_bytes()
        model_path, data_path = self.model_dir.resolve(), self.data_dir.resolve()
        separate = not (model_path.is_relative_to(data_path) or data_path.is_relative_to(model_path))
        total = None
        if root is not None and separate:
            try:
                root_device = Path("/").stat().st_dev
                mounts = [
                    volume["bytes"] for path, volume in ((model_path, models), (data_path, data))
                    if path.exists() and path.stat().st_dev != root_device
                ]
                if all(size is not None for size in mounts):
                    total = root + sum(size for size in mounts if size is not None)
            except OSError:
                pass
        return {
            "models": models,
            "data": data,
            "container_root_bytes": root,
            "container_root_partial": partial,
            "container_and_volumes_bytes": total,
        }

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            if time.monotonic() - self._sampled_at >= 30:
                self._snapshot = await asyncio.to_thread(self._read)
                self._sampled_at = time.monotonic()
            return self._snapshot
