import asyncio
import re
from pathlib import Path

import pytest

from conftest import wait_for, wav_bytes
from console.state import EngineConfig


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
async def test_dictation_stages_and_local_paged_history(live_client, engine):
    pw = pytest.importorskip("playwright.async_api")
    await live_client.app.state.supervisor.deploy(EngineConfig())
    bus = live_client.app.state.bus

    async with pw.async_playwright() as driver:
        launcher = getattr(driver, engine)
        if engine == "webkit" and not Path(launcher.executable_path).is_file():
            pytest.skip("Для проверки истории нужен Playwright WebKit")
        browser = await launcher.launch(**({"channel": "chrome"} if engine == "chromium" else {}))
        try:
            page = await browser.new_page(**(driver.devices["iPhone 15"] if engine == "webkit" else {
                "viewport": {"width": 1366, "height": 768},
            }))
            await page.goto(str(live_client.base_url) + "/#dict")
            await wait_for(lambda: bus.subscriber_count > 0)
            await page.locator("#file-mode").click()
            progress, history = page.locator("#audio-progress"), page.locator("#history-entries")
            started = asyncio.Event()
            finish = asyncio.Event()
            progress_id = ""
            sent = 0

            async def transcribe(route):
                nonlocal sent, progress_id
                sent += 1
                payload = {"text": f"Transcript number {sent}", "elapsed": 0.13, "audio_seconds": 1}
                if sent == 6:
                    match = re.search(rb'name="progress_id"\r\n\r\n([0-9a-f-]{36})', route.request.post_data_buffer)
                    assert match, "The browser did not attach an event correlation ID"
                    progress_id = match.group(1).decode()
                    started.set()
                    await finish.wait()
                    payload.update(cached=True, segments=[{"start": 1.5, "speaker": "speaker_1", "text": "<b>Example</b>"}])
                await route.fulfill(json=payload)

            await page.route("**/api/test", transcribe)
            for number in range(1, 7):
                await page.locator("#file-input").set_input_files({
                    "name": f"clip-{number}.wav", "mimeType": "audio/wav", "buffer": wav_bytes(),
                })
                await page.locator("#btn-send").click()
                if number < 6:
                    await pw.expect(page.locator("#result-text")).to_have_text(f"Transcript number {number}")

            await asyncio.wait_for(started.wait(), timeout=3)
            await pw.expect(progress).to_contain_text("Sending audio")
            bus.publish({"type": "transcription", "id": "another-request", "stage": "cache_hit"})
            bus.publish({"type": "transcription", "id": progress_id, "stage": "queued"})
            await pw.expect(progress).to_have_text("Waiting for the model…")
            bus.publish({"type": "transcription", "id": progress_id, "stage": "recognizing_speakers"})
            await pw.expect(progress).to_contain_text("identifying speakers")
            finish.set()
            await pw.expect(progress).to_have_text("Result from cache.")
            await pw.expect(page.locator("#latency-work-label")).to_have_text("server response")
            await pw.expect(page.locator("#result-text .transcript-speaker")).to_have_text("0:01 · Speaker 1")
            await page.evaluate("""Object.defineProperty(navigator, 'clipboard', {
                value: {writeText: async text => { window.copiedTranscript = text; }}
            })""")
            await page.locator('[data-target="result-text"]').click()
            copied = await page.evaluate("window.copiedTranscript")
            assert "0:01 · Speaker 1" in copied and "<b>Example</b>" in copied

            await pw.expect(history.locator("details")).to_have_count(5)
            await pw.expect(history.locator("details[open]")).to_have_count(0)
            first = history.locator("details").first
            await pw.expect(first.locator("summary")).to_contain_text("clip-6.wav")
            await first.locator("summary").press("Enter")
            await pw.expect(first.locator(".transcript p")).to_have_text("<b>Example</b>")
            await pw.expect(first.locator(".transcript b")).to_have_count(0)
            await page.locator("#history-next").click()
            await pw.expect(page.locator("#history-page")).to_have_text("2 of 2")
            await pw.expect(history.locator("details")).to_have_count(1)
            await pw.expect(history.locator("summary")).to_contain_text("clip-1.wav")

            await page.reload()
            await pw.expect(history.locator("details")).to_have_count(5)
            await pw.expect(history.locator("summary").first).to_contain_text("clip-6.wav")
            await page.evaluate("""() => {
                const key = 'kamerton_dictation_history';
                const entries = JSON.parse(localStorage.getItem(key));
                entries[0].at = Date.now() - 8 * 86_400_000;
                localStorage.setItem(key, JSON.stringify(entries));
            }""")
            await page.evaluate("location.hash = '#settings'")
            retention = page.locator("#history-retention")
            await retention.select_option("7")
            await page.evaluate("location.hash = '#dict'")
            await pw.expect(history.locator("summary").first).to_contain_text("clip-5.wav")
            await pw.expect(page.locator("#history-pages")).to_be_hidden()
            await page.evaluate("location.hash = '#settings'")
            await retention.select_option("off")
            await page.evaluate("location.hash = '#dict'")
            await pw.expect(history.locator("details")).to_have_count(0)
            assert await page.evaluate("localStorage.getItem('kamerton_dictation_history')") is None
            await pw.expect(page.locator("#history-empty")).to_contain_text("history is off")
            width = await page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            assert width[0] <= width[1], width
        finally:
            await browser.close()
