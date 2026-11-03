"""FIXTURE: integrated API-backed React layout smoke at the owner's CSS sizes."""

import json
import os
import subprocess
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    os.environ.get("QA_SHA")
    or subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
)
BASE = os.environ.get("QA_BASE_URL", "http://127.0.0.1:8000")
SIZES = [
    (1470, 870),
    (1512, 895),
    (1728, 1030),
    (1920, 960),
    (1536, 730),
    (1280, 600),
    (1366, 650),
    (1024, 768),
    (1180, 820),
    (2560, 1000),
    (390, 844),
]
PAGES = ["home", "visit/v_c", "rules", "settings", "media", "messages"]


def main():
    out = ROOT / "qa/screens" / SOURCE
    out.mkdir(parents=True, exist_ok=True)
    response = httpx.get(BASE + "/api/ui/state", timeout=5)
    response.raise_for_status()
    (out / "actual-state.json").write_bytes(response.content)
    failures, rows = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in SIZES:
            for theme in ("dark", "light"):
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                page.on("requestfailed", lambda request, errors=errors: errors.append(request.url))
                page.on(
                    "response",
                    lambda response, errors=errors: (
                        errors.append(f"HTTP {response.status}: {response.url}")
                        if response.status >= 400
                        else None
                    ),
                )
                page.add_init_script(f"localStorage.setItem('vigil_theme', '{theme}')")
                for route in PAGES:
                    page.goto(BASE + "/#/" + route)
                    page.wait_for_function("document.body.dataset.ready==='1'")
                    if route in {"home", "visit/v_c"}:
                        page.locator(".house-view canvas").wait_for()
                        page.wait_for_function(
                            "document.querySelector('.house-view [data-camera-y]')?.dataset.cameraY"
                        )
                    page.evaluate("document.fonts.ready")
                    measurements = page.evaluate("""() => ({
                        width:innerWidth,height:innerHeight,
                        scrollWidth:document.documentElement.scrollWidth,
                        scrollHeight:document.documentElement.scrollHeight,
                        canvasHeight:document.querySelector('.house-view canvas')
                          ?.getBoundingClientRect().height
                    })""")
                    filename = f"{width}x{height}/integration-{theme}-{route.replace('/', '-')}.png"
                    (out / filename).parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(out / filename), full_page=width <= 640)
                    row = {"route": route, "theme": theme, "screenshot": filename, **measurements}
                    rows.append(row)
                    if measurements["scrollWidth"] > width:
                        failures.append({**row, "failure": "horizontal document overflow"})
                    if width > 640 and measurements["scrollHeight"] > height:
                        failures.append({**row, "failure": "desktop document scroll"})
                    if (
                        width > 640
                        and route in {"home", "visit/v_c"}
                        and measurements["canvasHeight"] < 180
                    ):
                        failures.append({**row, "failure": "scene below 180 px"})
                if errors:
                    failures.append({"viewport": [width, height], "theme": theme, "errors": errors})
                context.close()
        browser.close()
    (out / "integration-layout.json").write_text(
        json.dumps({"source": SOURCE, "rows": rows, "failures": failures}, indent=2),
        encoding="utf-8",
    )
    print(f"FIXTURE integrated layout: {len(rows)} states, {len(failures)} failures")
    for failure in failures:
        print(json.dumps(failure))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
