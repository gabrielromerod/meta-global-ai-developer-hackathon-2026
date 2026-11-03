"""FIXTURE: consumer judge path on React, with real API evidence and no live models.

Missing media is asserted unavailable, never a playable synthetic canvas. The original
0.2-second multicamera bound is exercised on genuine generated MP4s in test_real_video.
"""

import struct
from datetime import UTC, datetime

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import UnreachableBackend, wait_ready
from tests.e2e.support import running_app
from vigil.api.app import create_app
from vigil.settings import Settings

pytestmark = pytest.mark.e2e
GAP = "Not observed · 41 s"
NO_TEMPLATES = "does not identify anyone and creates no face, voice or body templates"


def _visit(page, server_url, visit_id):
    page.goto(f"{server_url}/next/#/visit/{visit_id}")
    wait_ready(page)
    card = page.get_by_test_id("visit-card")
    expect(card).to_have_attribute("data-visit", visit_id)
    return card


def test_judge_path_scenario_c(page: Page, server_url: str):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server_url + "/next/")
    wait_ready(page)
    expect(page.locator(".home-summary")).to_contain_text("5 visits → 1 needs attention")
    expect(page.locator(".home-summary")).to_contain_text("unmeasured")
    expect(page.get_by_text("Demo data", exact=True)).to_be_visible()
    state = page.request.get(server_url + "/api/ui/state").json()
    row = next(v for v in state["visits"] if v["id"] == "v_c")
    page.get_by_role("button", name="Open visit " + row["title"], exact=True).click()
    card = page.get_by_test_id("visit-card")
    expect(card.locator(".visit-heading .v-verdict")).to_contain_text("Needs your attention")
    expect(card.locator(".visit-heading .v-verdict svg")).to_be_visible()
    expect(card).to_contain_text(GAP)
    expect(card).to_contain_text("Rule r7 fired")
    expect(page.locator(".house-view canvas")).to_be_visible()
    expect(page.locator(".twin-gap-summary")).to_contain_text(GAP)
    detail = page.request.get(server_url + "/api/ui/visits/v_c").json()
    sentences = card.locator(".visit-sentence")
    badges = card.locator(".visit-source")
    assert badges.count() == sentences.count() == len(detail["sentences"])
    assert badges.count() >= 4
    for index, sentence in enumerate(detail["sentences"]):
        expect(sentences.nth(index).locator("p").first).to_have_text(sentence["text"])
        expect(badges.nth(index)).to_contain_text(sentence["badge"]["label"])
        if sentence["badge"]["kind"] == "model":
            assert sentence["badge"]["model"] == "muse-wonder-1.0"
            assert sentence["badge"]["call_id"].startswith("call_")
    assert page.locator("video.player-media").count() == 0
    assert page.locator(".visit-media-empty").count() >= 3
    citations = [c for s in detail["sentences"] for c in s["citations"]]
    assert len(citations) >= 6
    chips = card.locator(".visit-citation")
    assert chips.count() == len(citations)
    for index, citation in enumerate(citations):
        chips.nth(index).click()
        page.wait_for_function(
            "t=>Math.abs(Number(document.querySelector('#evidence-clock').value)-t)<.2",
            arg=citation["t"],
        )
        expected = next(c["name"] for c in state["cameras"] if c["id"] == citation["camera_id"])
        expect(card.locator(".visit-camera.is-active")).to_contain_text(expected)
    card.get_by_text("How this was decided", exact=True).click()
    expect(card.locator(".visit-trace")).to_contain_text("rejected by the validator")
    expect(card.locator(".visit-trace")).to_contain_text("forced by code")
    expect(card).to_contain_text("perimeter:side_alley")
    expect(card.locator(".visit-trace")).to_contain_text("model calls")
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
def test_every_demo_card_has_every_element(page: Page, server_url, visit_id, verdict):
    card = _visit(page, server_url, visit_id)
    expect(card.locator(".visit-heading .v-verdict")).to_contain_text(verdict)
    assert card.locator(".visit-sentence").count() >= 2
    assert card.locator(".visit-citation").count() >= 2
    assert card.locator(".visit-source").count() >= 2
    card.locator(".visit-event-list li").first.scroll_into_view_if_needed()
    expect(card.locator(".visit-event-list li").first).to_be_visible()
    expect(card.locator(".visit-trace")).to_be_attached()
    expect(card.locator(".visit-context")).to_contain_text(":")
    if visit_id == "v_b":
        expect(card).to_contain_text("Now watching: package on porch")
    if visit_id == "v_bp":
        expect(card).to_contain_text("w3 “deliveries”")


