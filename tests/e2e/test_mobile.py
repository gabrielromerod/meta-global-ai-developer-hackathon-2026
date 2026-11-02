"""Mobile viewport (NFR-017): on a 390 px phone the verdict and the first story sentence show
without scrolling, verdicts are icon plus word, and the legend is readable."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import wait_ready

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 390, "height": 844}


@pytest.fixture
def phone(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(
        viewport=VIEWPORT, device_scale_factor=3, is_mobile=True, has_touch=True
    )
    page = context.new_page()
    yield page
    context.close()


@pytest.mark.parametrize("visit_id", ["v_a", "v_b", "v_c"])
def test_verdict_and_first_sentence_visible_without_scrolling(
    phone: Page, server_url: str, visit_id: str, tmp_path: Path
) -> None:
    phone.goto(f"{server_url}/#/visit/{visit_id}")
    wait_ready(phone)
    assert phone.evaluate("window.scrollY") == 0
    card = phone.get_by_test_id("visit-card")
    verdict = card.get_by_test_id("verdict").first
    first = card.locator("[data-testid=story] .sentence .text").first
    expect(verdict).to_be_visible()
    expect(first).to_be_visible()
    vbox = verdict.bounding_box()
    sbox = first.bounding_box()
    assert vbox is not None
    assert sbox is not None
    assert vbox["y"] >= 0
    assert vbox["y"] + vbox["height"] <= VIEWPORT["height"]
    assert sbox["y"] + sbox["height"] <= VIEWPORT["height"], sbox
    # Icon plus word, never colour alone.
    expect(verdict.locator("svg")).to_be_visible()
    assert verdict.locator(".verdict-word").inner_text().strip()
    # No horizontal scroll at phone width.
    assert phone.evaluate("document.documentElement.scrollWidth") <= VIEWPORT["width"] + 1
    phone.screenshot(path=str(tmp_path / f"mobile_{visit_id}.png"))


def test_legend_readable_on_phone(phone: Page, server_url: str) -> None:
    phone.goto(f"{server_url}/#/visit/v_c")
    wait_ready(phone)
    legend = phone.get_by_test_id("legend")
    legend.scroll_into_view_if_needed()
    expect(legend).to_be_visible()
    expect(legend).to_contain_text("Not observed")
    size = phone.evaluate(
        "parseFloat(getComputedStyle(document.querySelector('.legend-item span')).fontSize)"
    )
    assert size >= 11
