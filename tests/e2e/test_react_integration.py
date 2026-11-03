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