def test_scenario_switcher(page: Page, server_url):
    page.goto(server_url + "/next/")
    wait_ready(page)
    visits = page.request.get(server_url + "/api/ui/state").json()["visits"]
    assert {v["scenario"] for v in visits} == {"A", "A-prime", "B", "B-prime", "C"}
    for visit in visits:
        page.get_by_role("button", name="Attention", exact=True).click()
        page.get_by_role("tab", name="All visits", exact=True).click()
        page.get_by_role("button", name="Open visit " + visit["title"], exact=True).click()
        expect(page.get_by_test_id("visit-card")).to_have_attribute("data-visit", visit["id"])


def test_cached_controls_keep_evidence_visible_when_action_api_is_down(page: Page, server_url):
    card = _visit(page, server_url, "v_c")
    page.route(
        "**/api/visits/v_c/rerun",
        lambda route: route.fulfill(
            status=503,
            json={"detail": "Story service unavailable; recorded evidence remains available."},
        ),
    )
    card.get_by_text("How this was decided", exact=True).click()
    card.get_by_role("button", name="Rebuild story from cache").click()
    expect(card.get_by_role("alert")).to_contain_text("Story service unavailable")
    expect(card.locator(".visit-heading .v-verdict")).to_contain_text("Needs your attention")
    assert card.locator(".visit-sentence").count() >= 4
    page.get_by_role("button", name="Rules and protected objects", exact=True).click()
    page.route(
        "**/api/rules/compile",
        lambda route: route.fulfill(
            status=503, json={"detail": "Rule service unavailable; current rules remain active."}
        ),
    )
    field = page.get_by_role("textbox", name="Rule text")
    field.fill("Tell me if anyone except family touches the bin after 9 PM")
    page.get_by_role("button", name="Review rule draft").click()
    expect(page.get_by_role("alert")).to_contain_text("Rule service unavailable")
    expect(field).to_have_value("Tell me if anyone except family touches the bin after 9 PM")
    expect(page.get_by_role("region", name="Current rules")).to_contain_text("Side gate after dark")


def test_2d_fallback_map_draws_the_same_data(page: Page, server_url):
    page.goto(server_url + "/next/?twin=2d#/visit/v_c")
    wait_ready(page)
    view = page.get_by_test_id("property-map")
    expect(view.get_by_role("img", name="Property evidence map")).to_be_visible()
    expect(view).to_contain_text("2D map")
    expect(view).to_contain_text(GAP)
    expect(view.get_by_role("button", name="Select Left passage")).to_be_visible()
    assert view.locator(".map-gap").count() >= 1


def test_key_and_contributor_ids_never_reach_the_page(page: Page, server_url):
    _visit(page, server_url, "v_c")
    html = page.content()
    assert "MODEL_API_KEY" not in html
    assert "-" + "contributor" not in html


def test_step6_each_sample_audio_button_gives_an_editable_transcript_and_a_draft(
    page: Page, server_url
):
    page.goto(server_url + "/next/#/rules")
    wait_ready(page)
    fixtures = page.request.get(server_url + "/api/voice/fixtures").json()["fixtures"]
    assert [f["id"] for f in fixtures] == ["vf_family_bin", "vf_strangers_gate", "vf_named_gate"]
    for fixture in fixtures:
        page.get_by_role("button", name=fixture["label"]).click()
        text = page.get_by_role("textbox", name="Rule text")
        expect(text).to_have_value(fixture["transcript"])
        expect(text).to_be_editable()
        with page.expect_response("**/api/rules/compile") as response:
            page.get_by_role("button", name="Review rule draft").click()
        body = response.value.json()
        assert body["live"] is False
        draft = page.get_by_role("region", name="Rule draft", exact=True)
        expect(draft).to_contain_text(body["result"]["applies_label"])
        expect(draft).to_contain_text(body["result"]["basis_note"])
        expect(draft).to_contain_text(NO_TEMPLATES)
        expect(draft.get_by_role("button", name="Confirm rule")).to_be_disabled()
    expect(draft).to_contain_text("Vigil can't recognise individuals")
    page.get_by_role("button", name=fixtures[0]["label"]).click()
    page.get_by_role("button", name="Review rule draft").click()
    expect(draft).to_contain_text("Applies to everyone except household members.")
    expect(draft).to_contain_text("Vigil treats someone as household only when it saw them")


