import base64
import os
import re
from pathlib import Path

import pytest

from conftest import wav_bytes


SOURCE = Path(__file__).resolve().parents[1] / "frontend" / "src"


def locale_keys(lang):
    source = (SOURCE / "shared" / "i18n" / f"{lang}.js").read_text(encoding="utf-8")
    return set(re.findall(r'"([\w.]+)":', source))


def test_both_languages_cover_the_same_keys():
    english, russian = locale_keys("en"), locale_keys("ru")
    assert english == russian, english ^ russian
    assert len(english) > 100
    for code in ("weight_off", "weight_ignored", "weight_invalid", "comment", "tab", "short"):
        assert f"issue.{code}" in english


async def test_page_is_revalidated_and_build_assets_are_fingerprinted(client_stopped):
    response = await client_stopped.get("/")
    assert response.status_code == 200 and "no-cache" in response.headers["cache-control"]
    assert 'id="root"' in response.text and '<html lang="en">' in response.text
    assert 'type="module"' in response.text
    assets = set(re.findall(r'/static/assets/[\w-]+-[\w-]{8}\.(?:js|css)', response.text))
    assert {Path(asset).suffix for asset in assets} == {".js", ".css"}
    for asset in assets:
        result = await client_stopped.get(asset)
        assert result.status_code == 200
        assert "immutable" in result.headers["cache-control"]


async def test_microphone_worklet_keeps_its_same_origin_url(client_stopped):
    result = await client_stopped.get("/static/capture-worklet.js")
    assert result.status_code == 200
    assert "javascript" in result.headers["content-type"]
    assert "registerProcessor" in result.text
    assert "no-cache" in result.headers["cache-control"]


async def test_head_descriptions_come_translated_from_the_server(client_stopped):
    english = (await client_stopped.get("/api/models", params={"lang": "en"})).json()
    russian = (await client_stopped.get("/api/models", params={"lang": "ru"})).json()
    unknown = (await client_stopped.get("/api/models", params={"lang": "xx"})).json()
    by_id = {head["id"]: head for head in english["heads"]}
    assert "vocabulary" in by_id["e2e_rnnt"]["subtitle"]
    assert by_id["e2e_rnnt"]["badge"] == "low error on FLEURS ru"
    ru_by_id = {head["id"]: head for head in russian["heads"]}
    assert ru_by_id["e2e_rnnt"]["badge"] == "низкая ошибка на FLEURS ru"
    assert ru_by_id["e2e_rnnt"]["title"] == by_id["e2e_rnnt"]["title"]
    assert unknown["heads"] == english["heads"]


async def test_web_shell_navigation_and_language_persist(chrome_page, live_client):
    page, expect = chrome_page
    await page.goto(str(live_client.base_url))
    await expect(page.get_by_role("heading", name="Dictation", exact=True)).to_be_visible()
    nav = page.locator("#railnav")
    for route in ("dict", "compare", "benchmarks", "api", "models", "settings", "glossary", "status", "journal"):
        await expect(nav.locator(f'a[href="#{route}"]')).to_have_count(1)

    await nav.get_by_role("link", name="WER benchmarks").click()
    await expect(page.get_by_role("heading", name="WER benchmarks", exact=True)).to_be_visible()
    brand = page.get_by_role("complementary").get_by_role("link", name="Kamerton ASR Console")
    await brand.get_by_text("Kamerton", exact=True).click()
    await expect(page.get_by_role("heading", name="Dictation", exact=True)).to_be_visible()
    await page.go_back()
    await expect(page.get_by_role("heading", name="WER benchmarks", exact=True)).to_be_visible()
    await brand.press("Enter")
    await expect(nav.get_by_role("link", name="Dictation")).to_have_attribute("aria-current", "page")

    await page.get_by_role("complementary").get_by_role("radio", name="RU").click()
    await expect(page.get_by_role("heading", name="Диктовка", exact=True)).to_be_visible()
    await page.reload()
    await expect(page.get_by_role("heading", name="Диктовка", exact=True)).to_be_visible()
    await expect(page.locator("html")).to_have_attribute("lang", "ru")


