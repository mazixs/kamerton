"""OpenAI-compatible facade in front of the engine.

The engine already speaks the OpenAI transcription API, so the console adds only
what it lacks: an API key, a model listing, human-readable failures when nothing is
deployed yet, an upload limit, and latency measurement. The engine's own JSON is
never rewritten and uploads reach it byte for byte, browser WebM included since
2.17.0 — the console reads the length of one to time it, and changes nothing.
"""

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated, Any
from unicodedata import category

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.datastructures import FormData, UploadFile
from starlette.types import Message, Receive, Scope, Send

from .auth import require_client_key
from .audio_decode import whisper_audio
from .catalog import HEADS, PUBLIC_MODEL_ID, openai_model_id
from .errors import ApiError
from .glossary import read_glossary, whisper_prompt_fields
from .owner_access import require_active_client_key
from .state import EngineConfig
from .transcription_cache import MAX_ENTRY_BYTES, CachedResponse, transcription_key
from .wavinfo import wav_duration_seconds
from .webminfo import webm_duration_seconds

router = APIRouter(dependencies=[Depends(require_client_key)])
native_router = APIRouter(dependencies=[Depends(require_client_key)])

TRANSCRIBE_TIMEOUT = httpx.Timeout(None, connect=10.0)
MODEL_VARIANTS = {openai_model_id(variant): variant for variant in HEADS}
CURRENT_MODEL_ALIASES = {PUBLIC_MODEL_ID, "whisper-1"}

# Поля, которые клиент присылает, а движок не читает. `prompt` здесь не мелочь:
# у Whisper это и есть носитель пользовательского словаря, и клиенты диктовки
# (OpenWhispr и родня) шлют его на любой самохостный адрес, считая нас
# Whisper-семейством. Движок - трансдьюсер, контекст задается глоссарием на
# сервере, и молчаливое 200 в ответ означало бы, что словарь клиента не работает
# и никто об этом не узнает. Заголовок - единственный канал до чужого приложения.
IGNORED_FIELDS = ("prompt",)
GLOSSARY_SOURCE = "server-hotwords"
HOP_BY_HOP = {
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "host",
    "authorization",
}


def _serving_config(request: Request, *, allow_previous: bool = False) -> EngineConfig | None:
    supervisor = request.app.state.supervisor
    if supervisor.status == "ready" or (
        allow_previous and supervisor.status == "error" and supervisor.detail_code == "download.failed"
    ):
        return supervisor.current
    return None


def require_ready(request: Request, *, allow_previous: bool = False) -> EngineConfig:
    current = _serving_config(request, allow_previous=allow_previous)
    if current is not None:
        return current
    supervisor = request.app.state.supervisor
    hints = {
        "stopped": "Модель еще не запущена. Разверните ее в консоли.",
        "downloading": "Модель скачивается, это делается один раз. Повторите запрос позже.",
        "starting": "Движок запускается, обычно это пара секунд.",
        "error": "Движок не работает. Подробности доступны в разделе статуса сервиса.",
    }
    raise ApiError(
        503,
        hints.get(supervisor.status, "Движок недоступен."),
        "engine_not_ready",
        type_="server_error",
        headers={"Retry-After": "5"},
    )


class _BodyLimitExceeded(OSError):
    """При OSError multipart-парсер закрывает уже созданные временные файлы."""


@asynccontextmanager
async def _bounded_request(request: Request, body_limit: int) -> AsyncIterator[Request]:
    limit = request.app.state.settings.max_upload_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdecimal() and int(declared) > body_limit:
        raise ApiError(413, _too_big(limit), "file_too_large")
    received = 0

    async def receive() -> Message:
        nonlocal received
        message = await request.receive()
        received += len(message.get("body", b""))
        if received > body_limit:
            raise _BodyLimitExceeded
        return message

    bounded = Request(request.scope, receive=receive)
    try:
        yield bounded
    except _BodyLimitExceeded:
        raise ApiError(413, _too_big(limit), "file_too_large") from None
    finally:
        await bounded.close()


