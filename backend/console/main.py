"""Application wiring.

Run with: `uvicorn console.main:create_app --factory --host 0.0.0.0 --port 8080`
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import __version__, owner_access, proxy, web_ui
from .api import router as api_router
from .compare import clean_compare_temp_root, router as compare_router
from .errors import ApiError, api_error_handler
from .events import EventBus
from .metrics import Metrics
from .owner_store import OwnerStore
from .settings import Settings, get_settings
from .storage import Storage
from .supervisor import Supervisor
from .transcription_cache import TranscriptionCache

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    network = owner_access.public_network(settings) if settings.owner_access else None
    store = OwnerStore(settings.data_dir)
    if not settings.owner_access:
        store.guard_local(rollback=settings.allow_owner_local_rollback, key=settings.api_key)
    owner_store = store if settings.owner_access else None
    bus = EventBus(logger=logging.getLogger("console"))
    metrics = Metrics(settings.metrics_path)
    supervisor = Supervisor(settings, bus)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if owner_store is not None:
            await run_in_threadpool(owner_store.check)
        try:
            clean_compare_temp_root(settings)
        except OSError:
            supervisor.block_compare_storage()
            logging.getLogger("console").warning(
                "Не удалось очистить временный каталог; сравнение моделей отключено."
            )
        restore = asyncio.create_task(supervisor.restore_on_boot())
        try:
            yield
        finally:
            pending = [restore, *app.state.deploy_tasks]
            if app.state.diarization_task is not None:
                pending.append(app.state.diarization_task)
            for task in pending:
                task.cancel()
            try:
                await asyncio.gather(*pending, return_exceptions=True)
                if not restore.cancelled():
                    restore.result()
            finally:
                app.state.transcription_cache.close()
                await supervisor.shutdown()

    app = FastAPI(
        title="GigaAM STT Console",
        summary="Веб-консоль и OpenAI-совместимый API поверх движка GigaSTT",
        version=__version__,
        lifespan=lifespan,
        # В публичном профиле ASGI намеренно видит HTTP до прокси: не строим
        # абсолютные редиректы с лишним слешем на внутренней схеме.
        redirect_slashes=not settings.owner_access,
        # Штатные маршруты документации выключены: свои, на `/api/docs` и
        # `/api/openapi.json`, живут в `console.api` под проверкой ключа — схема
        # закрывается вместе с сервисом, а не остаётся открытой сама по себе.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.bus = bus
    app.state.metrics = metrics
    app.state.storage = Storage(settings.model_dir, settings.data_dir)
    app.state.supervisor = supervisor
    app.state.transcription_cache = TranscriptionCache()

    app.state.compare_lock = asyncio.Lock()
    app.state.diarization_lock = asyncio.Lock()
    app.state.diarization_task = None
    app.state.diarization_status = {}
    app.state.deploy_tasks = set()

    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(api_router)
    app.include_router(compare_router)
    app.include_router(proxy.router)
    if owner_store is not None:
        app.state.owner_store = owner_store
        app.state.login_slots = asyncio.Semaphore(2)
        app.add_middleware(owner_access.OwnerBoundary, network=network, login_assets=web_ui.public_login_assets())
        app.include_router(owner_access.router)

        @app.exception_handler(RequestValidationError)
        async def invalid_request(request: Request, _exc):
            # Стандартный 422 содержит input, иногда со всем присланным JSON.
            return await api_error_handler(request, ApiError(422, "Проверьте поля запроса.", "invalid_request"))

        @app.get("/login", include_in_schema=False)
        async def login_page():
            return web_ui.page("login.html", "no-store")
    else:
        app.include_router(proxy.native_router)

    @app.get("/auth/session", include_in_schema=False)
    async def auth_session(request: Request):
        result = (owner_access.session_result(request.state.owner_csrf) if owner_store is not None
                  else {"mode": "local"})
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    assets = web_ui.WEB_ROOT / "assets"
    if assets.is_dir():
        app.mount("/static/assets", web_ui.WebAssets(directory=assets), name="web-assets")

    worklet = web_ui.WEB_ROOT / "capture-worklet.js"
    if worklet.is_file():
        @app.get("/static/capture-worklet.js", include_in_schema=False)
        async def capture_worklet():
            return FileResponse(worklet, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    async def index():
        return web_ui.page("index.html", "no-cache, must-revalidate")

    return app
