import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from conftest import wav_bytes
from console.api import DeployRequest
from console.engine import build_argv
from console.parakeet_worker import Parakeet, TOne, create_worker
from console.state import EngineConfig, StateFile


def test_alternate_arguments_follow_the_model_profile(console_settings, monkeypatch):
    monkeypatch.setattr("console.engine.runtime_available", lambda *_: True)
    console_settings.alternate_threads = 3
    whisper = EngineConfig(variant="whisper_tiny", alternate_threads=2, whisper_beam_size=7)
    args = build_argv(console_settings, whisper, alternate_port=8201)
    assert args[args.index("--threads") + 1] == "2"
    assert args[args.index("--beam-size") + 1] == "7"
    assert args[args.index("--port") + 1] == "8201"
    reset = DeployRequest(variant="whisper_tiny", alternate_threads=None).to_config(whisper)
    args = build_argv(console_settings, reset)
    assert args[args.index("--threads") + 1] == "3"
    assert args[args.index("--beam-size") + 1] == "7"

    parakeet = DeployRequest(variant="parakeet_ultra", parakeet_max_segment=15).to_config(EngineConfig())
    assert build_argv(console_settings, parakeet)[-3:] == ["auto", "15", "auto"]
    nemotron = DeployRequest(variant="nemotron_35_asr", nemotron_language="ru").to_config(EngineConfig())
    assert build_argv(console_settings, nemotron)[-3:] == ["auto", "30", "ru"]
    tone = DeployRequest(variant="t_one", alternate_threads=2, punctuation="off").to_config(EngineConfig())
    args = build_argv(console_settings, tone)
    assert args[4] == "2" and args[-3:] == ["off", "30", "auto"]


def test_parakeet_vad_segment_length_reaches_the_inference_call(monkeypatch, tmp_path):
    calls = []

    def function(name):
        def invoke(*args):
            if name == "parakeet_capi_transcribe_path_json_vad_with":
                calls.append(json.loads(args[4]))
                return {"text": "synthetic"}
            return 1
        return invoke

    class Library:
        def __getattr__(self, name):
            return function(name)

    monkeypatch.setattr("console.parakeet_worker.c.CDLL", lambda _: Library())
    monkeypatch.setattr(Parakeet, "_load", lambda *_: 1)
    monkeypatch.setattr(Parakeet, "_json", lambda _, result: result)
    worker = Parakeet("stub", tmp_path, "parakeet_ultra", max_segment=15)
    assert worker.recognize(tmp_path / "audio.wav", "auto") == {"text": "synthetic"}
    assert calls == [{"max_segment": 15}]


async def test_worker_uses_nemotron_language_unless_request_overrides_it(console_settings, monkeypatch):
    languages = []
    engine = SimpleNamespace(default_language="ru", recognize=lambda _, lang: languages.append(lang) or {"text": "speech"})
    monkeypatch.setattr("console.parakeet_worker.decode_audio", lambda *_: 1.0)
    app = create_worker(engine, console_settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://worker") as client:
        for fields in ({}, {"language": "en"}, {"language": "auto"}):
            response = await client.post("/v1/audio/transcriptions", data=fields, files={"file": ("sample.wav", wav_bytes())})
            assert response.json() == {"text": "speech"}
    assert languages == ["ru", "en", "auto"]


@pytest.mark.parametrize("enabled,expected", [(True, "Привет."), (False, "привет")])
def test_tone_can_bypass_punctuation_and_case(tmp_path, enabled, expected):
    worker = object.__new__(TOne)
    stream = SimpleNamespace(accept_waveform=lambda *_: None, input_finished=lambda: None)
    result = SimpleNamespace(text="привет", tokens=["привет"], timestamps=[0.0])
    worker.recognizer = SimpleNamespace(create_stream=lambda: stream, is_ready=lambda _: False, get_result_all=lambda _: result)
    worker.numpy = SimpleNamespace(zeros=lambda *_, **__: None)
    worker.punctuation = object() if enabled else None
    worker._format = lambda words: [word.capitalize() + "." for word in words]
    audio = tmp_path / "sample.wav"
    audio.write_bytes(wav_bytes(0.0))
    recognized = worker.recognize(audio, "ru")
    assert recognized["text"] == recognized["words"][0]["word"] == expected


async def test_variant_profiles_survive_api_switch_and_roundtrip(client_stopped):
    supervisor = client_stopped.app.state.supervisor
    first = EngineConfig(variant="rnnt", punctuation="off", pool_size=2)
    second = EngineConfig(variant="e2e_rnnt", itn="off")
    await supervisor.deploy(first)
    await supervisor.deploy(second)
    assert supervisor.default_config() == second
    async with supervisor.inference_access("rnnt"):
        assert supervisor.current == first
    stored = StateFile(supervisor.settings.state_path).load()
    assert stored.model_configs == {"rnnt": first, "e2e_rnnt": second}
    assert stored.desired == second
    status = (await client_stopped.get("/api/status")).json()
    assert status["model_configs"]["rnnt"] == first.to_dict()


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
async def test_model_dialog_and_retention_are_separate_in_browser(engine, live_client, monkeypatch):
    pw = pytest.importorskip("playwright.async_api")
    monkeypatch.setattr("console.api.runtime_available", lambda *_: True)
    async with pw.async_playwright() as driver:
        if engine == "webkit" and not Path(driver.webkit.executable_path).is_file():
            pytest.skip("Для мобильной проверки нужен Playwright WebKit")
        browser = await driver.webkit.launch() if engine == "webkit" else await driver.chromium.launch(channel="chrome")
        try:
            page = await browser.new_page(**(driver.devices["iPhone 15"] if engine == "webkit" else {}))
            await page.goto(str(live_client.base_url) + "/#settings")
            retention = page.get_by_label("Keep transcripts for")
            await pw.expect(retention).to_have_value("30")
            await retention.select_option("90")
            await page.reload()
            await pw.expect(retention).to_have_value("90")
            await pw.expect(page.locator("#model-dialog")).to_be_hidden()

            navigation = page.locator("#mobile-nav")
            if await navigation.is_visible():
                await navigation.select_option("models")
            else:
                await page.locator("#railnav a[href='#models']").click()
            await page.locator("#models-whisper summary").click()
            await page.locator("#target-whisper_tiny").check()
            button = page.get_by_role("button", name="Configure startup")
            await button.click()
            dialog = page.get_by_role("dialog", name="Configure startup")
            await pw.expect(dialog.get_by_text("Whisper Tiny")).to_be_visible()
            assert await dialog.evaluate("""dialog => {
                const bounds = dialog.getBoundingClientRect();
                return Math.abs(bounds.left - (document.documentElement.clientWidth - bounds.right)) < 18;
            }""")
            await pw.expect(dialog.get_by_label("Beam size")).to_have_value("5")
            await dialog.get_by_label("Beam size").fill("7")
            await dialog.get_by_role("button", name="Close").click()
            await page.locator("#target-t_one").check()
            await button.click()
            await pw.expect(dialog.get_by_text("T-one Russian")).to_be_visible()
            await pw.expect(dialog.get_by_role("combobox", name="Additional punctuation", exact=True)).to_be_visible()
            await pw.expect(page.locator("#opt-whisper-beam")).to_be_hidden()
            await dialog.get_by_role("button", name="Close").click()
            await page.locator("#target-whisper_tiny").check()
            await button.click()
            await pw.expect(dialog.get_by_label("Beam size")).to_have_value("7")
            if engine == "chromium":
                await page.keyboard.press("Escape")
                await pw.expect(dialog).to_be_hidden()
                await pw.expect(button).to_be_focused()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            await browser.close()
