import asyncio
import hashlib

import httpx
import pytest

from console import proxy
from console.catalog import openai_model_id
from console.state import EngineConfig
from conftest import opus_code3_packet, wav_bytes, webm_opus_bytes

AUDIO = {"file": ("a.wav", wav_bytes(seconds=2), "audio/wav")}


async def test_transcription_proxied_to_engine(client_ready):
    response = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"model": "whisper-1"}
    )
    assert response.status_code == 200
    assert response.json() == {"text": "привет мир"}


async def test_text_format_passes_through(client_ready):
    response = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"response_format": "text"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "привет мир"


async def test_srt_and_verbose_json_pass_through(client_ready):
    srt = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"response_format": "srt"}
    )
    assert "00:00:00,000 --> 00:00:02,000" in srt.text

    verbose = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"response_format": "verbose_json"}
    )
    payload = verbose.json()
    assert payload["language"] == "ru" and payload["segments"][0]["text"] == "привет мир"


async def test_streaming_sse_passes_through(client_ready):
    async with client_ready.stream(
        "POST", "/v1/audio/transcriptions", files=AUDIO, data={"stream": "true"}
    ) as response:
        body = "".join([chunk async for chunk in response.aiter_text()])
    assert "transcript.text.delta" in body
    assert "[DONE]" in body


@pytest.mark.parametrize("path", ["/v1/audio/transcriptions", "/v1/transcribe"])
async def test_failed_stream_releases_engine_and_is_not_a_success(client_ready, path, monkeypatch):
    class BrokenStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"partial"
            raise httpx.ReadError("test stream ended early")

        async def aclose(self):
            self.closed = True

    stream = BrokenStream()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))
    upstream = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: upstream)
    with pytest.raises(httpx.ReadError):
        await client_ready.post(path, files=AUDIO)
    assert stream.closed and upstream.is_closed
    assert client_ready.app.state.metrics.snapshot()["count"] == 0


@pytest.mark.parametrize("path", ["/v1/audio/transcriptions", "/v1/transcribe"])
async def test_engine_connection_error_returns_502_and_closes_client(client_ready, path, monkeypatch):
    def fail_connection(request):
        raise httpx.ConnectError("connection refused", request=request)

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(fail_connection))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: upstream)

    response = await client_ready.post(path, files=AUDIO)

    assert response.status_code == 502
    assert response.json()["error"] == {
        "message": "Движок не ответил: connection refused",
        "type": "server_error",
        "code": "engine_unreachable",
        "param": None,
    }
    assert upstream.is_closed


@pytest.mark.parametrize("path", ["/v1/audio/transcriptions", "/v1/transcribe"])
async def test_cancelled_engine_send_closes_client(client_ready, path, monkeypatch):
    async def cancel_send(_request):
        raise asyncio.CancelledError

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(cancel_send))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: upstream)

    with pytest.raises(asyncio.CancelledError):
        await client_ready.post(path, files=AUDIO)

    assert upstream.is_closed


async def test_client_lists_downloaded_models_and_starts_requested_model(client_stopped):
    client = client_stopped
    supervisor = client.app.state.supervisor

    async def check_models(downloaded, variant):
        result = await client.get("/v1/models")
        assert result.headers["cache-control"] == "no-store"
        payload = result.json()
        assert payload["object"] == "list"
        assert [model["id"] for model in payload["data"]] == [
            *(openai_model_id(head) for head in downloaded), *(["kamerton"] if variant else []),
        ]
        assert all(model["deployed"] == (model["variant"] == variant) for model in payload["data"])
        assert all(not any(char.isspace() for char in model["id"]) for model in payload["data"])
        assert (await client.get("/api/client-models")).json() == payload
        assert (await client.get("/api/status")).json()["engine"]["variant"] == variant

    await check_models([], None)
    await supervisor.deploy(EngineConfig())
    await check_models(["rnnt"], "rnnt")
    await supervisor.deploy(EngineConfig(variant="ml_ctc"))
    await supervisor.stop_engine()
    await check_models(["rnnt", "ml_ctc"], None)
    response = await client.post("/v1/audio/transcriptions", files=AUDIO, data={"model": openai_model_id("rnnt")})
    assert response.status_code == 200
    assert (await engine_upload(client))["variant"] == "rnnt"
    await check_models(["rnnt", "ml_ctc"], "rnnt")
    assert supervisor.state_file.load().desired.variant == "ml_ctc"
    response = await client.post("/v1/audio/transcriptions", files=AUDIO, data={"model": openai_model_id("ml_ctc")})
    assert response.status_code == 200
    assert (await engine_upload(client))["variant"] == "ml_ctc"
    pid = supervisor.process.pid
    for model_id in ("kamerton", "whisper-1", openai_model_id("ml_ctc")):
        response = await client.post("/v1/audio/transcriptions", files=AUDIO, data={"model": model_id})
        assert response.status_code == 200
        assert response.headers["X-Kamerton-Cache"] == ("HIT" if model_id == openai_model_id("ml_ctc") else "MISS")
        assert (await engine_upload(client))["variant"] == "ml_ctc"
    for model_id, code in (
        (openai_model_id("ml_ctc_large"), "model_not_available"), ("made-up-model", "model_not_found"),
    ):
        response = await client.post("/v1/audio/transcriptions", files=AUDIO, data={"model": model_id})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == code
        assert response.json()["error"]["param"] == "model"
    assert client.app.state.metrics.snapshot()["count"] == 4
    assert supervisor.process.pid == pid
    await supervisor.stop_engine()
    await check_models(["rnnt", "ml_ctc"], None)