async def test_glossary_explains_active_model_support_with_empty_entries(chrome_page, live_client, monkeypatch):
    from console.state import EngineConfig

    supervisor = live_client.app.state.supervisor
    monkeypatch.setattr(supervisor, "default_config", lambda: EngineConfig(variant="t_one"))
    page, expect = chrome_page
    address = str(live_client.base_url) + "/#glossary"
    await page.goto(address)
    reach = page.locator("#glossary-reach")
    await expect(reach).to_contain_text("does not use the glossary")
    await expect(page.locator("#tag-list > li")).to_have_count(0)
    monkeypatch.setattr(supervisor, "default_config", lambda: EngineConfig(variant="whisper_tiny"))
    await page.reload()
    await expect(reach).to_contain_text("uses the first glossary phrases as a text hint")


async def test_mobile_feedback_and_model_list_in_chrome(live_client):
    """Браузерная регрессия: uv run --with playwright pytest -k mobile_feedback (нужен Chrome)."""
    pw = pytest.importorskip("playwright.async_api")
    from console.state import EngineConfig

    app = live_client.app
    app.state.settings.api_key = "ui-test-only"
    app.state.settings.max_upload_mb = 1
    await app.state.supervisor.deploy(EngineConfig())
    async with pw.async_playwright() as driver:
        browser = await driver.chromium.launch(channel="chrome")
        try:
            page = await browser.new_page(viewport={"width": 390, "height": 844})
            await page.add_init_script("localStorage.setItem('stt_console_key', 'ui-test-only')")
            await page.goto(str(live_client.base_url))
            nav = page.locator("#mobile-nav")
            await page.locator("#file-mode").click()
            await page.locator("#file-input").set_input_files({
                "name": "sample.wav", "mimeType": "audio/wav", "buffer": b"0" * (1024**2 + 1),
            })
            await page.locator("#btn-send").click()
            await pw.expect(page.locator("#result-text")).to_contain_text("upload limit")
            await page.locator(".mobile [data-lang=ru]").click()
            await pw.expect(page.locator("#result-text")).to_contain_text("лимит загрузки")

            await page.set_viewport_size({"width": 320, "height": 844})
            await page.locator("#file-input").set_input_files({
                "name": "sample.wav", "mimeType": "audio/wav", "buffer": wav_bytes(),
            })
            await page.locator("#btn-send").click()
            await pw.expect(page.locator("#result")).to_be_visible()
            assert await page.locator(".latency > div").evaluate_all("""rows => rows.every(row => {
                const range = document.createRange(); range.selectNodeContents(row.firstElementChild);
                return range.getBoundingClientRect().right < row.children[1].getBoundingClientRect().left;
            })""")

            await nav.select_option("glossary")
            assert await page.locator("#btn-add").evaluate("""button => {
                const range = document.createRange(); range.selectNodeContents(button);
                return range.getClientRects().length === 1;
            }""")
            await page.locator("#btn-export").click()
            await page.locator(".mobile [data-lang=en]").click()
            await pw.expect(page.locator("#glossary-hint")).to_have_text("the glossary is empty")
            async with page.expect_request(lambda r: r.url.endswith("/v1/models")) as req:
                await nav.select_option("api")
            assert await (await req.value).header_value("authorization") == "Bearer ui-test-only"
            await page.locator("#service-models summary").click()
            await pw.expect(page.locator("#model-response")).to_contain_text('"data"')
        finally:
            await browser.close()