@asynccontextmanager
async def parse_upload(request: Request) -> AsyncIterator[tuple[UploadFile, FormData]]:
    limit = request.app.state.settings.max_upload_bytes
    async with _bounded_request(request, limit + 8192) as bounded:
        form = await bounded.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ApiError(400, "Не передан аудиофайл в поле file.", "missing_file")
        if upload.size is not None and upload.size > limit:
            raise ApiError(413, _too_big(limit), "file_too_large")
        yield upload, form


TIMESTAMP_GRANULARITIES = frozenset({"timestamp_granularities", "timestamp_granularities[]"})


def upload_basename(filename: str | None) -> str:
    # Учитываем оба разделителя независимо от ОС клиента. Имя нигде не служит путём.
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if category(char) not in {"Cc", "Cf"})
    return name if name.strip() and name.strip() not in {".", ".."} else ""


async def read_upload(request: Request) -> tuple[bytes, str, str, list[tuple[str, str]]]:
    async with parse_upload(request) as (upload, form):
        return await upload.read(), upload_basename(upload.filename), upload_type(upload), upload_fields(form)


def upload_fields(form: FormData) -> list[tuple[str, str]]:
    scalars, granularities = {}, []
    for key, value in form.multi_items():
        if key == "file" or not isinstance(value, str):
            continue
        if key in TIMESTAMP_GRANULARITIES:
            granularities.append((key, value))
        else:
            scalars[key] = value
    return [*scalars.items(), *granularities]


def upload_type(upload: UploadFile) -> str:
    return upload.content_type or "application/octet-stream"


async def request_resources() -> AsyncIterator[AsyncExitStack]:
    async with AsyncExitStack() as stack:
        yield stack


RequestResources = Annotated[AsyncExitStack, Depends(request_resources, scope="request")]


def multipart_upload_parts(
    data: bytes, filename: str, content_type: str, fields: list[tuple[str, str]],
) -> list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]]:
    # Последовательность частей сохраняет порядок повторений и обоих имён поля.
    return [*((key, (None, value)) for key, value in fields), ("file", (filename or "audio", data, content_type))]


def upload_duration_seconds(data: bytes) -> float | None:
    """How long the recording is, for the real-time factor — None when unreadable.

    Only the two containers the console can measure without decoding: WAV, which the
    page records itself, and WebM/Opus, which is what every browser dictation client
    sends. Everything else the engine decodes but nobody here measures, so its
    requests contribute wall time to the metrics and no RTF.
    """
    return wav_duration_seconds(data) or webm_duration_seconds(data)


def _too_big(limit: int) -> str:
    return (
        f"Файл больше допустимых {limit // (1024 * 1024)} МБ. "
        "Увеличьте MAX_UPLOAD_MB в .env или разрежьте запись."
    )


def ignored_field_headers(fields: dict[str, str]) -> dict[str, str]:
    """Заголовки ответа про поля запроса, которые никуда не дошли.

    Пусто, когда таких полей нет: обвешивать заголовками каждый ответ ради
    сообщения, которое почти всегда неприменимо, значило бы приучить его
    игнорировать.
    """
    ignored = [name for name in IGNORED_FIELDS if fields.get(name, "").strip()]
    if not ignored:
        return {}
    return {
        "X-Ignored-Fields": ", ".join(ignored),
        "X-Glossary-Source": GLOSSARY_SOURCE,
    }


def _warn_once(request: Request, ignored: str) -> None:
    """Одна строка в логи на весь процесс, а не на каждый запрос.

    Клиент, настроенный слать словарь в `prompt`, шлет его всегда, и запись на
    каждую диктовку превратила бы раздел «Логи» в один повторяющийся абзац -
    ровно тот способ, которым предупреждение перестает читаться.
    """
    state = request.app.state
    if getattr(state, "ignored_fields_warned", False):
        return
    state.ignored_fields_warned = True
    state.bus.publish_log(
        f"client sent {ignored}: the engine ignores it, "
        "the glossary is configured on the server"
    )


