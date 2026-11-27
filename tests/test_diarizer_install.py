import asyncio

from console.downloader import DownloadError
from console.model_assets import DIARIZATION


async def test_diarizer_install_shares_progress_and_reports_success(client_stopped, monkeypatch):
    gate = asyncio.Event()
    calls = []

    async def download(targets, report):
        calls.extend(targets)
        report({"phase": "progress", "percent": 47})
        await gate.wait()
        directory, asset = targets[0]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / asset.name).touch()
        with (directory / asset.name).open("r+b") as weights:
            weights.truncate(asset.size)

    monkeypatch.setattr("console.api.runtime_available", lambda *_: True)
    monkeypatch.setattr("console.api.download_assets", download)
    subscription = client_stopped.app.state.bus.subscribe()
    first = asyncio.create_task(client_stopped.post("/api/models/diarization"))
    second = asyncio.create_task(client_stopped.post("/api/models/diarization"))
    try:
        for expected in (None, 47):
            event = await asyncio.wait_for(anext(subscription), 1)
            assert (event["type"], event["status"], event["progress"]) == ("diarization", "downloading", expected)
        assert (await client_stopped.get("/api/status")).json()["diarization"]["progress"] == 47
    finally:
        gate.set()
        replies = await asyncio.gather(first, second)
        await subscription.aclose()
    assert len(calls) == 1
    assert all(reply.status_code == 200 and reply.json()["installed_bytes"] == DIARIZATION.size for reply in replies)
    assert (await client_stopped.get("/api/status")).json()["diarization"]["status"] == "installed"


async def test_diarizer_download_error_exposes_actionable_status_only(client_stopped, monkeypatch):
    async def download(*_):
        raise DownloadError("http", "internal host details", 69, 429)

    monkeypatch.setattr("console.api.runtime_available", lambda *_: True)
    monkeypatch.setattr("console.api.download_assets", download)
    result = await client_stopped.post("/api/models/diarization")
    assert result.status_code == 502 and "internal host" not in result.text
    status = (await client_stopped.get("/api/status")).json()["diarization"]
    assert (status["status"], status["kind"], status["http_status"]) == ("error", "http", 429)
