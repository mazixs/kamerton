"""Сводный бенчмарк, места и прокрутка таблицы."""

import re
from pathlib import Path

import pytest


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
async def test_wer_report_is_readable_and_sorts_models(live_client, engine):
    pw = pytest.importorskip("playwright.async_api")
    async with pw.async_playwright() as driver:
        if engine == "webkit" and not Path(driver.webkit.executable_path).is_file():
            pytest.skip("Нужен Playwright WebKit")
        browser = await driver.webkit.launch() if engine == "webkit" else await driver.chromium.launch(channel="chrome")
        try:
            page = await browser.new_page(viewport={"width": 390, "height": 850})
            await page.goto(str(live_client.base_url) + "/#compare")
            await page.get_by_role("link", name="Open WER benchmarks").click()

            await pw.expect(page.get_by_role("heading", name="WER benchmarks", level=1)).to_be_visible()
            await pw.expect(page.locator('[data-type="brand-caption"]:visible')).to_have_text("ASR Console")
            table = page.get_by_role("table", name="Model leaderboard")
            await pw.expect(table.get_by_role("rowheader")).to_have_count(21)
            await pw.expect(table.get_by_role("rowheader").first).to_contain_text("GigaAM v4 RNN-T")
            await pw.expect(table.locator("thead tr:nth-child(2) th")).to_have_count(5)
            await pw.expect(table.locator("tbody .benchmark-missing")).to_have_count(0)
            widths = await table.locator("tbody tr:first-child td").evaluate_all(
                "cells => cells.map(cell => cell.getBoundingClientRect().width)",
            )
            assert max(widths) - min(widths) < 1
            alignment = await table.locator("tbody .benchmark-value").evaluate_all(
                "values => values.every(value => {"
                "const number = value.querySelector('.benchmark-number').getBoundingClientRect();"
                "const badge = value.querySelector('.benchmark-rank')?.getBoundingClientRect();"
                "const inset = value.getBoundingClientRect().right - number.right;"
                "const gap = badge && number.left - badge.right;"
                "return Math.abs(inset) < 1 && (!badge || (gap >= 5 && gap <= 7));"
                "})",
            )
            assert alignment
            assert await table.locator("thead button").evaluate_all(
                "buttons => buttons.every(button => [...button.children].every(label => "
                "label.getBoundingClientRect().bottom <= button.getBoundingClientRect().bottom + 1))",
            )

            soniox = table.get_by_role("row").filter(has=page.get_by_role("rowheader", name=re.compile("^Soniox")))
            await pw.expect(soniox.locator('[data-metric="podcast-itErrors"] strong')).to_have_text("13/338")
            await pw.expect(soniox.locator('[data-metric="podcast-numericErrors"] strong')).to_have_text("0/33")
            ultra = table.get_by_role("row").filter(has=page.get_by_role("rowheader", name=re.compile("^Parakeet Ultra")))
            await pw.expect(ultra.locator('[data-metric="podcast-wer"]')).to_have_attribute("data-rank", "2")
            await pw.expect(soniox.locator('[data-metric="podcast-wer"]')).to_have_attribute("data-rank", "2")

            all_metrics = page.get_by_role("button", name="All metrics")
            await all_metrics.click()
            await pw.expect(all_metrics).to_have_attribute("aria-pressed", "true")
            await pw.expect(table.locator('thead tr:nth-child(2) th')).to_have_count(32)
            await pw.expect(table.get_by_role("rowheader")).to_have_count(21)
            await pw.expect(soniox.locator('[data-metric="server-rtf"]')).to_have_text("-No measurement")
            rtf_sort = table.get_by_role("button", name="RTF", exact=True).first
            await rtf_sort.click()
            await pw.expect(table.get_by_role("columnheader", name="RTF", exact=True).first).to_have_attribute("aria-sort", "ascending")
            await pw.expect(table.get_by_role("rowheader").first).to_contain_text("Whisper Tiny")
            held_row = await table.get_by_role("rowheader").first.element_handle()
            await rtf_sort.focus()
            await rtf_sort.press("Enter")
            await pw.expect(rtf_sort).to_be_focused()
            await pw.expect(table.get_by_role("rowheader").first).to_contain_text("Whisper Large V3 Q5_0")
            assert await held_row.evaluate("element => element.isConnected")
            await pw.expect(table.locator("[aria-sort]")).to_have_count(1)
            await pw.expect(table.get_by_role("columnheader", name="RTF", exact=True).first).to_have_attribute("aria-sort", "descending")

            await pw.expect(soniox.locator('[data-metric="podcast-numericExtra"]')).to_have_text("2")
            archived = table.get_by_role("row").filter(has=page.get_by_role("rowheader", name=re.compile(r"^GigaAM v3 E2E RNN-T \(2\.17\.0\)")))
            await pw.expect(archived.locator('[data-metric="fleurs-wer"] strong')).to_have_text("4.32%")
            await pw.expect(archived.locator('[data-metric="human-ru"] .benchmark-number')).to_have_text("6.40%")
            await pw.expect(archived.locator('[data-metric="podcast-wer"] .benchmark-number')).to_have_text("18.66%")

            scroll = page.get_by_role("region", name="Benchmark results")
            await scroll.focus()
            await pw.expect(scroll).to_be_focused()
            assert await scroll.evaluate("el => el.scrollWidth > el.clientWidth && el.scrollHeight > el.clientHeight")
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await scroll.evaluate("el => { el.scrollTop = 150; el.scrollLeft = 200 }")
            header_top = await table.locator("thead").evaluate("el => el.getBoundingClientRect().top")
            model_left = await table.get_by_role("rowheader").first.evaluate("el => el.getBoundingClientRect().left")
            bounds = await scroll.bounding_box()
            assert abs(header_top - bounds["y"]) < 2
            assert abs(model_left - bounds["x"]) < 2

            await table.locator('button[data-metric="phrases-numbers"]').click()
            await pw.expect(table.locator('td[data-metric="phrases-numbers"][data-rank="1"] strong').first).to_have_text("6/6")
            await all_metrics.click()
            await pw.expect(table.locator('thead tr:nth-child(2) th')).to_have_count(5)
            await pw.expect(table.get_by_role("rowheader").first).to_contain_text("GigaAM v4 RNN-T")
            await page.get_by_text("Test sets and methods", exact=True).click()
            await pw.expect(page.get_by_text("Soniox STT Async v6 is the machine transcript reference", exact=False)).to_be_visible()
        finally:
            await browser.close()