async def test_mobile_navigation_has_visible_text_in_webkit(live_client):
    pw = pytest.importorskip("playwright.async_api")
    async with pw.async_playwright() as driver:
        if not Path(driver.webkit.executable_path).is_file():
            pytest.skip("Для проверки мобильной навигации нужен Playwright WebKit")
        browser = await driver.webkit.launch()
        try:
            page = await browser.new_page(**driver.devices["iPhone 15"])
            await page.goto(str(live_client.base_url))
            nav = page.locator("#mobile-nav")
            await pw.expect(nav.locator("option").first).to_have_text("Dictation")
            screenshot = await nav.screenshot(scale="css")
            contrast = await nav.evaluate("""async (select, encoded) => {
                const img = new Image();
                img.src = 'data:image/png;base64,' + encoded;
                await img.decode();
                const canvas = document.createElement('canvas');
                canvas.width = img.width;
                canvas.height = img.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                const background = ctx.getImageData(Math.floor(img.width / 2), 10, 1, 1).data;
                ctx.fillStyle = getComputedStyle(select).color;
                ctx.fillRect(0, 0, 1, 1);
                const foreground = ctx.getImageData(0, 0, 1, 1).data;
                function luminance([r, g, b]) {
                    const linear = value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
                    return 0.2126 * linear(r / 255) + 0.7152 * linear(g / 255) + 0.0722 * linear(b / 255);
                }
                const colors = [luminance(background), luminance(foreground)];
                return (Math.max(...colors) + 0.05) / (Math.min(...colors) + 0.05);
            }""", base64.b64encode(screenshot).decode("ascii"))
            assert contrast >= 4.5
            await nav.select_option("status")
            await pw.expect(page.locator("#storage-title")).to_be_visible()
            await pw.expect(page.locator("#disk-free")).to_contain_text(" of ")
            assert (await page.locator("#disk-free").text_content()).count("\u00a0") == 2
            brand = page.locator(".mobile").get_by_role("link", name="Kamerton ASR Console")
            await brand.locator("svg").tap()
            await pw.expect(page.get_by_role("heading", name="Dictation", exact=True)).to_be_visible()
            await pw.expect(nav).to_have_value("dict")
        finally:
            await browser.close()


