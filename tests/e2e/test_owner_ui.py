"""FIXTURE: owner controls hit the real local API, with synthetic bundle and token."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import UnreachableBackend, wait_ready
from tests.e2e.support import running_app
from vigil.api.app import create_app
from vigil.settings import Settings

pytestmark = pytest.mark.e2e


def test_owner_controls_disabled_in_sandbox(page: Page, server_url: str):
    page.goto(server_url)
    wait_ready(page)
    expect(page.get_by_test_id("owner-panel")).to_contain_text("Owner-only on the home box")
    expect(page.locator("#owner-checkin")).to_be_disabled()
    expect(page.locator("#owner-window-create")).to_be_disabled()
    expect(page.locator("#owner-token-open")).to_be_disabled()
    expect(page.locator("#owner-windows")).to_contain_text("deliveries")
    expect(page.locator("#owner-windows")).to_contain_text("Recorded example")
    page.goto(f"{server_url}/#/visit/v_b")
    wait_ready(page)
    expect(page.locator("[data-undo]")).to_have_count(0)


def test_owner_token_checkin_countdown_and_expected_window_crud(page: Page, tmp_path):
    settings = Settings(
        _env_file=None,
        mode="edge",
        owner_token="synthetic-owner-token",
        db_path=tmp_path / "owner.sqlite",
        meta_cache_only=True,
    )
    app = create_app(settings, live_backend=UnreachableBackend())
    with running_app(app) as url:
        page.goto(url)
        wait_ready(page)
        page.locator("#owner-token-open").click()
        page.locator("#owner-token-input").fill("synthetic-owner-token")
        page.locator("#owner-token-save").click()
        assert (
            page.evaluate("sessionStorage.getItem('vigil_owner_token')") == "synthetic-owner-token"
        )
        assert page.evaluate("localStorage.getItem('vigil_owner_token')") is None
        page.locator("#owner-checkin").click()
        expect(page.locator("#owner-countdown")).to_contain_text("s remaining")
        remaining = int(page.locator("#owner-countdown").inner_text().split()[0])
        assert 118 <= remaining <= 120
        dates = page.evaluate("""() => {
          const local = d => new Date(d.getTime() - d.getTimezoneOffset() * 60000)
            .toISOString().slice(0, 16);
          return [local(new Date(Date.now() + 600000)), local(new Date(Date.now() + 1200000))];
        }""")
        page.locator("#owner-window-start").fill(dates[0])
        page.locator("#owner-window-end").fill(dates[1])
        page.locator("#owner-window-label").fill("Fixture delivery")
        page.locator("#owner-window-camera").select_option("front")
        page.locator("#owner-window-create").click()
        row = page.locator(".owner-window").filter(has_text="Fixture delivery")
        expect(row).to_contain_text("scheduled")
        row.get_by_role("button", name="Cancel").click()
        expect(row).to_contain_text("cancelled")
        page.reload()
        wait_ready(page)
        expect(page.locator("#owner-windows")).to_contain_text("Fixture delivery")
        expect(page.locator("#owner-windows")).to_contain_text("cancelled")
