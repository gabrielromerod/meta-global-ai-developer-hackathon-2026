"""FIXTURE: real React/API behavior with cached ledgers and generated media only."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import wait_ready
from tests.e2e.test_real_video import video_server  # noqa: F401

pytestmark = pytest.mark.e2e


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