@pytest.fixture
async def chrome_page(live_client):
    pw = pytest.importorskip("playwright.async_api")
    async with pw.async_playwright() as driver:
        browser = await driver.chromium.launch(channel="chrome", args=[
            "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        ])
        try:
            yield await browser.new_page(), pw.expect
        finally:
            await browser.close()


async def test_model_catalog_groups_keep_one_choice_and_open_its_settings(chrome_page, live_client, monkeypatch):
    monkeypatch.setattr("console.api.runtime_available", lambda *_: True)
    page, expect = chrome_page
    await page.goto(str(live_client.base_url) + "/#models")
    whisper = page.locator("#models-whisper summary")
    nvidia = page.locator("#models-parakeet summary")
    await expect(page.locator("#target-whisper_tiny")).to_be_hidden()
    await whisper.focus()
    await whisper.press("Enter")
    await nvidia.click()
    for family, variants in {
        "GigaAM": [
            "rnnt", "e2e_rnnt", "e2e_rnnt_2026_10_09", "ml_ctc", "ml_ctc_large",
            "gigaam_v4_rnnt", "gigaam_v4_ctc", "gigaam_multilingual_v2_rnnt",
        ],
        "Whisper": ["whisper_tiny", "whisper_small", "whisper_large_v3_turbo", "whisper_large_v3"],
        "NVIDIA": ["parakeet_tdt_v3", "parakeet_ultra", "nemotron_35_asr"],
        "Other": ["t_one"],
    }.items():
        radios = page.get_by_role("group", name=family, exact=True).get_by_role("radio")
        await expect(radios).to_have_count(len(variants))
        assert await radios.evaluate_all("radios => radios.map(radio => radio.value)") == variants
    other = page.locator("#models-other summary")
    await other.click()
    await expect(page.locator("#target-t_one")).to_be_hidden()
    await expect(page.locator("#target-parakeet_tdt_v3")).to_be_visible()
    await page.locator('.lang-option[data-lang="ru"]:visible').click()
    await expect(page.get_by_role("group", name="Другие", exact=True)).to_be_visible()
    await expect(page.locator("#target-t_one")).to_be_hidden()
    await other.press("Enter")
    await expect(page.locator("#target-t_one")).to_be_visible()
    await page.locator('.lang-option[data-lang="en"]:visible').click()
    await whisper.press("Space")
    await expect(page.locator("#target-whisper_tiny")).to_be_hidden()
    await expect(page.locator("#target-parakeet_tdt_v3")).to_be_visible()
    status = (await live_client.get("/api/status")).json()
    async with page.expect_response(lambda response: "/api/models?lang=en" in response.url) as response:
        live_client.app.state.bus.publish({"type": "snapshot", **status})
    await (await response.value).finished()
    await expect(whisper).to_be_focused()
    await expect(page.locator("#target-whisper_tiny")).to_be_hidden()
    await whisper.press("Enter")
    await page.locator("#target-ml_ctc_large").check()
    await page.locator("#target-ml_ctc_large").press("ArrowDown")
    await expect(page.locator("#target-gigaam_v4_rnnt")).to_be_checked()
    await expect(page.locator('#heads input:checked')).to_have_count(1)
    await page.locator("#model-settings").click()
    await expect(page.locator("#cfg-model")).to_have_text("GigaAM v4 RNN-T")
    await expect(page.locator("#opt-alternate-threads")).to_be_visible()
    await expect(page.locator("#opt-whisper-beam")).to_have_count(0)
    await page.locator("#model-dialog-close").click()
    await page.locator("#target-gigaam_v4_ctc").check()
    await page.locator("#model-settings").click()
    await expect(page.locator("#cfg-model")).to_have_text("GigaAM v4 CTC")
    await expect(page.locator("#opt-alternate-threads")).to_be_visible()
    await page.locator("#model-dialog-close").click()
    await page.locator("#target-gigaam_multilingual_v2_rnnt").check()
    await expect(page.locator("#head-languages")).to_contain_text("Kazakh")
    await expect(page.locator("#target-gigaam_multilingual_v2_rnnt-modellang")).to_have_text("21 languages")
    await page.locator("#target-whisper_tiny").check()
    await page.locator("#model-settings").click()
    await expect(page.locator("#cfg-model")).to_have_text("Whisper Tiny")


async def test_api_catalog_deploys_missing_model_and_enables_its_id(chrome_page, live_client, monkeypatch):
    from console.state import EngineConfig

    await live_client.app.state.supervisor.deploy(EngineConfig())
    page, expect = chrome_page
    await page.goto(str(live_client.base_url) + "/#api")
    picker = page.locator("#client-model-picker")
    summary = picker.locator("summary")
    model_id = "gigaam-multilingual-ctc"
    row = picker.locator(f'[data-model-id="{model_id}"]')
    choose = row.locator(".api-model-select")
    button = row.get_by_role("button", name=f"Deploy {model_id}")
    await expect(page.locator("#client-model")).to_have_text("gigaam-v3-rnnt")
    await summary.press("Enter")
    await expect(row).to_contain_text("not downloaded")
    await expect(choose).to_be_hidden()
    await expect(button).to_be_enabled()
    listed = (await live_client.get("/v1/models")).json()["data"]
    assert model_id not in {entry["id"] for entry in listed}
    catalog = (await live_client.get("/api/models")).json()["heads"]
    assert set(await picker.locator("li").evaluate_all("rows => rows.map(row => row.dataset.modelId)")) == {
        head["api_id"] for head in catalog
    } | {"kamerton"}

    await button.press("Escape")
    await expect(picker.locator("ul")).to_be_hidden()
    await expect(summary).to_be_focused()
    await summary.click()
    await page.route("**/api/deploy", lambda route: route.fulfill(status=503), times=1)
    await button.click()
    await expect(row.get_by_role("status")).to_contain_text("503")
    monkeypatch.setenv("FAKE_DOWNLOAD_SLOW", "0.8")
    async with page.expect_request(lambda request: request.method == "POST" and request.url.endswith("/api/deploy")) as posted:
        await button.click()
    assert (await posted.value).post_data_json == {"variant": "ml_ctc"}
    await expect(button).to_be_disabled()
    await expect(choose).to_be_visible(timeout=15000)
    await expect(button).to_be_hidden()
    await choose.press("Enter")
    await expect(picker.locator("ul")).to_be_hidden()
    await expect(summary).to_be_focused()
    await expect(page.locator("#snip-curl")).to_contain_text(f"model={model_id}")


async def test_catalog_failure_stays_visible_during_status_refresh(chrome_page, live_client):
    page, expect = chrome_page
    await page.goto(str(live_client.base_url) + "/#models")
    await expect(page.locator("#target-rnnt")).to_be_visible()
    await page.route("**/api/models?*", lambda route: route.fulfill(status=503))
    await page.locator('#railnav a[href="#dict"]').click()
    await page.locator('#railnav a[href="#models"]').click()
    await expect(page.locator("#catalog-message")).to_contain_text("may be out of date")
    await expect(page.locator("#catalog-message")).to_contain_text("HTTP 503")
    await expect(page.locator("#target-rnnt")).to_be_visible()
    async with page.expect_response(lambda response: response.url.endswith("/api/status")) as response:
        live_client.app.state.bus.publish({"type": "status"})
    await (await response.value).finished()
    await expect(page.locator("#catalog-message")).to_contain_text("may be out of date")
    await page.unroute("**/api/models?*")
    await page.locator("#catalog-retry").click()
    await expect(page.locator("#catalog-notice")).to_be_hidden()


async def test_catalog_shows_safe_deploy_rejection_and_upstream_status(chrome_page, live_client, monkeypatch):
    from console.downloader import DownloadError
    from console.state import EngineConfig

    monkeypatch.setattr("console.api.runtime_available", lambda *_: True)
    supervisor = live_client.app.state.supervisor
    await supervisor.deploy(EngineConfig())
    page, expect = chrome_page
    await page.goto(str(live_client.base_url) + "/#models")
    await page.locator("#models-whisper summary").click()
    await page.locator("#target-whisper_tiny").check()
    await page.locator("#model-settings").click()
    await page.route("**/api/deploy", lambda route: route.fulfill(status=409, json={
        "error": {"code": "runtime_unavailable", "message": "Private diagnostic"},
    }), times=1)
    await page.locator("#btn-deploy").click()
    message = "The selected engine is unavailable in this installation."
    await expect(page.locator("#deploy-feedback")).to_have_text(message)
    await page.locator('#model-dialog-close').click()
    error = page.locator("#target-whisper_tiny-modelerror")
    await expect(error).to_have_text(message)
    await page.locator("#models-whisper summary").click()
    await expect(error).to_be_hidden()

    async def limited(*args):
        raise DownloadError("http", "Private diagnostic", 69, 429)

    monkeypatch.setattr("console.supervisor.download", limited)
    monkeypatch.setattr("console.supervisor.DOWNLOAD_RETRY_DELAYS", ())
    await page.locator("#model-settings").click()
    await page.locator("#btn-deploy").click()
    await page.locator('#model-dialog-close').click()
    await expect(error).to_have_text("The weights server is limiting requests (HTTP 429). Try again later.")
    await expect(error).to_be_visible()
    await expect(page.locator("#target-rnnt-modelstate")).to_have_text("active · downloaded")


async def test_stop_after_failed_deploy_and_retry_in_chrome(chrome_page, live_client, monkeypatch):
    from console.state import EngineConfig

    page, expect = chrome_page
    supervisor = live_client.app.state.supervisor
    await supervisor.deploy(EngineConfig())
    await page.goto(str(live_client.base_url) + "/#models")
    monkeypatch.setenv("FAKE_DOWNLOAD_SLOW", "0.6")
    monkeypatch.setenv("FAKE_DOWNLOAD_FAIL", "disk")
    await page.locator("#target-ml_ctc").check()
    await page.locator('#model-settings').click()
    await page.locator("#btn-deploy").click()
    await page.locator('#model-dialog-close').click()
    await page.locator('#railnav a[href="#status"]').click()
    await expect(page.locator("#state-pill")).to_have_attribute("data-state", "downloading")
    stop = page.locator("#btn-stop")
    await expect(stop).to_be_hidden()
    await expect(page.locator("#state-pill")).to_have_attribute("data-state", "error")
    await expect(stop).to_be_visible()
    await expect(stop).to_be_enabled()
    await page.locator('#railnav a[href="#models"]').click()
    await expect(page.locator("#target-ml_ctc-modelerror")).to_contain_text("write the model to disk")
    await expect(page.locator("#target-rnnt-modelstate")).to_have_text("active · downloaded")
    await expect(page.locator("#target-rnnt-modelerror")).to_be_empty()
    await page.locator("#target-e2e_rnnt").check()
    await expect(page.locator("#target-ml_ctc-modelerror")).to_be_visible()
    await expect(page.locator("#target-e2e_rnnt-modelerror")).to_be_empty()
    await page.locator('#railnav a[href="#status"]').click()
    await page.route("**/api/stop", lambda r: r.fulfill(status=503, body="Unavailable"), times=1)
    feedback = page.locator("#stop-feedback")
    await stop.click()
    await expect(feedback).to_have_text("Could not stop the engine. Error 503")
    async with page.expect_response(lambda r: r.url.endswith("/api/status")):
        pass  # Ждём следующего штатного опроса.
    await expect(feedback).to_contain_text("503")
    await page.get_by_role("complementary").get_by_role("radio", name="RU").click()
    await expect(feedback).to_have_text("Не удалось остановить движок. Ошибка 503")
    await stop.click()
    await expect(page.locator("#state-pill")).to_have_attribute("data-state", "stopped")
    await expect(stop).to_be_hidden()
    await expect(feedback).to_be_empty()
    assert not supervisor.process.is_running


async def test_bearer_switch_discards_manual_copy_in_chrome(chrome_page, live_client):
    page, expect = chrome_page
    await page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: undefined})")
    await page.goto(str(live_client.base_url) + "/#api")
    await expect(page.locator("#state-pill")).to_have_attribute("data-state", "stopped")
    bearer, copy = page.locator("#example-key"), page.locator('[data-target="snip-curl"]')
    await bearer.check()
    await copy.click()
    manual = page.locator(".manual textarea")
    assert "Authorization: Bearer" in await manual.input_value()
    await bearer.uncheck()
    await expect(manual).to_have_count(0)
    await copy.click()
    assert await manual.input_value() == await page.locator("#snip-curl").text_content()
    assert "Authorization" not in await manual.input_value()


