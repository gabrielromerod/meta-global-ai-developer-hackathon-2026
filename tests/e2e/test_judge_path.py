"""Judge path against the cached sandbox (spec 4, 12.1; P0 blocking suite 5): FR-017, FR-018,
FR-022 (step 6 through each sample-audio button, browser WAV encoding), FR-027 (5 scenarios),
FR-040, FR-044 (A′ vs C: same gate, opposite outcomes by spatial origin), NFR-009
(MODEL_API_KEY=invalid), NFR-018 (every citation chip), NFR-022 (badges)."""

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
    expect(page.get_by_test_id("summary-visits")).to_have_text("5")
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
    expect(card.get_by_test_id("role-basis")).to_contain_text("perimeter:side_alley")
    expect(card.get_by_test_id("telemetry")).to_contain_text("model calls")
    assert not errors, errors


@pytest.mark.parametrize(
    ("visit_id", "verdict"),
    [
        ("v_a", "Normal"),
        ("v_ap", "Normal"),
        ("v_b", "Noteworthy"),
        ("v_bp", "Normal"),
        ("v_c", "Needs your attention"),
    ],
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
    expect(card.get_by_test_id("roles")).to_contain_text(":")  # every subject shows its basis
    if visit_id == "v_b":
        expect(card.get_by_test_id("watch-notice")).to_contain_text(
            "Now watching: package on porch"
        )
    if visit_id == "v_bp":
        expect(card.get_by_test_id("window-chip")).to_contain_text('w3 "deliveries"')


def test_scenario_switcher(page: Page, server_url: str) -> None:
    page.goto(server_url + "/")
    wait_ready(page)
    tabs = (("A", "v_a"), ("A-prime", "v_ap"), ("B", "v_b"), ("B-prime", "v_bp"), ("C", "v_c"))
    expect(page.locator(".tab[data-tab=A-prime]")).to_contain_text("A′")
    expect(page.locator(".tab[data-tab=B-prime]")).to_contain_text("B′")
    for sid, visit in tabs:
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
    expect(page.get_by_test_id("rule-draft")).to_contain_text("does not identify anyone")
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


# --- step 6: voice rules through the sample-audio buttons, cached mode (FR-022) -------------

APPLIES = {
    "vf_family_bin": "Applies to: non-household",
    "vf_strangers_gate": "Applies to: outsiders only",
    "vf_named_gate": "Applies to: non-household",
}
NO_TEMPLATES = "does not identify anyone and creates no face, voice or body templates"


def test_step6_each_sample_audio_button_gives_an_editable_transcript_and_a_draft(
    page: Page, server_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    fixtures = page.request.get(f"{server_url}/api/voice/fixtures").json()["fixtures"]
    assert [f["id"] for f in fixtures] == list(APPLIES)
    page.goto(server_url + "/")
    wait_ready(page)
    samples = page.get_by_test_id("voice-sample")
    expect(samples).to_have_count(3)
    transcript = page.get_by_test_id("transcript")
    meta = page.get_by_test_id("transcript-meta")
    for i, fixture in enumerate(fixtures):
        samples.nth(i).click()
        expect(transcript).to_have_value(fixture["transcript"])
        expect(meta).to_contain_text("Recorded result")  # labelled offline (spec 4 step 6)
        expect(meta).to_contain_text("muse-voice-transcribe-1.0")
        page.click("#rule-form button[type=submit]")
        draft = page.get_by_test_id("rule-draft")
        expect(draft.get_by_test_id("applies-badge")).to_have_text(APPLIES[fixture["id"]])
        expect(draft.get_by_test_id("basis-note")).to_contain_text(NO_TEMPLATES)
    named = page.get_by_test_id("rule-draft")
    expect(named).to_contain_text("Vigil can't recognise individuals")
    # Back to the judge's phrase; the basis note is the spec's draft-card wording.
    samples.first.click()
    expect(transcript).to_have_value(fixtures[0]["transcript"])
    page.click("#rule-form button[type=submit]")
    note = page.get_by_test_id("rule-draft").get_by_test_id("basis-note")
    expect(note).to_contain_text("Applies to everyone except household members.")
    expect(note).to_contain_text("Vigil treats someone as household only when it saw them")
    page.locator("[data-confirm]").click()
    expect(page.locator(".rule-state")).to_contain_text("active")
    # The transcript stays editable, and a live compile with the API down falls back.
    transcript.fill(fixtures[0]["transcript"])
    page.click("#rule-live")
    expect(page.locator("#rule-result [data-testid=fallback-notice]")).to_contain_text(
        "Live call failed; recorded result from"
    )
    expect(page.get_by_test_id("rule-draft").get_by_test_id("applies-badge")).to_have_text(
        "Applies to: non-household"
    )
    assert not errors, errors


def test_browser_encodes_16khz_mono_16bit_wav_the_server_accepts(
    page: Page, server_url: str
) -> None:
    """FR-022: Web Audio samples at 48 kHz become a 16 kHz mono PCM16 WAV; 30 s < 2 MB."""
    page.goto(server_url + "/")
    wait_ready(page)
    info = page.evaluate(
        """async () => {
          const v = await import('/voice.js');
          const rate = 48000, n = rate * 2;
          const chunk = new Float32Array(n);
          for (let i = 0; i < n; i++) chunk[i] = 0.5 * Math.sin(2 * Math.PI * 440 * i / rate);
          const halves = [chunk.subarray(0, n / 2), chunk.subarray(n / 2)];
          const { blob, seconds } = v.toWav(halves, rate);
          const dv = new DataView(await blob.arrayBuffer());
          const tag = (o) => String.fromCharCode(...[0, 1, 2, 3].map((k) => dv.getUint8(o + k)));
          const long = v.toWav([new Float32Array(rate * 31)], rate);
          const post = async (body, live) => {
            const r = await fetch('/api/voice/transcribe' + (live ? '?live=1' : ''),
              { method: 'POST', headers: { 'content-type': 'audio/wav' }, body });
            return { status: r.status, body: await r.json() };
          };
          return {
            riff: tag(0), wave: tag(8), fmt: dv.getUint16(20, true),
            channels: dv.getUint16(22, true), rate: dv.getUint32(24, true),
            bits: dv.getUint16(34, true), data: dv.getUint32(40, true), size: blob.size,
            seconds, type: blob.type, longSize: long.blob.size, longSeconds: long.seconds,
            cached: await post(blob, false), live: await post(blob, true),
          };
        }"""
    )
    assert (info["riff"], info["wave"]) == ("RIFF", "WAVE")
    assert (info["fmt"], info["channels"], info["rate"], info["bits"]) == (1, 1, 16000, 16)
    assert info["data"] == 2 * 16000 * 2
    assert info["size"] == 44 + info["data"]
    assert info["seconds"] == 2
    assert info["type"] == "audio/wav"
    assert info["longSeconds"] == 30  # trimmed to the 30 s limit
    assert info["longSize"] == 44 + 30 * 16000 * 2 < 2 * 1024 * 1024  # about 0.96 MB
    assert info["cached"]["status"] == 200
    assert info["cached"]["body"]["result"]["transcript"] == ""
    assert info["live"]["status"] == 200  # API down: degrades, never blanks
    assert info["live"]["body"]["notice"].startswith("Live call failed")


# --- A′ vs C: the same touch of the same gate after dark, opposite outcomes (spec 4) -------


def test_a_prime_and_c_contrast_cards(page: Page, server_url: str) -> None:
    page.goto(f"{server_url}/#/visit/v_ap")
    wait_ready(page)
    card = page.get_by_test_id("visit-card")
    expect(card).to_have_attribute("data-visit", "v_ap")
    expect(card.get_by_test_id("verdict").first).to_contain_text("Normal")
    expect(card.locator(".timeline")).to_contain_text("6:02:28 PM")  # touch, after 17:30
    expect(card.get_by_test_id("roles")).to_contain_text("egress:front_door_egress")
    expect(card.get_by_test_id("role-chip").first).to_contain_text("Household")
    expect(card.locator(".rules-fired")).to_have_count(0)
    card.get_by_text("How this was decided").click()
    expect(card.get_by_test_id("role-basis")).to_contain_text("egress:front_door_egress")
    excluded = card.get_by_test_id("rule-excluded")
    expect(excluded).to_contain_text("r7")
    expect(excluded).to_contain_text("non-household")
    expect(excluded).to_contain_text("did not fire")

    page.evaluate("location.hash = '#/visit/v_c'")
    expect(card).to_have_attribute("data-visit", "v_c")
    expect(card.get_by_test_id("verdict").first).to_contain_text("Needs your attention")
    expect(card.locator(".timeline")).to_contain_text("6:14:05 PM")
    expect(card.get_by_test_id("roles")).to_contain_text("perimeter:side_alley")
    expect(card.get_by_test_id("role-chip").first).to_contain_text("Arrived from outside")
    expect(card).to_contain_text("Rule r7 fired")
    card.get_by_text("How this was decided").click()
    expect(card.get_by_test_id("role-basis")).to_contain_text("perimeter:side_alley")
    expect(card.get_by_test_id("rule-excluded")).to_have_count(0)


def test_this_was_expected_is_feedback_only(page: Page, server_url: str) -> None:
    page.goto(f"{server_url}/#/visit/v_b")
    wait_ready(page)
    card = page.get_by_test_id("visit-card")
    card.get_by_test_id("feedback-expected").click()
    expect(card.get_by_test_id("feedback-note")).to_contain_text("never changes a verdict")
    expect(card.get_by_test_id("verdict").first).to_contain_text("Noteworthy")
