"""FIXTURE: independent mechanical cutover smoke; no vendor/hardware actions."""

import hashlib
import json
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path("qa/screens/060c583c")
BASE = "http://127.0.0.1:8119"
result = {
    "evidence": {"kind": "fixture"},
    "root_commit": "060c583c0e11cd2cf8fdc0bfd8e6a16b18012f61",
    "composed_source": "73cdef6f1540a4d5132dcb38d4dd78331c374bdd",
    "viewports": [],
}
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    probe = browser.new_page()
    root = probe.request.get(BASE + "/")
    alias = probe.request.get(BASE + "/next/")
    assert root.status == 200
    assert alias.status == 200
    assert root.body() == alias.body()
    result["root_alias_html_sha256"] = hashlib.sha256(root.body()).hexdigest()
    assets = re.findall(r'(?:src|href)="(/next/assets/[^"]+)"', root.text())
    assert assets
    assert all(probe.request.get(BASE + a).status == 200 for a in assets)
    result["assets"] = assets
    for path in [
        "/app.js",
        "/cards.js",
        "/voice.js",
        "/styles.css",
        "/twin/vendor/three/build/three.module.min.js",
        "/calibrate/",
        "/calibrate/calibrate.js",
        "/calibrate/styles.css",
    ]:
        assert probe.request.get(BASE + path).status == 404, path
    state = probe.request.get(BASE + "/api/ui/state").json()
    assert state["evidence"]["kind"] == "fixture"
    result["state"] = state
    probe.close()
    for w, h in [(1470, 870), (390, 844)]:
        context = browser.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
        page.on("requestfailed", lambda r, errors=errors: errors.append(r.url))
        page.on(
            "response",
            lambda r, errors=errors: (
                errors.append(f"{r.status} {r.url}") if r.status >= 400 else None
            ),
        )
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_function("document.body.dataset.ready==='1'")
        page.wait_for_function("document.querySelector('.twin-canvas')?.dataset.cameraPosition")
        expect(page.locator(".v-app-shell")).to_be_visible()
        expect(page.get_by_role("region", name="Same action, different context")).to_contain_text(
            "Normal"
        )
        folder = ROOT / f"{w}x{h}"
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / "final-b-root.png"))
        page.goto(BASE + "/#/visit/v_c", wait_until="networkidle")
        expect(page.get_by_test_id("visit-card")).to_have_attribute("data-visit", "v_c")
        expect(page.get_by_text("Needs your attention", exact=True)).to_be_visible()
        assert not errors, errors
        result["viewports"].append(
            {"viewport": f"{w}x{h}", "root_home": True, "root_visit": True, "errors": errors}
        )
        context.close()
    browser.close()
(ROOT / "final-b-cutover.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("Root/preview identical; assets 200; legacy/calibration sandbox 404; browser sizes clean")