async def test_transcription_checks_process_generation_when_sending_upload(client_ready, monkeypatch):
    supervisor = client_ready.app.state.supervisor
    open_engine_stream = proxy._open_engine_stream
    generation = supervisor.process.generation

    async def restart_before_connecting(*args, **kwargs):
        # Имитируем смену процесса в обход диспетчера.
        await supervisor.process.stop()
        await supervisor.process.start(EngineConfig())
        await supervisor.process.wait_healthy()
        assert supervisor.process.generation > generation
        return await open_engine_stream(*args, **kwargs)

    monkeypatch.setattr(proxy, "_open_engine_stream", restart_before_connecting)
    response = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"model": openai_model_id("rnnt")},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "engine_not_ready"
    assert response.headers["retry-after"] == "5"
    assert client_ready.app.state.metrics.snapshot()["count"] == 0


async def test_model_switch_waits_for_stream_and_same_model_can_reuse_engine(client_ready, monkeypatch):
    supervisor = client_ready.app.state.supervisor
    await supervisor.deploy(EngineConfig(variant="ml_ctc"))
    await supervisor.deploy(EngineConfig())
    pid = supervisor.process.pid
    waiting_for_stream, release_stream = asyncio.Event(), asyncio.Event()
    open_engine_stream = proxy._open_engine_stream

    async def hold_first_stream(*args, **kwargs):
        client, response = await open_engine_stream(*args, **kwargs)
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            chunks = response.aiter_raw

            async def delayed_chunks():
                waiting_for_stream.set()
                await release_stream.wait()
                async for chunk in chunks():
                    yield chunk

            response.aiter_raw = delayed_chunks
        return client, response

    monkeypatch.setattr(proxy, "_open_engine_stream", hold_first_stream)

    async def recognize(variant, **fields):
        return await client_ready.post("/v1/audio/transcriptions", files=AUDIO,
                                       data={"model": openai_model_id(variant), **fields})

    first = asyncio.create_task(recognize("rnnt", stream="true"))
    pending = [first]
    try:
        await asyncio.wait_for(waiting_for_stream.wait(), 5)
        same = await asyncio.wait_for(recognize("rnnt"), 5)
        assert same.status_code == 200 and supervisor.process.pid == pid
        second = asyncio.create_task(recognize("ml_ctc"))
        pending.append(second)
        async with asyncio.timeout(5):
            while not supervisor._lock.locked():
                await asyncio.sleep(0.01)
        assert supervisor.process.pid == pid and not second.done()
        release_stream.set()
        assert "[DONE]" in (await asyncio.wait_for(first, 5)).text
        assert (await asyncio.wait_for(second, 15)).status_code == 200
        assert (await engine_upload(client_ready))["variant"] == "ml_ctc"
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def test_failed_request_model_restores_previous_engine(client_ready, monkeypatch):
    supervisor = client_ready.app.state.supervisor
    await supervisor.deploy(EngineConfig(variant="ml_ctc"))
    await supervisor.deploy(EngineConfig())
    monkeypatch.setenv("FAKE_UNHEALTHY_VARIANT", "ml_ctc")
    monkeypatch.setattr("console.supervisor.STARTUP_TIMEOUT", 2)
    rejected = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"model": openai_model_id("ml_ctc")},
    )
    assert rejected.status_code == 503 and rejected.json()["error"]["code"] == "model_start_failed"
    assert supervisor.current.variant == supervisor.state_file.load().desired.variant == "rnnt"
    assert (await client_ready.post("/v1/audio/transcriptions", files=AUDIO, data={"model": "kamerton"})).status_code == 200