class _EngineStream(StreamingResponse):
    def __init__(self, client: httpx.AsyncClient, upstream: httpx.Response,
                 body: AsyncIterator[bytes], headers: dict[str, str]) -> None:
        super().__init__(body, status_code=upstream.status_code, headers=headers)
        self.client = client
        self.upstream = upstream

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # BackgroundTask не вызывается, если upstream или отправка ответа упали.
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await self.upstream.aclose()
            finally:
                await self.client.aclose()


class _CheckedUpload(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, check: Callable[[], None]) -> None:
        self.stream = stream
        self.check = check

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.check()
        async for chunk in self.stream:
            yield chunk

    async def aclose(self) -> None:
        await self.stream.aclose()


async def _open_engine_stream(
    method: str, url: str, *, before_upload: Callable[[], None] | None = None, **request_options: Any,
) -> tuple[httpx.AsyncClient, httpx.Response]:
    client = httpx.AsyncClient(timeout=TRANSCRIBE_TIMEOUT, trust_env=False)
    try:
        engine_request = client.build_request(method, url, **request_options)
        if before_upload is not None:
            engine_request.stream = _CheckedUpload(engine_request.stream, before_upload)
        response = await client.send(engine_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise ApiError(
            502,
            f"Движок не ответил: {exc}",
            "engine_unreachable",
            type_="server_error",
        ) from exc
    except BaseException:
        await client.aclose()
        raise
    return client, response


def _requested_variant(form: FormData) -> str | None:
    models = form.getlist("model")
    if not models:
        return None
    model = models[0]
    if len(models) != 1 or not isinstance(model, str) or not model.strip():
        raise ApiError(400, "Передайте один непустой ID модели в поле model.", "invalid_model", param="model")
    if model in CURRENT_MODEL_ALIASES:
        return None
    if model not in MODEL_VARIANTS:
        raise ApiError(404, "Неизвестный ID модели. Получите доступные ID через GET /v1/models.",
                       "model_not_found", param="model")
    return MODEL_VARIANTS[model]


@router.post("/v1/audio/transcriptions")
async def transcriptions(request: Request, resources: RequestResources) -> Response:
    # Секундомер запускается до чтения загрузки: пользователь ждёт всю дорогу, а
    # не только ту её часть, где работает движок.
    started = time.perf_counter()
    settings = request.app.state.settings
    metrics = request.app.state.metrics
    supervisor = request.app.state.supervisor

    async def before_use() -> None:
        if await request.is_disconnected():
            raise ApiError(499, "Клиент прервал запрос.", "client_disconnected")
        if settings.owner_access:
            await require_active_client_key(request)

    async with parse_upload(request) as (upload, form):
        variant = _requested_variant(form)
        data = await upload.read()
        filename, content_type, fields = upload_basename(upload.filename), upload_type(upload), upload_fields(form)

    cache = request.app.state.transcription_cache
    options = dict(fields)
    cacheable = (options.get("response_format", "json") in {"json", "text", "verbose_json", "srt", "vtt", "diarized_json"}
                 and options.get("stream", "false").lower() == "false")
    key_scope = hashlib.sha256(request.headers.get("authorization", "").encode()).hexdigest()

    def effective_fields(config: EngineConfig, glossary: str) -> list[tuple[str, str]]:
        return whisper_prompt_fields(fields, glossary) if HEADS[config.variant].runtime == "whisper" else fields

    async def fingerprint(config: EngineConfig, glossary: str) -> bytes:
        return await asyncio.to_thread(
            transcription_key, data, filename, content_type, scope="api:" + key_scope,
            config=config.to_dict(), fields=effective_fields(config, glossary), glossary=glossary,
        )

    def cached_response(key: bytes) -> Response | None:
        cached = cache.get(key)
        if cached is None:
            return None
        return Response(cached.body, status_code=cached.status,
                        headers={**dict(cached.headers), "X-Kamerton-Cache": "HIT"})

    def preview_config() -> EngineConfig | None:
        if variant is not None and not supervisor.model_available(variant):
            return None
        current = _serving_config(request, allow_previous=True)
        if variant is None or (current is not None and current.variant == variant):
            return current
        return supervisor.default_config(variant)

    preview = preview_config() if cacheable else None
    glossary_preview = read_glossary(settings.hotwords_path) if preview is not None else None
    preview_key = None
    if preview is not None and glossary_preview is not None:
        preview_key = await fingerprint(preview, glossary_preview)
        await before_use()
        if preview == preview_config() and glossary_preview == read_glossary(settings.hotwords_path):
            if hit := cached_response(preview_key):
                return hit

    await resources.enter_async_context(supervisor.inference_access(variant, before_use))
    config = require_ready(request, allow_previous=True)
    generation = supervisor.process.generation

    def check_engine() -> None:
        require_ready(request, allow_previous=True)
        if supervisor.process.generation != generation:
            raise ApiError(503, "Движок перезапустился. Обновите список моделей и повторите запрос.",
                           "engine_not_ready", "server_error", headers={"Retry-After": "5"})

    duration = upload_duration_seconds(data)
    runtime = HEADS[config.variant].runtime
    glossary_text = read_glossary(settings.hotwords_path)
    cache_key = None
    if cacheable:
        cache_key = preview_key if config == preview and glossary_text == glossary_preview else await fingerprint(config, glossary_text)
        assert cache_key is not None
        await resources.enter_async_context(cache.access(cache_key))
        await before_use()
        check_engine()
        if hit := cached_response(cache_key):
            return hit
    fields = effective_fields(config, glossary_text)
    upstream_name = filename
    if runtime == "whisper":
        data = await whisper_audio(data)
        duration = upload_duration_seconds(data)
        upstream_name, content_type = "audio.wav", "audio/wav"

    await before_use()
    check_engine()
    client, response = await _open_engine_stream(
        "POST",
        f"{supervisor.process.base_url}/v1/audio/transcriptions",
        # Порт используется повторно. Тело отправляем только в то поколение,
        # которое выбрали перед обработкой файла. Здесь соединение уже открыто.
        before_upload=check_engine,
        files=multipart_upload_parts(data, upstream_name, content_type, fields),
    )

    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in HOP_BY_HOP
    }
    ignored = {} if runtime == "whisper" else ignored_field_headers(dict(fields))
    if ignored:
        if runtime == "gigastt":
            _warn_once(request, ignored["X-Ignored-Fields"])
        else:
            ignored.pop("X-Glossary-Source", None)
    headers.update(ignored)
    eligible = (cache_key is not None and response.status_code == 200
                and not response.headers.get("Content-Disposition") and not response.headers.get("Set-Cookie")
                and not response.headers.get("Content-Type", "").startswith("text/event-stream"))
    if cache_key is not None:
        headers.update({"Cache-Control": "no-store", "X-Kamerton-Cache": "MISS" if eligible else "BYPASS"})

    async def body():
        saved = bytearray() if eligible else None
        async for chunk in response.aiter_raw():
            if saved is not None:
                if len(saved) + len(chunk) <= MAX_ENTRY_BYTES:
                    saved.extend(chunk)
                else:
                    saved = None
            yield chunk
        if saved is not None and cache_key is not None:
            cache.put(cache_key, CachedResponse(bytes(saved), response.status_code, tuple(headers.items())))
        if response.status_code < 400:
            metrics.record(duration, time.perf_counter() - started, filename)

    return _EngineStream(client, response, body(), headers)


