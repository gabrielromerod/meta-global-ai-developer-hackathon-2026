"""Judge path against the cached sandbox (spec 4, 12.1): FR-017, FR-018, FR-027, FR-040,
NFR-009 (MODEL_API_KEY=invalid), NFR-018 (every citation chip), NFR-022 (badges)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import wait_ready

pytestmark = pytest.mark.e2e

GAP = "Not observed · 41 s"


def _times(page: Page) -> list[float]:
    return page.eval_on_selector_all(".player-media", "els => els.map(e => e.currentTime)")


def test_judge_path_scenario_c(page: Page, server_url: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server_url + "/")
    wait_ready(page)

    summary = page.get_by_test_id("summary")
    expect(summary).to_contain_text("motion triggers")
    expect(page.get_by_test_id("summary-visits")).to_have_text("3")
    expect(page.get_by_test_id("summary-alerts")).to_have_text("1")
    expect(page.get_by_test_id("synthetic-banner")).to_contain_text("SYNTHETIC")
    legend = page.get_by_test_id("legend")
    expect(legend).to_be_visible()
    texts = ("Camera view cone", "Blind region", "Estimated position", "Estimated from 2 cameras")
    for text in (*texts, "Low confidence", "Observed path", "Not observed"):
        expect(legend).to_contain_text(text)

    page.locator(".visit-item[data-visit=v_c]").click()
    card = page.get_by_test_id("visit-card")
    expect(card.get_by_test_id("verdict").first).to_contain_text("Needs your attention")
    expect(card.locator(".verdict svg").first).to_be_visible()
    expect(card).to_contain_text(GAP)
    expect(card).to_contain_text("Rule r7 fired")
    expect(page.locator(".twin-label.gap-label")).to_have_text(GAP)
    expect(page.get_by_test_id("twin")).to_have_attribute("data-mode", re.compile("webgl|2d"))

    sentences = card.locator("[data-testid=story] .sentence")
    badges = card.locator("[data-testid=story] [data-testid=source-badge]")
    assert badges.count() == sentences.count() >= 4
    for i in range(badges.count()):
        b = badges.nth(i)
        if b.get_attribute("data-kind") == "model":
            assert b.get_attribute("data-model") == "muse-wonder-1.0"
            assert (b.get_attribute("data-call") or "").startswith("call_")

    players = page.locator(".player-media")
    assert players.count() >= 3
    chips = card.locator("[data-testid=story] [data-testid=citation-chip]")
    assert chips.count() >= 6
    for i in range(chips.count()):
        chip = chips.nth(i)
        chip.click()
        t = float(chip.get_attribute("data-t") or "nan")
        times = _times(page)
        assert max(times) - min(times) < 0.2, (i, times)
        assert abs(page.evaluate("window.vigil.player.absTime") - t) < 0.2
        camera = chip.get_attribute("data-camera")
        if camera:
            expect(page.locator(f".tile[data-camera={camera}]")).to_have_class(
                re.compile("highlight")
            )

    # Players stay in step while playing.
    page.click("#play-toggle")
    page.wait_for_timeout(1200)
    times = _times(page)
    assert max(times) - min(times) < 0.2, times
    page.click("#play-toggle")

    card.get_by_text("How this was decided").click()
    expect(card.get_by_test_id("draft").first).to_contain_text("rejected by the validator")
    expect(card.get_by_test_id("trace")).to_contain_text("forced by code")
    expect(card.get_by_test_id("telemetry")).to_contain_text("model calls")
    assert not errors, errors


@pytest.mark.parametrize(
    ("visit_id", "verdict"),
    [("v_a", "Normal"), ("v_b", "Noteworthy"), ("v_c", "Needs your attention")],
)
def test_every_demo_card_has_every_element(
    page: Page, server_url: str, visit_id: str, verdict: str
) -> None:
    page.goto(f"{server_url}/#/visit/{visit_id}")
    wait_ready(page)
    card = page.get_by_test_id("visit-card")
    expect(card).to_have_attribute("data-visit", visit_id)
    expect(card.get_by_test_id("verdict").first).to_contain_text(verdict)
    assert card.locator("[data-testid=story] .sentence").count() >= 2
    assert card.locator("[data-testid=citation-chip]").count() >= 2
    assert card.locator("[data-testid=story] [data-testid=source-badge]").count() >= 2
    expect(card.locator(".timeline li").first).to_be_visible()
    expect(card.get_by_test_id("trace")).to_be_attached()
    expect(card.get_by_test_id("telemetry")).to_be_attached()
    expect(page.get_by_test_id("legend")).to_be_visible()
    if visit_id == "v_b":
        expect(card.get_by_test_id("watch-notice")).to_contain_text(
            "Now watching: package on porch"
        )


def test_scenario_switcher(page: Page, server_url: str) -> None:
    page.goto(server_url + "/")
    wait_ready(page)
    for sid, visit in (("A", "v_a"), ("B", "v_b"), ("C", "v_c")):
        page.locator(f".tab[data-tab={sid}]").click()
        expect(page.get_by_test_id("visit-card")).to_have_attribute("data-visit", visit)


def test_live_buttons_fall_back_with_notice_when_api_is_down(page: Page, server_url: str) -> None:
    """NFR-009 / FR-026: MODEL_API_KEY=invalid and an unreachable API never blank a screen."""
    page.goto(f"{server_url}/#/visit/v_c")
    wait_ready(page)
    page.get_by_test_id("rerun-live").click()
    out = page.get_by_test_id("rerun-out")
    expect(out.get_by_test_id("fallback-notice")).to_contain_text("Live call failed")
    expect(out).to_contain_text("Needs your attention")

    page.locator("[data-preset]").first.click()
    page.locator("#protect-result [data-run=true]").click()
    expect(page.locator("#protect-result [data-testid=fallback-notice]")).to_contain_text(
        "Live call failed"
    )
    expect(page.locator("#protect-result")).to_contain_text("Protected")

    page.click("#rule-live")
    expect(page.locator("#rule-result [data-testid=fallback-notice]")).to_contain_text(
        "Live call failed"
    )
    expect(page.get_by_test_id("rule-draft")).to_contain_text("identify people")
    page.locator("[data-confirm]").click()
    expect(page.locator(".rule-state")).to_contain_text("active")


def test_2d_fallback_map_draws_the_same_data(page: Page, server_url: str) -> None:
    page.goto(f"{server_url}/?twin=2d#/visit/v_c")
    wait_ready(page)
    expect(page.get_by_test_id("twin")).to_have_attribute("data-mode", "2d")
    expect(page.locator(".twin-label.gap-label")).to_have_text(GAP)
    expect(page.get_by_test_id("twin-mode")).to_contain_text("2D map")


def test_key_and_contributor_ids_never_reach_the_page(page: Page, server_url: str) -> None:
    page.goto(f"{server_url}/#/visit/v_c")
    wait_ready(page)
    html = page.content()
    assert "MODEL_API_KEY" not in html
    assert "-" + "contributor" not in html