async def test_superseded_clipboard_write_does_not_open_manual_copy(chrome_page, live_client):
    page, expect = chrome_page
    await page.add_init_script("""window.clipboardWrites = [];
        Object.defineProperty(navigator, 'clipboard', {value: {
            writeText: () => new Promise((resolve, reject) => clipboardWrites.push({resolve, reject}))
        }});""")
    await page.goto(str(live_client.base_url) + "/#api")
    await page.locator('[data-target="snip-curl"]').click()
    await page.locator('[data-target="snip-py"]').click()
    await page.evaluate("""() => {
        clipboardWrites[0].reject(new DOMException('Cancelled', 'NotAllowedError'));
        clipboardWrites[1].resolve();
    }""")
    await expect(page.locator("#live")).to_have_text("Copied")
    await expect(page.locator(".manual")).to_have_count(0)


async def test_glossary_enter_waits_for_input_composition(chrome_page, live_client):
    page, expect = chrome_page
    await page.goto(str(live_client.base_url) + "/#glossary")
    phrase = page.locator("#add-phrase")
    tags = page.locator("#tag-list .tag-text")
    candidate = "日本語"
    await phrase.fill(candidate)
    for event in ({"isComposing": True}, {"isComposing": False, "keyCode": 229}):
        await phrase.dispatch_event("keydown", {"key": "Enter", "cancelable": True, **event})
        await expect(phrase).to_have_value(candidate)
        await expect(tags).to_have_count(0)
    await phrase.press("Enter")
    await expect(tags).to_have_text([candidate])
    await expect(phrase).to_have_value("")


