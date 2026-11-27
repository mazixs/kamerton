"""Persisted deployment state.

The console must come back to whatever the user last deployed, so the desired
configuration is written to disk on every transition. Writes are atomic: a
container killed mid-write must never find a half-written state file.
"""

import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .catalog import HEADS

STATUSES = ("stopped", "downloading", "starting", "ready", "error")


@dataclass(frozen=True)
class EngineConfig:
    variant: str = "rnnt"
    punctuation: str = "auto"
    itn: str = "auto"
    vad: bool = False
    pool_size: int = 1
    hotwords_boost: float = 5.0  # the engine's own default; see console.settings
    hotwords_default: bool = True  # measured, not assumed; see console.settings
    # Сколько окон длинного файла движок декодирует одновременно (движок 2.21.0 и
    # новее). 1 - последовательно, как было всегда. Толк появляется только при
    # `pool_size` от 2: движок берёт свободный слот пула без ожидания, а при пуле 1
    # свободного слота нет и файл всё равно идёт последовательно.
    file_window_concurrency: int = 1
    alternate_threads: int | None = None
    whisper_beam_size: int = 5
    parakeet_max_segment: int = 30
    nemotron_language: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fit_window_concurrency(self) -> "EngineConfig":
        # Дополнительных окон больше, чем рабочих слотов, движок запустить не может.
        if self.file_window_concurrency <= self.pool_size:
            return self
        return replace(self, file_window_concurrency=self.pool_size)

    @classmethod
    def from_dict(cls, raw: object) -> "EngineConfig | None":
        if not isinstance(raw, dict) or not raw:
            return None
        known = {f.name for f in fields(cls)}
        config = cls(**{k: v for k, v in raw.items() if k in known})
        # desired и last_good читаются независимо: повреждение одной записи не
        # должно лишать нас второй. Не сравниваем окна с пулом до миграции.
        if (
            not isinstance(config.variant, str) or config.variant not in HEADS
            or config.punctuation not in ("auto", "on", "off")
            or config.itn not in ("auto", "on", "off")
            or type(config.vad) is not bool or type(config.hotwords_default) is not bool
            or type(config.pool_size) is not int or not 1 <= config.pool_size <= 8
            or type(config.file_window_concurrency) is not int
            or not 1 <= config.file_window_concurrency <= 8
            or (config.alternate_threads is not None and (
                type(config.alternate_threads) is not int or not 1 <= config.alternate_threads <= 16
            ))
            or type(config.whisper_beam_size) is not int or not 1 <= config.whisper_beam_size <= 10
            or type(config.parakeet_max_segment) is not int or not 5 <= config.parakeet_max_segment <= 30
            or config.nemotron_language not in ("auto", "ru", "en")
            or type(config.hotwords_boost) not in (int, float)
            or not -float("inf") < config.hotwords_boost < float("inf")
        ):
            return None
        return config


@dataclass
class State:
    status: str = "stopped"
    detail: str = ""
    desired: EngineConfig | None = None
    last_good: EngineConfig | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    compare_enabled: bool | None = None
    model_configs: dict[str, EngineConfig] = field(default_factory=dict)


class StateFile:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> State:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return State()
        if not isinstance(raw, dict):
            return State()
        status = raw.get("status")
        compare = raw.get("compare_enabled")
        profiles = raw.get("model_configs")
        model_configs = {
            variant: config for variant, value in (profiles.items() if isinstance(profiles, dict) else ())
            if (config := EngineConfig.from_dict(value)) is not None and config.variant == variant
        }
        return State(
            status=status if status in STATUSES else "stopped",
            detail=str(raw.get("detail") or ""),
            desired=EngineConfig.from_dict(raw.get("desired")),
            last_good=EngineConfig.from_dict(raw.get("last_good")),
            updated_at=str(raw.get("updated_at") or datetime.now(UTC).isoformat()),
            compare_enabled=compare if isinstance(compare, bool) else None,
            model_configs=model_configs,
        )

    def save(self, state: State) -> None:
        state.updated_at = datetime.now(UTC).isoformat()
        payload = {
            "version": 1,
            "status": state.status,
            "detail": state.detail,
            "desired": state.desired.to_dict() if state.desired else None,
            "last_good": state.last_good.to_dict() if state.last_good else None,
            "updated_at": state.updated_at,
            "compare_enabled": state.compare_enabled,
            "model_configs": {variant: cfg.to_dict() for variant, cfg in state.model_configs.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, suffix=".tmp", delete=False,
            ) as file:
                tmp = Path(file.name)
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, self.path)
        finally:
            if tmp is not None:
                with suppress(OSError):
                    tmp.unlink(missing_ok=True)