@router.post("/v1/audio/translations")
async def translations(_request: Request) -> JSONResponse:
    raise ApiError(
        400,
        "Камертон распознает речь, но не переводит ее. Используйте "
        "/v1/audio/transcriptions для получения текста на языке записи.",
        "translations_not_supported",
    )


@router.get("/v1/models")
async def models(request: Request, response: Response) -> dict[str, Any]:
    supervisor = request.app.state.supervisor
    current = _serving_config(request, allow_previous=True)
    response.headers["Cache-Control"] = "no-store"
    data = [
        {
            "id": openai_model_id(variant), "object": "model", "created": 0,
            "owned_by": "gigaam" if head.runtime in ("gigastt", "gigaam_v4") else head.runtime,
            "variant": variant, "deployed": current is not None and current.variant == variant,
        }
        for variant, head in HEADS.items() if supervisor.model_available(variant)
    ]
    if current is not None:
        runtime = HEADS[current.variant].runtime
        data.append({
            "id": PUBLIC_MODEL_ID, "object": "model", "created": 0,
            "owned_by": "gigaam" if runtime in ("gigastt", "gigaam_v4") else runtime,
            "variant": current.variant, "deployed": True,
        })
    return {"object": "list", "data": data}


def _passthrough_headers(response: httpx.Response) -> dict[str, str]:
    return {key: value for key, value in response.headers.items() if key.lower() not in HOP_BY_HOP}