async def test_deployment_dependencies_and_old_defaults_in_chrome(chrome_page, live_client):
    from console.state import EngineConfig

    page, expect = chrome_page
    supervisor = live_client.app.state.supervisor
    await supervisor.deploy(EngineConfig(variant="rnnt", punctuation="off", itn="on", pool_size=4,
                                         file_window_concurrency=3, hotwords_default=True, hotwords_boost=4.25))
    await page.goto(str(live_client.base_url) + "/#models")
    await page.locator("#model-settings").click()
    pool, windows = page.locator("#opt-pool"), page.locator("#opt-window-concurrency")
    await expect(windows).to_have_value("3")
    await expect(page.locator("#opt-boost")).to_have_value("4.25")
    await expect(page.locator("#opt-punctuation")).to_have_value("off")
    await expect(page.locator("#opt-itn")).to_have_value("on")
    await pool.select_option("2")
    await expect(windows).to_have_value("2")
    await expect(windows.locator('option[value="3"]')).to_be_disabled()
    await pool.select_option("1")
    await expect(windows).to_be_disabled()
    await expect(windows).to_have_value("1")
    await page.locator("#opt-hotwords-default").select_option("false")
    await expect(page.locator("#opt-boost")).to_be_disabled()
    for lang, note in [("ru", "Недоступно"), ("en", "Unavailable")]:
        await page.locator('#model-dialog-close').click()
        await page.locator(f'.lang-option[data-lang="{lang}"]:visible').click()
        await page.locator('#model-settings').click()
        await expect(page.locator("#window-note")).to_contain_text(note)
        await expect(page.locator("#boost-note")).to_contain_text(note)
    for variant in ("e2e_rnnt", "e2e_rnnt_2026_10_09", "ml_ctc", "ml_ctc_large", "rnnt"):
        await page.locator('#model-dialog-close').click()
        await page.locator("#target-" + variant).check()
        await page.locator('#model-settings').click()
        await expect(page.locator("#opt-punctuation")).to_be_enabled()
        await expect(page.locator("#opt-itn")).to_be_enabled()
        await expect(page.locator("#punctuation-note")).to_contain_text({
            "rnnt": "Auto runs", "e2e_rnnt": "already adds", "e2e_rnnt_2026_10_09": "already adds",
            "ml_ctc": "CTC", "ml_ctc_large": "CTC",
        }[variant])
    async with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/deploy")) as posted:
        await page.locator("#btn-deploy").click()
    config = (await posted.value).post_data_json
    assert config["file_window_concurrency"] == config["pool_size"] == 1
    assert config["hotwords_default"] is False and "hotwords_boost" not in config