async def test_request_model_preserves_local_native_job_engine(client_ready):
    supervisor = client_ready.app.state.supervisor
    await supervisor.deploy(EngineConfig(variant="ml_ctc"))
    supervisor.settings.enable_jobs = True
    await supervisor.deploy(EngineConfig())
    pid = supervisor.process.pid
    response = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"model": openai_model_id("ml_ctc")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "model_switch_jobs_enabled"
    assert supervisor.process.pid == pid
    same = await client_ready.post("/v1/audio/transcriptions", files=AUDIO, data={"model": openai_model_id("rnnt")})
    assert same.status_code == 200


async def test_previous_model_still_serves_after_replacement_download_fails(client_ready, monkeypatch):
    supervisor = client_ready.app.state.supervisor
    generation = supervisor.process.generation
    monkeypatch.setenv("FAKE_DOWNLOAD_FAIL", "disk")
    await supervisor.deploy(EngineConfig(variant="e2e_rnnt"))
    assert supervisor.detail_code == "download.failed"
    assert supervisor.process.generation == generation
    models = (await client_ready.get("/v1/models")).json()["data"]
    assert [model["id"] for model in models] == ["gigaam-v3-rnnt", "kamerton"]
    for model in models:
        transcript = await client_ready.post("/v1/audio/transcriptions", files=AUDIO, data={"model": model["id"]})
        assert transcript.json() == {"text": "привет мир"}
        assert (await engine_upload(client_ready))["variant"] == "rnnt"
    undeployed = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"model": "gigaam-v3-e2e-rnnt"},
    )
    assert undeployed.status_code == 404
    assert undeployed.json()["error"]["code"] == "model_not_available"