async def _native_reload(
    request: Request, url: str, params: list[tuple[str, str]], body: bytes, headers: dict[str, str],
) -> Response:
    async def reload() -> Response:
        current = require_ready(request)
        if HEADS[current.variant].runtime != "gigastt":
            raise ApiError(404, "Маршрут доступен только с GigaSTT.", "native_route_unavailable")
        async with httpx.AsyncClient(timeout=TRANSCRIBE_TIMEOUT, trust_env=False) as client:
            try:
                async with client.stream("POST", url, params=params, content=body, headers=headers) as response:
                    content = b"".join([chunk async for chunk in response.aiter_raw()])
                    return Response(
                        content, status_code=response.status_code, headers=_passthrough_headers(response),
                    )
            except httpx.HTTPError as exc:
                raise ApiError(
                    502, f"Движок не ответил: {exc}", "engine_unreachable", type_="server_error"
                ) from exc

    response = await request.app.state.supervisor.run_native_reload(reload)
    if response is not None:
        return response
    # Такой же конфликт, как у upstream, вместо очереди повторных reload.
    return JSONResponse(
        {"error": "A model reload is already in progress", "code": "reload_in_progress"},
        status_code=409,
    )


# `include_in_schema=False`: одна запись с подстановкой `{path}` ничего не сообщает
# читателю схемы, а три метода на одном маршруте дают FastAPI повторяющийся
# operation id и предупреждение при каждой сборке схемы. Родные эндпоинты движка
# описаны в README, документация у них своя — апстримная.
@native_router.api_route(
    "/v1/{path:path}", methods=["GET", "POST", "DELETE"], include_in_schema=False
)
async def passthrough(request: Request, path: str, resources: RequestResources) -> Response:
    """Everything else the engine exposes (native /v1/transcribe, /v1/jobs, ...)."""
    require_ready(request)
    current = request.app.state.supervisor.current
    if current and HEADS[current.variant].runtime != "gigastt":
        raise ApiError(404, "Маршрут доступен только с GigaSTT.", "native_route_unavailable")
    settings = request.app.state.settings
    url = f"{settings.engine_base_url}/v1/{path}"
    async with _bounded_request(request, settings.engine_body_limit_bytes) as bounded:
        body = await bounded.body()
    # Ключ консоли не должен попасть в URL движка и технические логи.
    params = [(k, v) for k, v in request.query_params.multi_items() if k != "api_key"]
    headers = {
        key: value for key, value in request.headers.items() if key.lower() not in HOP_BY_HOP
    }
    # Проверяем путь после нормализации HTTPX, а не исходный сегмент catch-all.
    if request.method == "POST" and httpx.URL(url).path == "/v1/admin/reload":
        return await _native_reload(request, url, params, body, headers)

    await resources.enter_async_context(request.app.state.supervisor.inference_access())
    current = require_ready(request)
    if HEADS[current.variant].runtime != "gigastt":
        raise ApiError(404, "Маршрут доступен только с GigaSTT.", "native_route_unavailable")

    client, response = await _open_engine_stream(
        request.method,
        url,
        params=params,
        content=body,
        headers=headers,
    )

    return _EngineStream(client, response, response.aiter_raw(), _passthrough_headers(response))
