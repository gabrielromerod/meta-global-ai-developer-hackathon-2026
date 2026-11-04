"""FIXTURE: React owner controls use the real local API and isolated durable storage."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import UnreachableBackend, wait_ready
from tests.e2e.support import open_protection, running_app, sign_in_owner
from vigil.api.app import create_app
from vigil.settings import Settings

pytestmark = pytest.mark.e2e


def test_owner_controls_disabled_in_sandbox(page: Page, server_url: str):
    page.goto(server_url + "/next/#/settings")
    wait_ready(page)
    page.get_by_role("tab", name="Owner access", exact=True).click()
    expect(page.get_by_role("textbox", name="Owner token")).to_be_disabled()
    expect(page.get_by_role("button", name="Save owner token")).to_be_disabled()
    expect(page.get_by_text("Owner-only on the home box", exact=True)).to_be_visible()
    # Check-in, expected windows and object selection moved to the Protection page.
    open_protection(page)
    expect(page.get_by_role("button", name="I'm outside")).to_be_disabled()
    expect(page.get_by_role("button", name="New expected window")).to_be_disabled()
    expect(page.get_by_role("button", name="Add object", exact=True)).to_be_disabled()
    expect(page.get_by_role("switch")).to_have_count(0)
    visitors = page.get_by_label("Visitor controls", exact=True)
    visitors.get_by_text(re.compile(r"^Past windows")).click()
    recorded = visitors.get_by_role("article", name="deliveries")
    expect(recorded).to_contain_text("Recorded example")
    expect(visitors.get_by_role("button", name="Cancel window")).to_have_count(0)
    page.goto(server_url + "/next/#/visit/v_b")
    wait_ready(page)
    expect(page.get_by_role("button", name="Undo", exact=True)).to_have_count(0)


def test_owner_token_checkin_countdown_and_expected_window_crud(page: Page, tmp_path):
    settings = Settings(
        _env_file=None,
        mode="edge",
        owner_token="synthetic-owner-token",
        data_dir=tmp_path,
        db_path=tmp_path / "owner.sqlite",
        ledger_path=tmp_path / "ledger.sqlite",
        cache_dir=tmp_path / "cache",
        meta_cache_only=True,
    )
    with running_app(create_app(settings, live_backend=UnreachableBackend())) as url:
        sign_in_owner(page, url)
        assert (
            page.evaluate("sessionStorage.getItem('vigil_owner_token')") == "synthetic-owner-token"
        )
        assert page.evaluate("localStorage.getItem('vigil_owner_token')") is None
        open_protection(page)
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
        dialog.get_by_label("Window starts").fill(dates[0])
        dialog.get_by_label("Window ends").fill(dates[1])
        dialog.get_by_label("Window label").fill("Fixture delivery")
        dialog.get_by_label("Window camera").select_option("front_left_duo")
        dialog.get_by_role("button", name="Create expected window").click()
        expect(dialog).not_to_be_visible()
        row = page.get_by_role("article", name="Fixture delivery")
        expect(row).to_contain_text("Scheduled")
        expect(row).to_contain_text("Front left Duo")
        row.get_by_role("button", name="Cancel window").click()
        # A cancelled window moves into the collapsed "Past windows" list.
        past = page.get_by_text(re.compile(r"^Past windows"))
        past.click()
        expect(row).to_contain_text("Cancelled")
        page.reload()
        wait_ready(page)
        past.click()
        expect(page.get_by_role("article", name="Fixture delivery")).to_contain_text("Cancelled")
