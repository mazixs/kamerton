import asyncio
import struct
from uuid import uuid4

from conftest import wav_bytes

from console import transcription_cache
from console.transcription_cache import CachedResponse, TranscriptionCache, transcription_key


def with_wav_metadata(wav: bytes) -> bytes:
    updated = wav[:12] + b"JUNK" + struct.pack("<I", 4) + b"info" + wav[12:]
    return updated[:4] + struct.pack("<I", len(updated) - 8) + updated[8:]


def test_pcm_fingerprint_uses_samples_options_and_scope():
    def key(audio, *, scope="first", language="ru", glossary="", rate="normal"):
        return transcription_key(audio, "x.wav", "audio/wav", scope=scope, config={"option": rate},
                                 fields=[("language", language)], glossary=glossary)

    audio = wav_bytes()
    assert key(audio) == key(with_wav_metadata(audio))
    assert key(audio) != key(wav_bytes(seconds=2))
    assert key(audio) != key(wav_bytes(sample_rate=8000))
    assert key(audio) != key(audio, scope="second")
    assert key(audio) != key(audio, glossary="new")
    assert key(audio) != key(audio, language="en")
    assert key(audio) != key(audio, rate="custom")


async def test_cache_has_fixed_expiry_and_byte_budget(monkeypatch):
    monkeypatch.setattr(transcription_cache, "TTL_SECONDS", 0.02)
    monkeypatch.setattr(transcription_cache, "MAX_BYTES", 4)
    cache = TranscriptionCache()
    cache.put(b"1", CachedResponse(b"abc"))
    cache.put(b"2", CachedResponse(b"def"))
    assert cache.get(b"1") is None
    assert cache.get(b"2") is not None
    assert cache.status()["bytes"] == 3
    await asyncio.sleep(0.05)
    assert not cache._entries
    assert cache.status()["bytes"] == 0
    cache.close()


async def test_dictation_serves_repeat_without_recording_new_inference(client_ready):
    audio = wav_bytes()
    files = {"file": ("one.wav", audio, "audio/wav")}
    first = await client_ready.post("/api/test", files=files)
    bus = client_ready.app.state.bus
    subscription = bus.subscribe()
    progress_id = str(uuid4())
    try:
        repeated = await client_ready.post("/api/test", data={"progress_id": progress_id},
                                           files={"file": ("duplicate.wav", with_wav_metadata(audio), "audio/wav")})
        assert first.status_code == repeated.status_code == 200
        assert first.json()["cached"] is False and repeated.json()["cached"] is True
        assert repeated.json()["text"] == first.json()["text"]
        assert repeated.json()["audio_seconds"] == first.json()["audio_seconds"]
        assert repeated.json()["rtf"] is None
        assert repeated.headers["Cache-Control"] == "no-store"
        events = [await asyncio.wait_for(anext(subscription), 1) for _ in range(2)]
        assert [(event["id"], event["stage"]) for event in events] == [(progress_id, "queued"), (progress_id, "cache_hit")]
        metrics = client_ready.app.state.metrics.snapshot()
        assert metrics["count"] == 1 and metrics["recent"][0]["name"] == "one.wav"
    finally:
        await subscription.aclose()
        client_ready.app.state.transcription_cache.close()


async def test_simultaneous_api_repeats_reuse_complete_response(client_ready):
    async def request(name, response_format="json"):
        return await client_ready.post("/v1/audio/transcriptions", data={"response_format": response_format},
                                      files={"file": (name, wav_bytes(), "audio/wav")})

    try:
        first, repeat = await asyncio.gather(request("one.wav"), request("two.wav"))
        assert first.status_code == repeat.status_code == 200
        assert first.content == repeat.content
        assert {first.headers["X-Kamerton-Cache"], repeat.headers["X-Kamerton-Cache"]} == {"MISS", "HIT"}
        assert (await request("three.wav", "text")).headers["X-Kamerton-Cache"] == "MISS"
        assert client_ready.app.state.metrics.snapshot()["count"] == 2
    finally:
        client_ready.app.state.transcription_cache.close()


async def test_benchmark_requests_skip_reading_and_writing_cache(client_ready):
    cache = client_ready.app.state.transcription_cache
    files = {"file": ("fixture.wav", wav_bytes(), "audio/wav")}
    try:
        for _ in range(2):
            result = await client_ready.post("/api/test?use_cache=false", files=files)
            assert result.status_code == 200 and result.json()["cached"] is False
        assert cache.status()["entries"] == 0
        first = await client_ready.post("/api/test", files=files)
        assert first.status_code == 200 and first.json()["cached"] is False
        bypass = await client_ready.post("/api/test?use_cache=false", files=files)
        assert bypass.status_code == 200 and bypass.json()["cached"] is False
        repeat = await client_ready.post("/api/test", files=files)
        assert repeat.status_code == 200 and repeat.json()["cached"] is True
        assert client_ready.app.state.metrics.snapshot()["count"] == 4
        assert cache.status()["hits"] == 1
    finally:
        cache.close()


async def test_cached_explicit_model_does_not_switch_current_engine(client_ready):
    supervisor = client_ready.app.state.supervisor
    from console.state import EngineConfig

    data = {"model": "gigaam-v3-rnnt"}
    files = {"file": ("same.wav", wav_bytes(), "audio/wav")}
    try:
        first = await client_ready.post("/v1/audio/transcriptions", data=data, files=files)
        assert first.status_code == 200 and first.headers["X-Kamerton-Cache"] == "MISS"
        await supervisor.deploy(EngineConfig(variant="ml_ctc"))
        generation = supervisor.process.generation
        repeat = await client_ready.post("/v1/audio/transcriptions", data=data, files=files)
        assert repeat.status_code == 200 and repeat.headers["X-Kamerton-Cache"] == "HIT"
        assert supervisor.current.variant == "ml_ctc" and supervisor.process.generation == generation
    finally:
        client_ready.app.state.transcription_cache.close()