async def test_env_deploy_uses_exact_snapshot_and_rejects_conflict(chrome_page, live_client):
    from conftest import wait_for
    from console.state import EngineConfig

    page, expect = chrome_page
    supervisor = live_client.app.state.supervisor
    settings = live_client.app.state.settings
    await supervisor.deploy(EngineConfig(hotwords_default=False, hotwords_boost=5))
    settings.hotwords_default, settings.hotwords_boost = False, 8
    settings.pool_size, settings.file_window_concurrency = 1, 2
    requests = []
    page.on("request", lambda req: requests.append(req.post_data_json) if req.url.endswith("/api/deploy") else None)
    await page.goto(str(live_client.base_url) + "/#models")
    env = page.locator("#btn-deploy-env")
    await expect(env).to_be_visible()
    await expect(env).to_be_disabled()
    await expect(page.locator("#env-error")).to_contain_text("FILE_WINDOW_CONCURRENCY")
    await page.locator('.lang-option[data-lang="ru"]:visible').click()
    await expect(page.locator("#env-error")).to_contain_text("частей одновременно: 2")
    await env.evaluate("button => button.click()")
    assert not requests and supervisor.current.hotwords_boost == 5
    settings.file_window_concurrency = 1
    await page.reload()
    await expect(env).to_be_enabled()
    await page.locator('#model-settings').click()
    await expect(page.locator("#opt-boost")).to_be_disabled()
    await page.locator("#opt-punctuation").select_option("on")
    await page.locator('#model-dialog-close').click()
    await page.route("**/api/deploy", lambda r: r.fulfill(status=503), times=1)
    await env.click()
    await expect(page.locator("#env-error")).to_contain_text("503")
    await page.locator('#model-settings').click()
    await expect(page.locator("#opt-punctuation")).to_have_value("on")
    await expect(page.locator("#draft-note")).not_to_be_empty()
    await page.locator('#model-dialog-close').click()
    await env.click()
    await wait_for(lambda: supervisor.status == "ready" and supervisor.current and supervisor.current.hotwords_boost == 8)
    assert requests == [supervisor.env_config().to_dict()] * 2
    assert supervisor.current.hotwords_default is False and supervisor.current.punctuation == "auto"


async def test_microphone_and_selected_filename_in_chrome(chrome_page, live_client):
    from console.state import EngineConfig

    page, expect = chrome_page
    await live_client.app.state.supervisor.deploy(EngineConfig())
    await page.emulate_media(reduced_motion="no-preference")
    await page.goto(str(live_client.base_url))
    await page.locator("#btn-record").click()
    # Реальный AudioWorklet получает кадры виртуального устройства Chrome, а не пользовательского микрофона.
    await page.wait_for_function("""() => {
        const meter = document.getElementById("meter");
        return !meter.hidden && meter.getContext("2d").getImageData(440, 32, 1, 1).data[3] > 0;
    }""")
    await page.locator("#btn-record").click()
    await expect(page.locator("#result")).to_be_visible()
    await page.locator("#file-mode").click()
    name = "synthetic sample 07.wav"
    await page.locator("#file-input").set_input_files({"name": name, "mimeType": "audio/wav", "buffer": wav_bytes()})
    await expect(page.locator("#source-state")).to_have_text(name)
    await page.locator("#btn-send").click()
    await expect(page.locator("#result")).to_be_visible()
    await page.locator('#railnav a[href="#status"]').click()
    rows = page.locator("#recent-rows tr")
    await expect(rows.nth(0)).to_contain_text(name)
    await expect(rows.nth(0)).to_contain_text("Uploaded file")
    await expect(rows.nth(1)).to_contain_text("microphone.wav")
    await expect(rows.nth(1)).to_contain_text("Live microphone")


