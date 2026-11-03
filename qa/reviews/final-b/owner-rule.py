"""FIXTURE: actual local owner rule confirmation against an isolated cache-only app."""

import json
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from tests.e2e.conftest import UnreachableBackend
from tests.e2e.support import running_app
from vigil.api.app import create_app
from vigil.settings import Settings


def main():
    root = Path("data/qa-final-b") / ("owner-rule-" + uuid4().hex[:8])
    root.mkdir(parents=True)
    fixture_owner_secret = "fixture-" + uuid4().hex
    settings = Settings(
        _env_file=None,
        mode="edge",
        MODEL_API_KEY="invalid",
        meta_cache_only=True,
        meta_base_url="http://127.0.0.1:9/v1",
        owner_token=fixture_owner_secret,
        data_dir=root,
        db_path=root / "owner.sqlite",
        ledger_path=root / "ledger.sqlite",
        cache_dir=root / "cache",
    )
    out = Path("qa/screens/9a8ced22/1470x870")
    with (
        running_app(create_app(settings, live_backend=UnreachableBackend())) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1470, "height": 870}, reduced_motion="reduce")
        page.goto(url + "/next/#/settings")
        page.get_by_role("tab", name="Owner controls").click()
        page.get_by_role("textbox", name="Owner token").fill(fixture_owner_secret)
        page.get_by_role("button", name="Save owner token").click()
        expect(page.get_by_text("Owner session active")).to_be_visible()
        page.get_by_role("button", name="Rules and protected objects", exact=True).click()
        sample = page.request.get(url + "/api/voice/fixtures").json()["fixtures"][0]
        page.get_by_role("textbox", name="Rule text").fill(sample["transcript"])
        page.get_by_role("button", name="Review rule draft").click()
        draft = page.get_by_role("region", name="Rule draft")
        expect(draft).to_be_visible()
        page.screenshot(path=str(out / "final-b-rule-draft-before-confirm.png"))
        before = draft.inner_text()
        draft.get_by_role("button", name="Confirm rule").click()
        expect(page.get_by_role("status")).to_contain_text("kept in memory")
        expect(
            page.get_by_role("region", name="Current rules").get_by_role(
                "article", name="Recycling bin after 9 PM (non-household)"
            )
        ).to_contain_text("Active")
        page.screenshot(path=str(out / "final-b-rule-still-draft-after-confirm.png"))
        after = draft.inner_text()
        api_state = page.evaluate("""async()=>await (await fetch('/api/ui/state',{
          headers:{'X-Vigil-Owner':sessionStorage.getItem('vigil_owner_token')}
        })).json()""")
        result = {
            "before": before,
            "after": after,
            "confirm_disabled": draft.get_by_role("button", name="Confirm rule").is_disabled(),
            "server_rules": [
                {"id": row["id"], "state": row["state"]} for row in api_state["rules"]
            ],
        }
        print(json.dumps(result))
        (out / "final-b-owner-rule.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (out / "final-b-owner-rule-fixture.json").write_text(
            json.dumps({"evidence": {"kind": "fixture"}, "state": api_state}, indent=2),
            encoding="utf-8",
        )
        browser.close()


if __name__ == "__main__":
    main()
