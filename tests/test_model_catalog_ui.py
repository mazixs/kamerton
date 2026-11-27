"""Причины ошибок, которые каталог показывает у конкретной модели."""

import json

import httpx
import pytest

from console.state import EngineConfig


@pytest.mark.parametrize(("event", "expected"), [
    ({"kind": "network", "http_status": 403}, ("http", 403)),
    ({"kind": "network", "message": "HTTP 403: synthetic detail"}, ("network", None)),
    ({"kind": "private upstream diagnostic"}, ("network", None)),
])
async def test_cli_error_only_uses_structured_status(console_settings, tmp_path, event, expected):
    from console.downloader import DownloadError, download

    engine = tmp_path / "error_engine.py"
    line = json.dumps({"phase": "error", **event})
    engine.write_text(f"print({line!r})\nraise SystemExit(69)\n", encoding="utf-8")
    settings = console_settings.model_copy(update={"engine_bin": str(engine)})
    with pytest.raises(DownloadError) as exc:
        await download(settings, "rnnt", lambda event: None)
    assert (exc.value.kind, exc.value.http_status) == expected
    assert "private" not in exc.value.message


@pytest.mark.parametrize(("http_status", "attempts"), [(401, 1), (403, 1), (429, 3), (503, 3)])
async def test_weight_server_status_is_safe_and_attributed(client_ready, monkeypatch, http_status, attempts):
    supervisor = client_ready.app.state.supervisor
    monkeypatch.setattr("console.supervisor.DOWNLOAD_RETRY_DELAYS", (0, 0))
    client = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(http_status, text="private upstream diagnostics")

    def client_for_download(**kwargs):
        if kwargs.get("follow_redirects"):
            return client(transport=httpx.MockTransport(respond), **kwargs)
        return client(**kwargs)

    monkeypatch.setattr("console.downloader.httpx.AsyncClient", client_for_download)
    await supervisor.deploy(EngineConfig(variant="whisper_tiny"))
    status = (await client_ready.get("/api/status")).json()
    assert len(requests) == attempts
    assert status["engine"]["running"] and status["engine"]["variant"] == "rnnt"
    assert status["detail_code"] == "download.failed"
    assert status["detail_params"] == {
        "kind": "http", "http_status": http_status, "variant": "whisper_tiny",
        "attempts": attempts, "running": "rnnt",
    }
    assert "private upstream" not in status["detail"] and "https://" not in status["detail"]


async def test_start_failure_has_safe_kind_after_rollback(client_ready, monkeypatch):
    from console.engine import EngineStartupError

    supervisor = client_ready.app.state.supervisor
    original = supervisor.process.wait_healthy

    async def wait_healthy(timeout):
        if supervisor.process.config.variant == "ml_ctc":
            raise EngineStartupError("Synthetic private diagnostic", "timeout")
        return await original(timeout)

    monkeypatch.setattr(supervisor.process, "wait_healthy", wait_healthy)
    await supervisor.deploy(EngineConfig(variant="ml_ctc"))
    status = (await client_ready.get("/api/status")).json()
    assert status["detail_code"] == "rollback.done"
    assert status["detail_params"]["failed"] == "ml_ctc"
    assert status["detail_params"]["start_kind"] == "timeout"
    assert status["engine"]["variant"] == "rnnt" and status["engine"]["running"]
