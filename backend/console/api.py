"""Management API used by the web console.

Everything the UI needs and nothing the engine already provides: status, catalog,
deploy/stop, glossary, a live event stream and a one-off test transcription that
reports its own timing.
"""

import asyncio
import hashlib
import json
import re
import time
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from . import owner_access
from .audio_decode import whisper_audio
from .auth import require_api_key
from .catalog import DEFAULT_LANG, HEADS, LANGS, PUBLIC_MODEL_ID, has_weight, is_downloaded, openai_model_id, pick
from .downloader import DownloadError, download_assets
from .engine import runtime_available
from .errors import ApiError
from .glossary import entry_issues, parse_context, read_glossary, whisper_prompt_fields
from .model_assets import DIARIZATION
from .proxy import (
    RequestResources,
    TIMESTAMP_GRANULARITIES,
    TRANSCRIBE_TIMEOUT,
    models as client_models,
    multipart_upload_parts,
    read_upload,
    require_ready,
    upload_duration_seconds,
)
from .settings import HeadId, Mode
from .state import EngineConfig
from .storage import model_bytes
from .transcription_cache import CachedResponse, transcription_key
from .vocab import head_alphabet, split_representable

router = APIRouter()
admin = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])
admin.add_api_route("/client-models", client_models, methods=["GET"])
STARTED_AT = time.monotonic()
_PUBLIC_ENGINE_DETAIL = {
    "stopped": "Движок остановлен",
    "downloading": "Загрузка модели",
    "starting": "Движок запускается",
    "ready": "Движок готов",
    "error": "Ошибка движка",
}


class DeployRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant: HeadId
    punctuation: Mode | None = None
    itn: Mode | None = None
    vad: bool | None = None
    pool_size: int | None = Field(default=None, ge=1, le=8)
    hotwords_boost: float | None = Field(default=None, ge=0.0, le=50.0)
    hotwords_default: bool | None = None
    file_window_concurrency: int | None = Field(default=None, ge=1, le=8)
    alternate_threads: int | None = Field(default=None, ge=1, le=16)
    whisper_beam_size: int | None = Field(default=None, ge=1, le=10)
    parakeet_max_segment: int | None = Field(default=None, ge=5, le=30)
    nemotron_language: Literal["auto", "ru", "en"] | None = None

    def to_config(self, defaults: EngineConfig) -> EngineConfig:
        config = EngineConfig(
            variant=self.variant,
            punctuation=self.punctuation or defaults.punctuation,
            itn=self.itn or defaults.itn,
            vad=defaults.vad if self.vad is None else self.vad,
            pool_size=self.pool_size or defaults.pool_size,
            hotwords_boost=(
                defaults.hotwords_boost if self.hotwords_boost is None else self.hotwords_boost
            ),
            hotwords_default=(
                defaults.hotwords_default
                if self.hotwords_default is None
                else self.hotwords_default
            ),
            file_window_concurrency=(
                self.file_window_concurrency or defaults.file_window_concurrency
            ),
            alternate_threads=(
                self.alternate_threads if "alternate_threads" in self.model_fields_set else defaults.alternate_threads
            ),
            whisper_beam_size=self.whisper_beam_size or defaults.whisper_beam_size,
            parakeet_max_segment=self.parakeet_max_segment or defaults.parakeet_max_segment,
            nemotron_language=self.nemotron_language or defaults.nemotron_language,
        )
        fitted = config.fit_window_concurrency()
        if fitted != config and self.file_window_concurrency is not None:
            raise ApiError(
                422, "Число параллельных окон не может превышать размер пула.",
                "invalid_file_window_concurrency",
            )
        return fitted


class CompareSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool


class GlossaryRequest(BaseModel):
    text: str = ""


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Liveness of the console itself.

    Always 200 while the process is alive: Docker's healthcheck must not restart the
    container just because no model is deployed yet.
    """
    supervisor = request.app.state.supervisor
    return {
        "status": "ok",
        "engine_status": supervisor.status,
        # Свободный текст ошибок, включая пути ОС, остаётся в закрытом /api/status.
        "engine_detail": _PUBLIC_ENGINE_DETAIL.get(supervisor.status, "Состояние движка неизвестно"),
        "engine_detail_code": supervisor.detail_code,
        "variant": supervisor.current.variant if supervisor.current else None,
    }


def _status_payload(request: Request) -> dict[str, Any]:
    supervisor = request.app.state.supervisor
    settings = request.app.state.settings
    current = supervisor.current
    return {
        "status": supervisor.status,
        # `detail` - готовая строка по-русски, она же идет в логи. `detail_code` и
        # `detail_params` - то же самое машиночитаемо, чтобы консоль показала фразу
        # на выбранном языке, а не переводила текст обратно.
        "detail": supervisor.detail,
        "detail_code": supervisor.detail_code,
        "detail_params": supervisor.detail_params,
        "download_percent": supervisor.download_percent,
        # Цель развертывания, а не работающий процесс: консоль рисует прогресс на
        # карточке той головы, которую разворачивают, и до первого запуска процесса нет.
        "deploying": supervisor.deploying,
        "engine": {
            "variant": current.variant if current else None,
            "runtime": HEADS[current.variant].runtime if current else None,
            "punctuation": current.punctuation if current else None,
            "itn": current.itn if current else None,
            "vad": current.vad if current else None,
            "pool_size": current.pool_size if current else None,
            "hotwords_boost": current.hotwords_boost if current else None,
            "hotwords_default": current.hotwords_default if current else None,
            "file_window_concurrency": current.file_window_concurrency if current else None,
            "running": supervisor.process.is_running,
        },
        "defaults": supervisor.default_config().to_dict(),
        "model_configs": supervisor.model_configs(),
        "alternate_threads_default": settings.alternate_threads,
        # Состояние сильнее `.env` намеренно, поэтому расхождение между ними не
        # исправляется само, а показывается: что просит файл, что из этого задано явно
        # и где значения разошлись.
        "env": {
            "config": supervisor.env_config().to_dict(),
            "explicit": sorted(settings.explicit_engine_fields()),
            "diverges": supervisor.env_divergence(),
        },
        "metrics": request.app.state.metrics.snapshot(),
        "api_key_set": settings.owner_access or bool(settings.api_key),
        "glossary_count": supervisor.glossary_count,
        "restart_count": supervisor.restart_count,
        "uptime_seconds": int(time.monotonic() - STARTED_AT),
        "max_upload_mb": settings.max_upload_mb,
        "compare_enabled": supervisor.compare_enabled,
        "compare_available": supervisor.compare_available,
        "compare_single_engine": settings.compare_single_engine,
        "diarization_installed": has_weight(settings.model_dir / DIARIZATION.name, DIARIZATION.size),
        "diarization": _diarization_status(request),
        "transcription_cache": request.app.state.transcription_cache.status(),
    }


@admin.get("/status")
async def status(request: Request) -> dict[str, Any]:
    return _status_payload(request)


@admin.get("/storage")
async def storage(request: Request) -> dict[str, Any]:
    return await request.app.state.storage.snapshot()


@admin.put("/settings/compare")
async def set_compare(request: Request, body: CompareSetting) -> CompareSetting:
    """Сохранить доступность сравнения без перезапуска рабочего движка."""
    supervisor = request.app.state.supervisor
    supervisor.set_compare_enabled(body.enabled)
    return CompareSetting(enabled=supervisor.compare_enabled)


@admin.get("/models")
async def models(request: Request, lang: str = DEFAULT_LANG) -> dict[str, Any]:
    """Каталог голов на языке интерфейса.

    Переводятся только пояснения: идентификаторы, названия моделей и коды языков
    одинаковы везде. Неизвестный `lang` молча становится английским - выбор языка
    в интерфейсе не повод отвечать ошибкой.
    """
    settings = request.app.state.settings
    current = request.app.state.supervisor.current
    if lang not in LANGS:
        lang = DEFAULT_LANG
    return {
        "lang": lang,
        "heads": [
            {
                "id": head.id,
                "api_id": openai_model_id(head.id),
                "title": head.title,
                "subtitle": pick(head.subtitle, lang),
                "languages": list(head.languages),
                "native_punctuation": head.native_punctuation,
                "runtime": head.runtime,
                "size_mb": head.size_mb,
                "installed_bytes": model_bytes(head.id, settings.model_dir),
                "badge": pick(head.badge, lang),
                "badge_note": pick(head.badge_note, lang),
                "downloaded": is_downloaded(head.id, settings.model_dir),
                "deployed": current is not None and current.variant == head.id,
            }
            for head in HEADS.values()
            if runtime_available(settings, head.id)
        ]
    }


@admin.post("/deploy", status_code=202)
async def deploy(request: Request, body: DeployRequest) -> dict[str, Any]:
    if not runtime_available(request.app.state.settings, body.variant):
        raise ApiError(409, "Движок выбранной модели не установлен.", "runtime_unavailable")
    supervisor = request.app.state.supervisor
    config = body.to_config(supervisor.default_config(body.variant))
    task = asyncio.create_task(supervisor.deploy(config))
    # При остановке надо дождаться и текущего развёртывания, и стоящих за ним.
    pending = request.app.state.deploy_tasks
    pending.add(task)
    task.add_done_callback(pending.discard)
    request.app.state.deploy_task = task
    return {"status": "accepted", "config": config.to_dict()}


def _diarization_status(request: Request) -> dict[str, Any]:
    state = request.app.state
    installed = has_weight(state.settings.model_dir / DIARIZATION.name, DIARIZATION.size)
    activity = state.diarization_status if state.diarization_status.get("status") in {"downloading", "error"} else {}
    return {"available": runtime_available(state.settings, "parakeet_tdt_v3"),
            "bytes": DIARIZATION.size, "status": "installed" if installed else "missing",
            **(activity if not installed else {})}


async def _download_diarization(request: Request) -> None:
    state = request.app.state

    def notify(status: str, **extra: Any) -> None:
        state.diarization_status = {"status": status, **extra}
        state.bus.publish({"type": "diarization", **_diarization_status(request)})

    notify("downloading", progress=None)
    try:
        await download_assets([(state.settings.model_dir, DIARIZATION)],
                              lambda event: notify("downloading", progress=event["percent"]))
    except DownloadError as exc:
        notify("error", kind=exc.kind, http_status=exc.http_status)
        raise ApiError(502, "Не удалось скачать модель диаризации.",
                       "diarization_download_failed", "server_error") from exc
    notify("installed")


@admin.post("/models/diarization")
async def install_diarization(request: Request) -> dict[str, int]:
    state = request.app.state
    if not runtime_available(state.settings, "parakeet_tdt_v3"):
        raise ApiError(409, "Движок диаризации не установлен.", "runtime_unavailable")
    async with state.diarization_lock:
        task = state.diarization_task
        if task is None or task.done():
            if _diarization_status(request)["status"] == "installed":
                return {"installed_bytes": DIARIZATION.size}
            task = state.diarization_task = asyncio.create_task(_download_diarization(request))
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    await asyncio.shield(task)
    return {"installed_bytes": DIARIZATION.size}


@admin.post("/stop")
async def stop(request: Request) -> dict[str, Any]:
    await request.app.state.supervisor.stop_engine()
    return {"status": "stopped"}


def _glossary_mode(variant: str) -> Literal["hotwords", "prompt", "unsupported"]:
    runtime = HEADS[variant].runtime
    if runtime == "gigastt":
        return "hotwords"
    return "prompt" if runtime == "whisper" else "unsupported"


@admin.get("/glossary")
async def glossary_get(request: Request) -> dict[str, Any]:
    """The glossary plus how much of it the current head can actually spell."""
    supervisor = request.app.state.supervisor
    settings = request.app.state.settings
    defaults = supervisor.default_config()
    current = supervisor.current
    variant = current.variant if current else defaults.variant

    text = read_glossary(settings.hotwords_path)
    entries = parse_context(text)
    mode = _glossary_mode(variant)
    alphabet = head_alphabet(variant, settings.model_dir) if mode == "hotwords" else None
    usable, dropped = (
        split_representable([phrase for phrase, _weight in entries], alphabet)
        if alphabet is not None
        else ([], [])
    )
    return {
        "text": text,
        "count": len(entries),
        "boost": defaults.hotwords_boost,
        "variant": variant,
        "mode": mode,
        # None rather than 0 when the vocabulary is unreadable: the UI must not
        # claim phrases are being dropped when we simply do not know.
        "usable_count": len(usable) if alphabet is not None else None,
        "dropped": dropped,
        # Фразы из INITIAL_CONTEXT, которых в списке нет: `.env` читается один раз, при
        # создании файла, поэтому дальше расхождение видно только так.
        "env_missing": supervisor.initial_context_missing(),
        # Что движок сделает с фразой помимо того, о чем его просили: вес <= 0
        # выбрасывает фразу, любой положительный вес равен единице, строка с `#`
        # читается как комментарий. Коды, а не фразы: формулировку выбирает
        # консоль на своем языке.
        "issues": entry_issues(text),
        "approximate": alphabet is not None and alphabet.subword,
        # What this head can spell, so the advice is read off the vocabulary on disk
        # instead of a rule that is wrong for some head: `e2e_rnnt` writes Latin and
        # digits, `rnnt` writes neither. Case is deliberately absent — the engine
        # retries a phrase lowercased itself, so it can never be the reason one dies.
        "alphabet": (
            None
            if alphabet is None
            else {
                "latin": alphabet.writes_latin,
                "digits": alphabet.writes_digits,
            }
        ),
    }


@admin.post("/glossary")
async def glossary_post(request: Request, body: GlossaryRequest) -> dict[str, Any]:
    supervisor = request.app.state.supervisor
    applied = await supervisor.apply_glossary(body.text)
    # Претензии считаются по присланному тексту, а не по сохраненному файлу:
    # файл часть из них не переживает. Неразобранный вес в нем неотличим от
    # отсутствующего, а табуляцию `render_hotwords` убирает, иначе она разрезала
    # бы строку. Сказать об этом можно только здесь, в ответ на саму правку.
    return {
        "count": supervisor.glossary_count,
        "applied": applied,
        "mode": _glossary_mode((supervisor.current or supervisor.default_config()).variant),
        "issues": entry_issues(body.text),
    }


@admin.get("/journal")
async def journal(request: Request) -> dict[str, Any]:
    """До 200 событий развёртывания и движка, новые сверху; только за жизнь процесса."""
    return {"events": request.app.state.supervisor.journal.snapshot()}


@admin.get("/events")
async def events(request: Request) -> StreamingResponse:
    bus = request.app.state.bus
    subscription = bus.subscribe()
    snapshot = _status_payload(request)
    log_lines = bus.log_lines(limit=50)

    async def stream():
        try:
            yield _sse({"type": "snapshot", **snapshot})
            for line in log_lines:
                yield _sse({"type": "log", "line": line})
            if not request.app.state.settings.owner_access:
                async for event in subscription:
                    yield _sse(event)
                return
            loop = asyncio.get_running_loop()
            deadline = loop.time() + owner_access.SSE_CHECK_SECONDS
            while True:
                if loop.time() >= deadline:
                    try:
                        if not await owner_access.live_session(request):
                            return
                    except ApiError:
                        return
                    deadline = loop.time() + owner_access.SSE_CHECK_SECONDS
                try:
                    async with asyncio.timeout_at(deadline):
                        event = await anext(subscription)
                except TimeoutError:
                    continue
                yield _sse(event)
        finally:
            await subscription.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def _worker_progress(client: httpx.AsyncClient, url: str, report) -> None:
    previous = None
    while True:
        try:
            response = await client.get(url, timeout=0.8)
            stage = response.json().get("stage") if response.is_success else None
            if stage in {"decoding", "recognizing", "diarizing"} and stage != previous:
                report(stage)
                previous = stage
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(0.35)


@admin.post("/test")
async def test_transcription(request: Request, resources: RequestResources, use_cache: bool = True) -> JSONResponse:
    """Transcribe one file and report how long it took on this machine."""
    started = time.perf_counter()
    require_ready(request)
    data, filename, content_type, fields = await read_upload(request)
    form = dict(fields)
    progress_id = form.get("progress_id", "")
    track_progress = re.fullmatch(r"[0-9a-f-]{36}", progress_id) is not None
    bus = request.app.state.bus

    def stage(name: str) -> None:
        if track_progress:
            bus.publish({"type": "transcription", "id": progress_id, "stage": name})

    supervisor = request.app.state.supervisor
    stage("queued")
    await resources.enter_async_context(supervisor.inference_access())
    current = require_ready(request)
    metrics = request.app.state.metrics

    runtime = HEADS[current.variant].runtime
    format_ = form.get("response_format", "json" if runtime == "gigastt" else "verbose_json")
    if format_ == "diarized_json" and runtime not in ("parakeet", "sherpa"):
        raise ApiError(400, "Диаризация доступна с Parakeet, Nemotron ASR и T-one.", "diarization_unsupported")
    source = "microphone" if form.get("source") == "microphone" else "file"
    payload = [("model", PUBLIC_MODEL_ID), ("response_format", format_)]
    payload.extend((k, v) for k, v in fields if k == "language" or k in TIMESTAMP_GRANULARITIES)
    glossary_text = read_glossary(request.app.state.settings.hotwords_path)
    if runtime == "whisper":
        payload = whisper_prompt_fields(payload, glossary_text)
    cache = request.app.state.transcription_cache
    key = None
    if use_cache:
        key_scope = hashlib.sha256(request.headers.get("authorization", "").encode()).hexdigest()
        key = await asyncio.to_thread(
            transcription_key, data, filename, content_type, scope="dictation:" + key_scope, config=current.to_dict(),
            fields=payload, glossary=glossary_text,
        )
        await resources.enter_async_context(cache.access(key))
        cached = cache.get(key)
        if cached is not None:
            stage("cache_hit")
            return JSONResponse({**json.loads(cached.body), "cached": True,
                                 "elapsed": round(time.perf_counter() - started, 3), "rtf": None},
                                headers={"Cache-Control": "no-store"})

    stage("recognizing_speakers" if format_ == "diarized_json" else "recognizing")
    upstream_name = filename
    if runtime == "whisper":
        data = await whisper_audio(data)
        upstream_name, content_type = "audio.wav", "audio/wav"

    try:
        async with httpx.AsyncClient(timeout=TRANSCRIBE_TIMEOUT, trust_env=False) as client:
            base = supervisor.process.base_url
            worker_reports = track_progress and runtime in ("parakeet", "sherpa", "gigaam_v4")
            progress_task = asyncio.create_task(_worker_progress(
                client, f"{base}/internal/transcription-progress/{progress_id}", stage,
            )) if worker_reports else None
            try:
                response = await client.post(
                    f"{base}/v1/audio/transcriptions",
                    headers={"X-Kamerton-Progress": progress_id} if worker_reports else None,
                    files=multipart_upload_parts(data, upstream_name, content_type, payload),
                )
            finally:
                if progress_task is not None:
                    progress_task.cancel()
                    await asyncio.gather(progress_task, return_exceptions=True)
    except httpx.HTTPError as exc:
        raise ApiError(
            502, f"Движок не ответил: {exc}", "engine_unreachable", type_="server_error"
        ) from exc
    elapsed = time.perf_counter() - started

    if response.status_code >= 400:
        return JSONResponse(status_code=response.status_code, content=_engine_error(response))

    stage("preparing_result")
    text = ""
    body = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
            text = body.get("text", "")
    except ValueError:
        text = response.text

    audio_seconds = upload_duration_seconds(data)
    if audio_seconds is None and isinstance(body.get("duration"), (int, float)):
        audio_seconds = body["duration"]
    metrics.record(audio_seconds, elapsed, filename, source=source)
    result = {
        "text": text,
        "audio_seconds": audio_seconds,
        **({"segments": body["segments"]} if "segments" in body and format_ == "diarized_json" else {}),
    }
    if key is not None:
        cache.put(key, CachedResponse(json.dumps(result, ensure_ascii=False).encode()))
    return JSONResponse(
        {
            **result,
            "cached": False,
            "elapsed": round(elapsed, 3),
            "rtf": round(elapsed / audio_seconds, 3) if audio_seconds else None,
        },
        headers={"Cache-Control": "no-store"},
    )


@admin.get("/docs", include_in_schema=False)
async def swagger_ui(request: Request) -> HTMLResponse:
    """Swagger UI под тем же ключом, что и остальной `/api`.

    Схема описывает управляющие эндпоинты вместе с их телами запросов, поэтому она
    закрывается ровно тогда, когда закрыт сам сервис: пустой `API_KEY` — открыто,
    заданный — нужен ключ. Отдельного переключателя для документации нет намеренно,
    иначе владелец сервиса решал бы один вопрос дважды.

    Ключ принимается ещё и как `?api_key=`, как на SSE: браузер не умеет послать
    заголовок при переходе по ссылке. Пришедший так ключ страница подставляет в ссылку
    на схему — иначе Swagger получил бы 401 на первом же запросе к `/api/openapi.json`.
    """
    if request.app.state.settings.owner_access:
        return HTMLResponse(
            '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Камертон — API</title>'
            '<main><h1>Камертон — API</h1><p>Клиентские приложения используют Bearer-ключ. '
            'Управление консолью доступно по сессии владельца.</p>'
            '<a href="/api/openapi.json">Открыть схему OpenAPI (JSON)</a></main></html>',
            headers={"Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"},
        )
    presented = request.query_params.get("api_key", "")
    openapi_url = "/api/openapi.json"
    if presented:
        openapi_url += f"?api_key={quote(presented, safe='')}"
    return get_swagger_ui_html(
        openapi_url=openapi_url,
        title="GigaAM STT Console — API",
        oauth2_redirect_url=None,
    )


@admin.get("/openapi.json", include_in_schema=False)
async def openapi_schema(request: Request) -> JSONResponse:
    return JSONResponse(request.app.openapi())


def _engine_error(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = {"error": {"message": response.text[:500], "code": "engine_error"}}
    if isinstance(body, dict) and "error" in body:
        return body
    return {"error": {"message": str(body)[:500], "code": "engine_error"}}


router.include_router(admin)
