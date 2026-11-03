"""Read-only FIXTURE acceptance of the mechanical React root cutover."""

import hashlib
import json
import re
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8198"
ROOT = Path(__file__).resolve().parents[3]
with httpx.Client(base_url=BASE, follow_redirects=True) as client:
    root = client.get("/")
    preview = client.get("/next/")
    assert root.status_code == 200
    assert root.content == preview.content
    assets = re.findall(r'(?:src|href)="(/next/assets/[^\"]+)"', root.text)
    assert assets
    records = {}
    for asset in assets:
        response = client.get(asset)
        assert response.status_code == 200
        records[asset] = hashlib.sha256(response.content).hexdigest()
    paths = ["/app.js", "/owner.js", "/twin/viewer.js", "/vendor/preact.module.js"]
    legacy = {path: client.get(path).status_code for path in paths}
    assert all(status == 404 for status in legacy.values())
    assert client.get("/calibrate/").status_code == 404
    assert client.get("/api/ui/state").status_code == 200
    assert not (ROOT / "web").exists()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1470, "height": 870})
    errors = []
    failed = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("requestfailed", lambda request: failed.append(request.url))
    page.goto(BASE + "/")
    page.wait_for_function("document.body.dataset.ready === '1'")
    expect(page.locator(".v-app-shell")).to_be_visible()
    expect(page.get_by_text("Same action, different context", exact=True)).to_be_visible()
    page.goto(BASE + "/#/visit/v_c")
    expect(page.get_by_text("Needs your attention", exact=True).first).to_be_visible()
    expect(page.locator(".house-view")).to_be_visible()
    assert not errors
    assert not failed
    browser.close()

report = {
    "evidence": {"kind": "fixture"},
    "root_commit": "060c583c0e11cd2cf8fdc0bfd8e6a16b18012f61",
    "composed_source": "934b6ed7",
    "source": BASE,
    "root_equals_preview": True,
    "assets": records,
    "legacy_status": legacy,
    "sandbox_calibration_status": 404,
    "api_status": 200,
    "console_errors": errors,
    "failed_requests": failed,
    "web_directory_removed": True,
}
(ROOT / "qa/reviews/final-a/cutover-smoke.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
