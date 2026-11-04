"""Local test server and navigation helpers shared by the React browser tests."""

import threading
import time
from contextlib import contextmanager

import uvicorn
from playwright.sync_api import Locator, Page, expect

from tests.e2e.conftest import _free_port, wait_ready

RULE_TEXT = "What should Vigil watch for?"


@contextmanager
def running_app(app):
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("test server did not start")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def sign_in_owner(page: Page, url: str, token: str = "synthetic-owner-token") -> None:
    """Settings -> Owner access: save the owner token for this tab."""
    page.goto(url + "/next/#/settings")
    wait_ready(page)
    page.get_by_role("tab", name="Owner access", exact=True).click()
    page.get_by_role("textbox", name="Owner token").fill(token)
    page.get_by_role("button", name="Save owner token").click()
    expect(page.get_by_text("Active on this browser", exact=True)).to_be_visible()


def open_protection(page: Page) -> None:
    """Rules, visitor windows and protected objects live on the Protection page."""
    page.get_by_role("button", name="Protection", exact=True).first.click()
    expect(page.get_by_role("region", name="Current rules")).to_be_visible()


def open_rule_editor(page: Page) -> Locator:
    """Open the New rule dialog (rule text, suggestions, voice samples, dictation, draft)."""
    page.get_by_role("button", name="New rule", exact=True).first.click()
    dialog = page.get_by_role("dialog", name="New rule", exact=True)
    expect(dialog).to_be_visible()
    return dialog
