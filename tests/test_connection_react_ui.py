"""Поведение интерфейса подключения и диагностики в WebKit."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


async def test_api_picker_and_journal_filters_in_webkit(live_client):
    pw = pytest.importorskip("playwright.async_api")
    now = datetime.now(timezone.utc)
    bus = live_client.app.state.bus
    async with pw.async_playwright() as playwright:
        if not Path(playwright.webkit.executable_path).is_file():
            pytest.skip("Нужен браузер WebKit для Playwright")
        browser = await playwright.webkit.launch()
        page = await browser.new_page(**playwright.devices["iPhone 15"])
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.route("**/v1/models", lambda route: route.fulfill(json={"data": [{"id": "gigaam-v3-rnnt"}]}))
        await page.route("**/api/journal", lambda route: route.fulfill(json={"events": [
            {"at": now.isoformat(), "category": "deploy", "level": "info", "code": "deploy.ready", "params": {"variant": "rnnt"}},
            {"at": (now - timedelta(hours=2)).isoformat(), "category": "engine", "level": "error", "code": "watchdog.failed", "params": {"variant": "rnnt", "attempt": 1}},
        ]}))
        try:
            await page.goto(str(live_client.base_url) + "/#api")
            heading = page.get_by_role("heading", name="Our models", level=2)
            await pw.expect(heading).to_have_js_property("tagName", "H2")
            picker = page.locator("#client-model-picker")
            await pw.expect(picker.locator("..")).to_have_css("display", "grid")
            summary = picker.locator("summary")
            await pw.expect(summary).to_contain_text("gigaam-v3-rnnt")
            await summary.tap()
            available = page.locator('[data-model-id="gigaam-v3-rnnt"]')
            missing = page.locator('[data-model-id="gigaam-multilingual-ctc"]')
            await pw.expect(available.get_by_role("button", name="gigaam-v3-rnnt")).to_be_visible()
            await pw.expect(missing.get_by_role("button", name="Deploy gigaam-multilingual-ctc")).to_be_visible()
            await pw.expect(missing).to_contain_text("not downloaded")
            await pw.expect(missing.locator(".api-model-select")).to_have_count(0)
            row_fits = await missing.get_by_role("button").evaluate("button => button.scrollWidth <= button.clientWidth + 1")
            assert row_fits
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")

            await page.locator("#mobile-nav").select_option("journal")
            filters = page.locator('[data-layout~="filters"]')
            await pw.expect(filters).to_have_css("display", "flex")
            await pw.expect(filters).to_have_css("flex-direction", "row")
            rows = page.locator("#journal-events li")
            await pw.expect(rows).to_have_count(2)
            await page.locator("#journal-level").select_option("error")
            await pw.expect(rows).to_have_count(1)
            await pw.expect(rows).to_contain_text("Could not restart rnnt")
            await page.locator("#journal-period").select_option("hour")
            await pw.expect(page.locator("#journal-note")).to_contain_text("No events")
            await page.locator("#tech-logs summary").tap()
            bus.publish_log("Synthetic diagnostic line")
            await pw.expect(page.locator("#logs")).to_contain_text("Synthetic diagnostic line")
            assert not errors, errors
        finally:
            await browser.close()