def test_browser_encodes_16khz_mono_16bit_wav_the_server_accepts(page: Page, tmp_path):
    """Drive actual React recorder/encoder with fake PCM, never a real microphone."""
    settings = Settings(
        _env_file=None,
        mode="sandbox",
        MODEL_API_KEY="invalid",
        meta_cache_only=True,
        meta_base_url="http://127.0.0.1:9/v1",
        data_dir=tmp_path,
        db_path=tmp_path / "state.db",
        ledger_path=tmp_path / "ledger.db",
        cache_dir=tmp_path / "cache",
    )
    app = create_app(
        settings,
        live_backend=UnreachableBackend(),
        clock=lambda: datetime(2026, 11, 3, 20, tzinfo=UTC).timestamp(),
    )
    bodies = []

    @app.middleware("http")
    async def observe_fixture_wav(request, call_next):
        if request.url.path == "/api/voice/transcribe" and request.headers.get(
            "content-type", ""
        ).startswith("audio/wav"):
            bodies.append(await request.body())
        return await call_next(request)

    page.add_init_script("""(() => {
      const probe={stopped:0,closed:0,node:null};window.vigilAudioFixture=probe;
      Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{
        getUserMedia:async()=>({getTracks:()=>[{stop:()=>probe.stopped++}]})
      }});
      window.AudioContext=class {
        sampleRate=48000;state='running';destination={};
        createMediaStreamSource(){return {connect(){},disconnect(){}};}
        createScriptProcessor(){const node={connect(){},disconnect(){},onaudioprocess:null};
          probe.node=node;return node;}
        async close(){this.state='closed';probe.closed++;}
      };
      probe.feed=seconds=>{const samples=new Float32Array(48000*seconds);
        for(let i=0;i<samples.length;i++)samples[i]=.5*Math.sin(2*Math.PI*440*i/48000);
        probe.node.onaudioprocess({inputBuffer:{getChannelData:()=>samples}});};
    })()""")
    with running_app(app) as url:
        page.goto(url + "/next/#/rules")
        wait_ready(page)
        page.get_by_role("button", name="Record a voice rule").click()
        dialog = page.get_by_role("dialog", name="Voice rule", exact=True)
        dialog.get_by_role("button", name="Start microphone").click()
        expect(dialog.get_by_role("button", name="Stop and transcribe")).to_be_visible()
        page.evaluate("window.vigilAudioFixture.feed(2)")
        with page.expect_response("**/api/voice/transcribe") as result:
            dialog.get_by_role("button", name="Stop and transcribe").click()
        assert result.value.status == 200
        assert result.value.json()["result"]["transcript"] == ""
        page.get_by_role("button", name="Record a voice rule").click()
        dialog.get_by_role("button", name="Start microphone").click()
        expect(dialog.get_by_role("button", name="Stop and transcribe")).to_be_visible()
        with page.expect_response("**/api/voice/transcribe") as limit:
            page.evaluate("window.vigilAudioFixture.feed(31)")
        assert limit.value.status == 200
        assert len(bodies) == 2
        first, long = bodies
        assert first[:4] == b"RIFF"
        assert first[8:12] == b"WAVE"
        assert struct.unpack_from("<HHI", first, 20) == (1, 1, 16000)
        assert struct.unpack_from("<H", first, 34)[0] == 16
        assert struct.unpack_from("<I", first, 40)[0] == 2 * 16000 * 2
        assert len(first) == 44 + 2 * 16000 * 2
        assert len(long) == 44 + 30 * 16000 * 2 < 2 * 1024 * 1024
        assert page.evaluate("window.vigilAudioFixture.stopped") == 2
        assert page.evaluate("window.vigilAudioFixture.closed") == 2
        fallback = page.request.post(
            url + "/api/voice/transcribe?live=1", data=first, headers={"content-type": "audio/wav"}
        )
        assert fallback.status == 200
        assert fallback.json()["notice"].startswith("Live call failed")


def test_a_prime_and_c_contrast_cards(page: Page, server_url):
    household = _visit(page, server_url, "v_ap")
    expect(household.locator(".visit-heading .v-verdict")).to_contain_text("Normal")
    expect(household.locator(".visit-event-list")).to_contain_text("6:02:28 PM")
    expect(household.locator(".visit-context")).to_contain_text("egress:front_door_egress")
    expect(household.locator(".visit-context")).to_contain_text("Household")
    expect(household.locator(".visit-context")).to_contain_text("r7")
    expect(household.locator(".visit-context")).to_contain_text("did not fire")
    external = _visit(page, server_url, "v_c")
    expect(external.locator(".visit-heading .v-verdict")).to_contain_text("Needs your attention")
    expect(external.locator(".visit-event-list")).to_contain_text("6:14:05 PM")
    expect(external.locator(".visit-context")).to_contain_text("perimeter:side_alley")
    expect(external.locator(".visit-context")).to_contain_text("Arrived from outside")
    expect(external).to_contain_text("Rule r7 fired")


def test_this_was_expected_is_feedback_only(page: Page, server_url):
    card = _visit(page, server_url, "v_b")
    card.get_by_role("button", name="This was expected").click()
    expect(card.locator(".app-notice")).to_contain_text("never changes a verdict")
    expect(card.locator(".visit-heading .v-verdict")).to_contain_text("Noteworthy")
