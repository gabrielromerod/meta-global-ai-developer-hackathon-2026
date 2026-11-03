"""FIXTURE: real React/API behavior with cached ledgers and generated media only."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import UnreachableBackend, wait_ready
from tests.e2e.support import running_app
from tests.e2e.test_real_video import video_server as generated_video_fixture
from vigil.api.app import create_app
from vigil.settings import Settings

pytestmark = pytest.mark.e2e
video_server = generated_video_fixture


def test_reviewed_react_app_is_the_root_application(page: Page, server_url):
    page.goto(server_url + "/")
    wait_ready(page)
    expect(page.locator(".v-app-shell")).to_be_visible()
    expect(page.get_by_role("button", name="Home", exact=True)).to_be_visible()
    expect(page.get_by_text("Demo data", exact=True).first).to_be_visible()
    page.goto(server_url + "/#/visit/v_c")
    wait_ready(page)
    expect(page.locator(".house-view")).to_be_visible()
    expect(page.get_by_text("Needs your attention", exact=True).first).to_be_visible()


def test_react_owner_token_countdown_and_expected_window_crud(page: Page, tmp_path):
    settings = Settings(
        _env_file=None,
        mode="edge",
        owner_token="synthetic-owner-token",
        db_path=tmp_path / "owner.sqlite",
        ledger_path=tmp_path / "ledger.sqlite",
        data_dir=tmp_path,
        meta_cache_only=True,
    )
    with running_app(create_app(settings, live_backend=UnreachableBackend())) as url:
        page.goto(url + "/next/#/settings")
        wait_ready(page)
        page.get_by_role("tab", name="Owner controls").click()
        page.get_by_role("textbox", name="Owner token").fill("synthetic-owner-token")
        page.get_by_role("button", name="Save owner token").click()
        expect(page.get_by_text("Owner session active")).to_be_visible()
        assert (
            page.evaluate("sessionStorage.getItem('vigil_owner_token')") == "synthetic-owner-token"
        )
        assert page.evaluate("localStorage.getItem('vigil_owner_token')") is None
        page.get_by_role("button", name="I'm outside").click()
        countdown = page.get_by_role("status").filter(has_text="s remaining")
        expect(countdown).to_be_visible()
        assert 118 <= int(countdown.inner_text().split()[0]) <= 120
        page.get_by_role("button", name="New expected window").click()
        dialog = page.get_by_role("dialog", name="New expected window")
        dates = page.evaluate("""() => {
          const local = d => new Date(d.getTime()-d.getTimezoneOffset()*60000)
            .toISOString().slice(0,16);
          return [local(new Date(Date.now()+600000)),local(new Date(Date.now()+1200000))];
        }""")
        dialog.get_by_label("Window label").fill("Fixture delivery")
        dialog.get_by_label("Window starts").fill(dates[0])
        dialog.get_by_label("Window ends").fill(dates[1])
        dialog.get_by_label("Window camera").select_option("front_left_duo")
        dialog.get_by_role("button", name="Create expected window").click()
        expect(dialog).not_to_be_visible()
        row = page.get_by_role("article", name="Fixture delivery")
        expect(row).to_contain_text("Scheduled")
        expect(row).to_contain_text("Front left Duo")
        row.get_by_role("button", name="Cancel window").click()
        expect(row).to_contain_text("Cancelled")
        page.reload()
        wait_ready(page)
        page.get_by_role("tab", name="Owner controls").click()
        expect(page.get_by_role("article", name="Fixture delivery")).to_contain_text("Cancelled")


def test_react_confirmed_rule_clears_the_draft_and_uses_edge_session_copy(page, tmp_path):
    settings = Settings(
        _env_file=None,
        mode="edge",
        owner_token="synthetic-owner-token",
        db_path=tmp_path / "owner.db",
        ledger_path=tmp_path / "ledger.db",
        data_dir=tmp_path,
        meta_cache_only=True,
    )
    with running_app(create_app(settings, live_backend=UnreachableBackend())) as url:
        page.goto(url + "/next/#/settings")
        wait_ready(page)
        page.get_by_role("tab", name="Owner controls").click()
        page.get_by_role("textbox", name="Owner token").fill("synthetic-owner-token")
        page.get_by_role("button", name="Save owner token").click()
        expect(page.get_by_text("Owner session active")).to_be_visible()
        page.get_by_role("button", name="Rules and protected objects", exact=True).click()
        sample = page.request.get(url + "/api/voice/fixtures").json()["fixtures"][0]
        page.get_by_role("button", name=sample["label"]).click()
        expect(page.get_by_role("textbox", name="Rule text")).to_have_value(sample["transcript"])
        page.get_by_role("button", name="Review rule draft").click()
        draft = page.get_by_role("region", name="Rule draft", exact=True)
        draft.get_by_role("button", name="Confirm rule").click()
        expect(draft).not_to_be_visible()
        expect(page.get_by_role("region", name="Current rules")).to_contain_text(
            "Recycling bin after 9 PM"
        )
        expect(page.get_by_role("status")).to_contain_text("server session")
        expect(page.get_by_role("status")).not_to_contain_text("Sandbox")


def test_react_home_shows_household_and_external_gate_context(page: Page, server_url):
    page.goto(server_url + "/next/")
    wait_ready(page)
    comparison = page.get_by_role("region", name="Same action, different context")
    expect(comparison).to_contain_text("Normal")
    expect(comparison).to_contain_text("Needs attention")
    expect(comparison).to_contain_text("came out of the house")
    expect(comparison).to_contain_text("excludes household")
    expect(comparison).to_contain_text("An owner rule fired")
    assert page.locator("video").count() == 0  # Missing clips stay honestly unavailable.
    assert page.locator("body").evaluate("e=>e.scrollHeight<=innerHeight")


def test_react_map_fallback_keeps_cameras_and_explicit_gaps(page: Page, server_url):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server_url + "/next/?twin=2d#/visit/v_c")
    wait_ready(page)
    view = page.get_by_test_id("property-map")
    expect(view.get_by_role("img", name="Property evidence map")).to_be_visible()
    house = view.locator(".map-house").bounding_box()
    trees = view.locator(".map-trees").bounding_box()
    assert house is not None
    assert trees is not None
    assert trees["x"] > house["x"]
    expect(view).to_contain_text("Not observed · 41 s")
    expect(view.get_by_role("button", name="Select Left passage")).to_be_visible()
    view.get_by_role("button", name="Select Left passage").click()
    expect(view.get_by_role("button", name="Select Left passage")).to_have_attribute(
        "aria-pressed", "true"
    )
    page.get_by_role("slider", name="Evidence time").fill("15280")
    expect(view.get_by_label("Current estimated position")).to_have_count(0)
    assert page.locator(".house-view canvas").count() == 0
    assert not errors, errors


def test_react_group_view_allows_manual_presets_and_a_new_group_request(page, server_url):
    page.emulate_media(reduced_motion="reduce")
    page.goto(server_url + "/next/")
    wait_ready(page)
    page.get_by_role("tab", name="Front garden", exact=True).click()
    canvas = page.get_by_test_id("twin-canvas")
    expect(canvas).to_have_attribute("data-camera-position", re.compile(r".+"))
    before = canvas.get_attribute("data-camera-position")
    page.get_by_role("tab", name="Top-down", exact=True).click()
    expect(page.get_by_role("tab", name="Top-down", exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
    page.wait_for_function(
        "before=>document.querySelector('[data-testid=twin-canvas]')"
        ".dataset.cameraPosition!==before",
        arg=before,
    )
    page.get_by_role("tab", name="Porch", exact=True).first.click()
    expect(page.get_by_role("tab", name="Front", exact=True)).to_have_attribute(
        "aria-selected", "true"
    )


@pytest.mark.parametrize("timezone", ["UTC", "Asia/Tokyo", "America/Los_Angeles"])
def test_react_recorded_clock_matches_citations_in_every_viewer_timezone(
    browser, server_url, timezone
):
    context = browser.new_context(timezone_id=timezone, viewport={"width": 1470, "height": 870})
    try:
        page = context.new_page()
        page.goto(server_url + "/next/#/visit/v_c")
        wait_ready(page)
        detail = page.request.get(server_url + "/api/ui/visits/v_c").json()
        citation = next(
            c
            for sentence in detail["sentences"]
            for c in sentence["citations"]
            if c["event_id"] == "e17"
        )
        page.get_by_role("button", name="Show evidence e17", exact=True).click()
        output = page.get_by_label("Recorded time", exact=True)
        expect(output).to_contain_text(citation["clock"])
        expect(output).to_contain_text("UTC-08:00")
        expect(output).to_contain_text("Nov 2, 2026")
    finally:
        context.close()


def test_react_voice_sample_keeps_editable_text_and_server_scope_explanation(
    page: Page, server_url
):
    page.goto(server_url + "/next/#/rules")
    wait_ready(page)
    fixtures = page.request.get(server_url + "/api/voice/fixtures").json()["fixtures"]
    for fixture in fixtures:
        page.get_by_role("button", name=fixture["label"]).click()
        text = page.get_by_role("textbox", name="Rule text")
        expect(text).to_have_value(fixture["transcript"])
        page.get_by_role("button", name="Review rule draft").click()
        draft = page.get_by_role("region", name="Rule draft")
        expect(draft).to_contain_text("does not identify anyone")
        expect(draft).to_contain_text("face, voice or body templates")
        expect(draft.get_by_role("button", name="Confirm rule")).to_be_disabled()
    expect(draft).to_contain_text("can't recognise individuals")
    text.fill("Tell me if anyone except family touches the bin after 9 PM")
    expect(text).to_be_editable()


def test_react_messages_share_draft_and_keep_household_local(page: Page, server_url):
    posts = []
    page.on(
        "request", lambda request: posts.append(request.url) if request.method == "POST" else None
    )
    page.goto(server_url + "/next/")
    wait_ready(page)
    page.get_by_role("button", name="Messages", exact=True).last.click()
    popup = page.get_by_role("dialog", name="Messages")
    popup.get_by_role("tab", name="Household", exact=True).click()
    popup.get_by_role("textbox", name="Message", exact=True).fill("Check the gate")
    popup.get_by_role("button", name="Close messages").click()
    page.get_by_role("button", name="Messages", exact=True).first.click()
    expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value("Check the gate")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("log")).to_contain_text("Check the gate")
    assert not posts
    page.get_by_role("tab", name="Ask your home", exact=True).click()
    page.get_by_role("textbox", name="Message", exact=True).fill("side gate")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("log")).to_contain_text("They touched the side gate")
    expect(page.get_by_role("button", name=re.compile("Open evidence")).first).to_be_visible()
    assert posts == [server_url + "/api/chat/ask"]


def test_react_initial_chat_service_failure_is_visible_and_retry_recovers(page, server_url):
    calls = []

    def fail_once(route):
        calls.append(route.request.url)
        if len(calls) == 1:
            route.fulfill(status=503, json={"detail": "Chat service unavailable."})
        else:
            route.continue_()

    page.route("**/api/ui/chat", fail_once)
    page.goto(server_url + "/next/#/messages")
    wait_ready(page)
    expect(page.get_by_role("alert")).to_have_text("Chat service unavailable.")
    expect(page.get_by_role("heading", name="No threads available")).to_have_count(0)
    page.get_by_role("button", name="Try again").click()
    expect(page.get_by_role("textbox", name="Message", exact=True)).to_be_enabled()
    assert len(calls) == 2


def test_react_chat_citation_opens_its_exact_event_and_camera(page, server_url):
    page.goto(server_url + "/next/#/messages")
    wait_ready(page)
    page.get_by_role("textbox", name="Message", exact=True).fill("side gate")
    page.get_by_role("button", name="Send message").click()
    page.get_by_role("button", name="Open evidence e17", exact=True).click()
    expect(page.get_by_test_id("visit-card")).to_have_attribute("data-visit", "v_c")
    page.wait_for_function("Number(document.querySelector('#evidence-clock')?.value)===15245")
    expect(page.locator(".visit-camera.is-active")).to_contain_text("Left passage")
    expect(page.get_by_label("Recorded time", exact=True)).to_contain_text("6:14:05 PM")


def test_react_generated_video_decodes_seeks_overlays_and_snapshot(page: Page, video_server):
    url, visit_id = video_server
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{url}/next/#/visit/{visit_id}")
    wait_ready(page)
    video = page.locator("video.player-media")
    expect(video).to_have_count(1)
    page.wait_for_function("document.querySelector('video').readyState >= 2")
    assert video.evaluate("v=>v.videoWidth") == 1280
    assert video.evaluate("v=>v.duration") == pytest.approx(4, abs=0.1)
    page.get_by_role("slider", name="Evidence time").fill("1")
    page.wait_for_function("Math.abs(document.querySelector('video').currentTime-1)<0.1")
    assert page.locator("canvas.overlay").evaluate(
        "c=>c.getContext('2d').getImageData(0,0,c.width,c.height).data.some((v,i)=>i%4===3&&v>0)"
    )
    page.get_by_role("button", name="Play evidence timeline").click()
    page.wait_for_function("document.querySelector('video').currentTime>1.3")
    page.get_by_role("button", name="Pause evidence timeline").click()
    page.get_by_role("button", name="Messages", exact=True).last.click()
    page.get_by_role("button", name="Take snapshot", exact=True).click()
    snapshot = page.get_by_role("dialog", name="Camera snapshot")
    expect(snapshot).to_be_visible()
    page.wait_for_function("document.querySelector('.app-snapshot')?.naturalWidth===1280")
    assert not errors, errors


def test_react_point_selection_uses_exported_still_and_explicit_mocked_model_approval(
    page, tmp_path
):
    """FIXTURE: no Meta request; a strict injected FakeBackend returns the mask."""
    from datetime import UTC, datetime

    import respx
    from pydantic import SecretStr

    from tests.integration.test_api import FakeBackend
    from tests.integration.test_cloud_process import generated_session, mock_models
    from vigil.meta.client import MetaClient
    from vigil.pipeline import process_session
    from vigil.store.export import export_session

    settings, _ = generated_session(tmp_path)
    with (
        respx.mock as router,
        MetaClient(
            settings, clock=lambda: datetime(2026, 11, 3, tzinfo=UTC), sleep=lambda _: None
        ) as client,
    ):
        mock_models(router)
        process_session("generated", settings=settings, client=client, confirm=True)
    bundle = export_session("generated", tmp_path / "bundle", settings=settings, synthetic=True)
    settings = settings.model_copy(
        update={"mode": "edge", "owner_token": SecretStr("synthetic-owner-token")}
    )
    backend = FakeBackend()
    app = create_app(settings, bundle_dir=bundle, live_backend=backend)
    assert app.state.live_backend is backend
    with running_app(app) as url:
        page.goto(url + "/next/#/settings")
        wait_ready(page)
        page.get_by_role("tab", name="Owner controls").click()
        page.get_by_role("textbox", name="Owner token").fill("synthetic-owner-token")
        page.get_by_role("button", name="Save owner token").click()
        page.get_by_role("button", name="Select an object", exact=True).click()
        dialog = page.get_by_role("dialog", name="Select an object")
        image = dialog.get_by_role("img", name="Left side exported still")
        expect(image).to_be_visible()
        page.wait_for_function(
            "document.querySelector('.protection-frame img')?.naturalWidth===1280"
        )
        dialog.get_by_role("spinbutton", name="Pixel X").fill("160")
        dialog.get_by_role("spinbutton", name="Pixel Y").fill("600")
        dialog.get_by_role("textbox", name="Object label").fill("Fixture gate")
        dialog.get_by_role("button", name="Request point model").click()
        approval = page.get_by_role("dialog", name="Approve point model request")
        expect(approval).to_contain_text("$0.0025")
        assert backend.calls == []
        approval.get_by_role("button", name="Approve and run").click()
        expect(dialog.get_by_label("Point model mask")).to_be_visible()
        expect(dialog).to_contain_text("Fixture gate")
        expect(dialog).to_contain_text("Added to this server session")
        assert backend.calls == ["protect"]
        dialog.get_by_role("button", name="Close Select an object").click()
        page.get_by_role("button", name="Rules and protected objects", exact=True).click()
        expect(page.get_by_role("heading", name="Fixture gate", exact=True)).to_be_visible()


def test_react_phone_house_toolbar_keeps_every_control_reachable(page, server_url):
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    page.goto(server_url + "/next/")
    wait_ready(page)
    toolbar = page.locator(".house-view .twin-toolbar")
    toolbar.scroll_into_view_if_needed()
    bounds = toolbar.evaluate("""element=>{
      const box=element.getBoundingClientRect();
      return [...element.querySelectorAll('button')].filter(b=>b.getClientRects().length)
        .map(b=>({name:b.getAttribute('aria-label')||b.textContent,
          left:b.getBoundingClientRect().left,right:b.getBoundingClientRect().right,
          parentLeft:box.left,parentRight:box.right}));
    }""")
    assert all(b["left"] >= b["parentLeft"] and b["right"] <= b["parentRight"] for b in bounds), (
        bounds
    )
    page.get_by_role("button", name="Camera and view controls", exact=True).click()
    expect(page.get_by_role("menuitem", name="Zoom in", exact=True)).to_be_visible()
    page.get_by_role("menuitem", name="Zoom in", exact=True).click()
    page.get_by_role("button", name="Camera and view controls", exact=True).click()
    expect(page.get_by_role("menuitem", name="Zoom out", exact=True)).to_be_visible()
    expect(page.get_by_role("menuitem", name="Reset view", exact=True)).to_be_visible()


def test_react_built_motion_tokens_refresh_after_initial_reduced_preference(page, server_url):
    page.emulate_media(reduced_motion="reduce")
    page.goto(server_url + "/next/")
    wait_ready(page)
    view = page.get_by_test_id("house-view")
    expect(view).to_have_attribute("data-motion-seconds", "0")
    canvas = page.get_by_test_id("twin-canvas")
    expect(canvas).to_have_attribute("data-camera-position", re.compile(r".+"))
    before = canvas.get_attribute("data-camera-position")
    page.emulate_media(reduced_motion="no-preference")
    expect(view).to_have_attribute("data-motion-seconds", "0.48")
    expect(view).to_have_attribute("data-pulse-period", "1.6")
    after = canvas.get_attribute("data-camera-position")
    assert (
        sum(
            (float(a) - float(b)) ** 2
            for a, b in zip(before.split(","), after.split(","), strict=True)
        )
        < 1e-10
    )


def test_react_popup_is_opaque_in_ordinary_motion_and_preserves_live_preference_state(
    page, server_url
):
    page.emulate_media(reduced_motion="no-preference")
    page.goto(server_url + "/next/")
    wait_ready(page)
    page.get_by_role("button", name="Messages", exact=True).last.click()
    popup = page.get_by_role("dialog", name="Messages")
    expect(popup).to_be_visible()
    page.wait_for_function(
        "Number(getComputedStyle(document.querySelector('.v-chat-popup')).opacity)>.99",
        timeout=2000,
    )
    field = popup.get_by_role("textbox", name="Message", exact=True)
    field.fill("Keep this draft")
    field.focus()
    element = field.element_handle()
    for preference in ("reduce", "no-preference"):
        page.emulate_media(reduced_motion=preference)
        page.wait_for_function(
            "Number(getComputedStyle(document.querySelector('.v-chat-popup')).opacity)>.99",
            timeout=2000,
        )
        expect(field).to_have_value("Keep this draft")
        expect(field).to_be_focused()
        assert field.evaluate("(e,old)=>e===old", element)


def test_react_home_tabpanel_has_a_visible_keyboard_focus_indicator(page, server_url):
    page.goto(server_url + "/next/")
    wait_ready(page)
    page.get_by_role("tab", name="Overview", exact=True).focus()
    page.keyboard.press("Tab")
    panel = page.locator(".home-view-tabs>.v-tab-panel")
    expect(panel).to_be_focused()
    focus = panel.evaluate("""element=>{
      const style=getComputedStyle(element);
      return {visible:element.matches(':focus-visible'),style:style.outlineStyle,
              width:parseFloat(style.outlineWidth),color:style.outlineColor};
    }""")
    assert focus["visible"]
    assert focus["style"] != "none"
    assert focus["width"] >= 2


def test_react_roving_tablist_remains_visible_if_entry_focus_stays_on_its_wrapper(page, server_url):
    page.goto(server_url + "/next/")
    wait_ready(page)
    page.keyboard.press("Tab")
    tablist = page.get_by_role("tablist", name="House views", exact=True)
    tablist.evaluate("""element=>{
      element.addEventListener('rovingFocusGroup.onEntryFocus',event=>event.preventDefault());
      element.focus();
    }""")
    expect(tablist).to_be_focused()
    focus = tablist.evaluate("""element=>({visible:element.matches(':focus-visible'),
      shadow:getComputedStyle(element).boxShadow})""")
    assert focus["visible"]
    assert "inset" in focus["shadow"]
    assert "2px" in focus["shadow"]