@pytest.mark.parametrize("model_fields", [[("model", (None, ""))], [
    ("model", (None, "kamerton")), ("model", (None, "whisper-1")),
]])
async def test_invalid_model_field_rejected(client_ready, model_fields):
    response = await client_ready.post(
        "/v1/audio/transcriptions", files=[*AUDIO.items(), *model_fields],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_model"
    assert response.json()["error"]["param"] == "model"


async def test_translations_rejected_with_explanation(client_ready):
    response = await client_ready.post("/v1/audio/translations", files=AUDIO)
    assert response.status_code == 400
    assert "не переводит" in response.json()["error"]["message"]
    assert response.json()["error"]["code"] == "translations_not_supported"


async def test_503_with_retry_after_when_engine_not_ready(client_stopped):
    response = await client_stopped.post("/v1/audio/transcriptions", files=AUDIO)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json()["error"]["code"] == "engine_not_ready"
    assert "Разверните" in response.json()["error"]["message"]


async def test_engine_diagnostics_stay_out_of_client_error(client_stopped):
    supervisor = client_stopped.app.state.supervisor
    supervisor._set_status("error", "unpublished /internal/model/file")
    response = await client_stopped.post("/v1/audio/transcriptions", files=AUDIO, data={"model": "kamerton"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "engine_not_ready"
    assert "/internal/model/file" not in response.text


async def test_missing_file_rejected(client_ready):
    response = await client_ready.post("/v1/audio/transcriptions", data={"model": "whisper-1"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_file"


async def test_upload_larger_than_limit_rejected(client_ready):
    client_ready.app.state.settings.max_upload_mb = 1
    big = b"0" * (2 * 1024 * 1024)
    response = await client_ready.post(
        "/v1/audio/transcriptions", files={"file": ("a.wav", big, "audio/wav")}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert "МБ" in response.json()["error"]["message"]


async def test_metrics_recorded_with_rtf_for_wav(client_ready):
    await client_ready.post("/v1/audio/transcriptions", files=AUDIO)
    snapshot = client_ready.app.state.metrics.snapshot()
    assert snapshot["count"] == 1
    assert snapshot["avg_rtf"] is not None  # 2 s WAV => duration known


@pytest.mark.parametrize("path", ["/v1/audio/transcriptions", "/api/test", "/v1/transcribe"])
async def test_upload_limit_while_receiving_chunked_body(client_ready, path):
    client_ready.app.state.settings.max_upload_mb = 1

    async def chunks():
        yield b'--test\r\nContent-Disposition: form-data; name="file"; filename="sample.wav"\r\n\r\n'
        for _ in range(5):
            yield b"0" * (512 * 1024)
        pytest.fail("Получатель продолжил читать тело после отказа по размеру")

    response = await client_ready.post(path, content=chunks(), headers={
        "Content-Type": "multipart/form-data; boundary=test",
    })
    assert response.status_code == 413 and response.json()["error"]["code"] == "file_too_large"


async def test_local_engine_traffic_ignores_environment_proxy(client_ready, monkeypatch):
    # Заведомо несуществующая схема не открывает соединений даже при регрессии.
    monkeypatch.setenv("HTTP_PROXY", "invalid-scheme://no-proxy.invalid")
    monkeypatch.setenv("http_proxy", "invalid-scheme://no-proxy.invalid")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    process = client_ready.app.state.supervisor.process
    assert await process.health() and await process.reload()
    for path in ("/api/test", "/v1/audio/transcriptions", "/v1/transcribe", "/v1/admin/reload"):
        assert (await client_ready.post(path, files=AUDIO)).status_code == 200


async def test_native_query_excludes_console_key_and_preserves_lists(client_ready_with_key):
    client = client_ready_with_key
    response = await client.post(
        "/v1/admin/reload", headers={"Authorization": "Bearer secret"},
        params=[("api_key", "discard-me"), ("option", "one"), ("option", "two")],
    )
    assert response.status_code == 200
    logs = client.app.state.bus.log_lines()
    assert any("/v1/admin/reload?option=one&option=two" in line for line in logs)
    assert all("api_key=" not in line for line in logs)


async def test_native_engine_endpoint_passthrough(client_ready):
    response = await client_ready.post("/v1/transcribe", files=AUDIO)
    assert response.status_code == 200
    assert response.json()["text"] == "привет мир"


async def engine_upload(client) -> dict:
    """What the engine actually received in the last transcription request."""
    import httpx

    base = client.app.state.settings.engine_base_url
    async with httpx.AsyncClient(timeout=5) as engine:
        response = await engine.get(f"{base}/debug/last_upload")
    return response.json()


async def test_browser_webm_reaches_the_engine_untouched(client_ready):
    """The engine demuxes WebM itself since 2.17.0, so the console must not rewrite it."""
    webm = webm_opus_bytes([opus_code3_packet([b"m" * 30] * 3)] * 4)
    response = await client_ready.post(
        "/v1/audio/transcriptions",
        files={"file": ("dictation.webm", webm, "audio/webm")},
    )
    assert response.status_code == 200
    upload = await engine_upload(client_ready)
    assert upload["magic"] == b"\x1a\x45\xdf\xa3".decode("latin-1")  # the EBML header
    assert upload["filename"] == "dictation.webm"
    assert upload["content_type"] == "audio/webm"
    assert upload["size"] == len(webm)


async def test_webm_gets_an_rtf_the_engine_would_not_have_reported(client_ready):
    """`json` responses carry no duration, so the console reads it off the container."""
    webm = webm_opus_bytes([opus_code3_packet([b"m" * 30] * 3)] * 50)
    await client_ready.post(
        "/v1/audio/transcriptions", files={"file": ("d.webm", webm, "audio/webm")}
    )
    snapshot = client_ready.app.state.metrics.snapshot()
    assert snapshot["avg_rtf"] is not None  # 150 frames x 20 ms => 3 s of audio


async def test_formats_the_engine_supports_reach_it_byte_for_byte(client_ready):
    payload = wav_bytes(seconds=2)
    response = await client_ready.post(
        "/v1/audio/transcriptions", files={"file": ("a.wav", payload, "audio/wav")}
    )
    assert response.status_code == 200
    upload = await engine_upload(client_ready)
    assert upload["magic"] == "RIFF"
    assert upload["filename"] == "a.wav"
    assert upload["size"] == len(payload)


@pytest.mark.parametrize(("path", "fields", "source"), [
    ("/v1/audio/transcriptions", {"source": "microphone"}, "api"),
    ("/api/test", {}, "file"),
    ("/api/test", {"source": "microphone"}, "microphone"),
])
async def test_upload_keeps_safe_original_basename_bytes_and_source(client_ready, path, fields, source):
    name = "Заметка 19.11.webm"
    webm = webm_opus_bytes([opus_code3_packet([b"m" * 30] * 3)] * 5)
    response = await client_ready.post(
        path, data=fields, files={"file": (f"../private/folder/{name}", webm, "audio/webm")},
    )
    assert response.status_code == 200
    upload = await engine_upload(client_ready)
    assert upload["filename"] == name and upload["content_type"] == "audio/webm"
    assert upload["sha256"] == hashlib.sha256(webm).hexdigest()
    if path == "/api/test":
        assert upload["source"] is None
    status = (await client_ready.get("/api/status")).json()
    recent, = status["metrics"]["recent"]
    assert (recent["name"], recent["source"]) == (name, source)
    settings = client_ready.app.state.settings
    assert name not in settings.metrics_path.read_text(encoding="utf-8")
    assert name not in str((await client_ready.get("/api/journal")).json())


async def test_nameless_upload_is_not_reported_as_fictitious_wav(client_ready):
    audio = wav_bytes()
    payload = (
        b'--test\r\nContent-Disposition: form-data; name="file"; filename=""\r\n'
        b'Content-Type: audio/wav\r\n\r\n' + audio + b'\r\n--test--\r\n'
    )
    response = await client_ready.post("/api/test", content=payload, headers={
        "Content-Type": "multipart/form-data; boundary=test",
    })
    assert response.status_code == 200
    assert (await engine_upload(client_ready))["sha256"] == hashlib.sha256(audio).hexdigest()
    assert client_ready.app.state.metrics.snapshot()["recent"][0]["name"] == "без имени"


@pytest.mark.parametrize("path", ["/v1/audio/transcriptions", "/api/test"])
@pytest.mark.parametrize("aliases", [
    ("timestamp_granularities[]", "timestamp_granularities[]"),
    ("timestamp_granularities", "timestamp_granularities"),
    ("timestamp_granularities", "timestamp_granularities[]", "timestamp_granularities"),
])
async def test_timestamp_granularities_reach_engine_in_order(client_ready, path, aliases):
    timestamps = list(zip(aliases, ("word", "segment", "word")))
    response = await client_ready.post(path, files=[
        ("file", AUDIO["file"]),
        ("response_format", (None, "verbose_json")),
        *((name, (None, value)) for name, value in timestamps),
    ])
    assert response.status_code == 200
    assert (await engine_upload(client_ready))["timestamps"] == [list(pair) for pair in timestamps]


# --------------------------------------------- словарь клиента, который не дошел
#
# Клиенты диктовки из мира Whisper кладут пользовательский словарь в `prompt` и
# на самохостный адрес шлют его вслепую. Движок - трансдьюсер, `prompt` он
# принимает и не читает, а 200 без единого признака этого означало бы, что
# словарь клиента молча не работает. Заголовок - единственный канал до чужого
# приложения, поэтому он проверяется как часть контракта.


async def test_prompt_is_answered_with_a_header_saying_it_was_ignored(client_ready):
    response = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"prompt": "АйМоп, GigaAM"}
    )
    assert response.status_code == 200
    assert response.headers["x-ignored-fields"] == "prompt"
    assert response.headers["x-glossary-source"] == "server-hotwords"


async def test_request_without_a_prompt_carries_no_such_headers(client_ready):
    response = await client_ready.post("/v1/audio/transcriptions", files=AUDIO)
    assert response.status_code == 200
    assert "x-ignored-fields" not in response.headers


async def test_blank_prompt_is_not_worth_a_warning(client_ready):
    response = await client_ready.post(
        "/v1/audio/transcriptions", files=AUDIO, data={"prompt": "   "}
    )
    assert "x-ignored-fields" not in response.headers


async def test_ignored_prompt_is_logged_once_not_on_every_request(client_ready):
    for _ in range(3):
        await client_ready.post(
            "/v1/audio/transcriptions", files=AUDIO, data={"prompt": "АйМоп"}
        )
    bus = client_ready.app.state.bus
    warnings = [line for line in bus.log_lines(limit=200) if "client sent prompt" in line]
    assert len(warnings) == 1