async def test_compare_switch_without_engine_restart_in_chrome(chrome_page, live_client, monkeypatch, tmp_path):
    from conftest import wait_for
    from console.state import EngineConfig

    page, expect = chrome_page
    supervisor = live_client.app.state.supervisor
    await supervisor.deploy(EngineConfig(variant="rnnt"))
    await supervisor.deploy(EngineConfig(variant="e2e_rnnt"))
    pid = supervisor.process.pid
    origin = str(live_client.base_url)
    await page.goto(origin + "/#settings")
    toggle = page.locator("#compare-enabled")
    nav = page.locator("#mobile-nav")

    async def section(name):
        if await nav.is_visible():
            await nav.select_option(name)
        else:
            await page.locator(f'#railnav a[href="#{name}"]').click()

    await expect(page.locator("#compare-toggle-note")).to_contain_text("without access protection")
    await expect(toggle).to_be_disabled()
    live_client.app.state.settings.api_key = "ui-synthetic-local"
    await page.evaluate("localStorage.setItem('stt_console_key','ui-synthetic-local')")
    await page.reload()
    await page.route("**/api/settings/compare", lambda r: r.fulfill(status=503, json={
        "error": {"code": "compare_settings_unavailable", "message": "Temporary write failure"},
    }), times=1)
    await toggle.check()
    await expect(page.locator("#compare-toggle-error")).to_contain_text("could not be saved")
    await expect(toggle).not_to_be_checked()
    assert not supervisor.compare_enabled
    async with page.expect_request(lambda r: r.method == "PUT" and r.url.endswith("/api/settings/compare")) as sent:
        await toggle.check()
    assert (await sent.value).post_data_json == {"enabled": True}
    await page.reload()
    await expect(toggle).to_be_checked()
    await section("compare")
    await expect(page.locator("#compare-form")).to_be_visible()
    await page.locator("#compare-file").set_input_files({"name": "comparison.wav", "mimeType": "audio/wav", "buffer": wav_bytes()})
    await page.locator("#btn-compare").click()
    await expect(page.locator("#compare-results .panel")).to_have_count(2)
    for width in (320, 390, 1440):
        await page.set_viewport_size({"width": width, "height": 844 if width < 500 else 900})
        for lang in ("ru", "en"):
            await page.locator(f'.lang-option[data-lang="{lang}"]:visible').click()
            await expect(page.locator("#compare-form")).to_be_visible()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if folder := os.environ.get("KAMERTON_UI_ARTIFACTS"):
                Path(folder).mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=Path(folder) / f"compare-{width}-{lang}.png")
    await section("settings")
    await toggle.uncheck()
    await expect(toggle).not_to_be_checked()
    await section("compare")
    await expect(page.locator("#compare-form")).to_be_hidden()
    await expect(page.locator("#compare-results .panel")).to_have_count(0)
    assert not supervisor.compare_enabled and supervisor.process.pid == pid

    # Выключение во время уже запущенного CLI закрывает только новые задания.
    from console import compare

    record = tmp_path / "synthetic-compare-started.jsonl"
    cli_env = compare._cli_env() | {"FAKE_COMPARE_RECORD": str(record), "FAKE_COMPARE_DELAY": "0.5"}
    monkeypatch.setattr(compare, "_cli_env", lambda: cli_env.copy())
    await section("settings")
    await toggle.check()
    await section("compare")
    await page.locator("#btn-compare").click()
    await wait_for(record.exists)
    await section("settings")
    await toggle.uncheck()
    await expect(toggle).not_to_be_checked()
    await section("compare")
    await expect(page.locator("#compare-form")).to_be_hidden()
    await expect(page.locator("#compare-results .panel")).to_have_count(2)
    assert not supervisor.compare_enabled and supervisor.process.pid == pid
