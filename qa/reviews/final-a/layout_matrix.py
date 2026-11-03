"""Independent FIXTURE layout sweep; full interaction review is recorded separately."""

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "qa/screens/9a8ced22"
BASE = "http://127.0.0.1:8118/next/"
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
ROUTES = [
    "home",
    "attention",
    "clips",
    "media",
    "messages",
    "rules",
    "settings",
    "benchmark",
    "visit/v_c",
]


def main():
    start = time.time()
    rows, failures = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in SIZES:
            for theme in ["dark", "light"]:
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                page.on("requestfailed", lambda request, errors=errors: errors.append(request.url))
                page.on(
                    "console",
                    lambda message, errors=errors: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )
                page.on(
                    "response",
                    lambda response, errors=errors: (
                        errors.append(f"HTTP {response.status}: {response.url}")
                        if response.status >= 400
                        else None
                    ),
                )
                page.add_init_script(f"localStorage.setItem('vigil_theme','{theme}')")
                for route in ROUTES:
                    page.goto(BASE + "#/" + route)
                    page.wait_for_function("document.body.dataset.ready==='1'")
                    page.wait_for_function("""() => {
                      const element=document.querySelector('.v-motion-view');
                      return element && Math.abs(new DOMMatrixReadOnly(
                        getComputedStyle(element).transform).m42)<.01;
                    }""")
                    if route in {"home", "visit/v_c"}:
                        page.wait_for_function(
                            "document.querySelector('[data-camera-y]')?.dataset.cameraY"
                        )
                    page.evaluate("document.fonts.ready")
                    geometry = page.evaluate("""() => ({
                      width:innerWidth,height:innerHeight,
                      scrollWidth:document.documentElement.scrollWidth,
                      scrollHeight:document.documentElement.scrollHeight,
                      canvasHeight:document.querySelector('.house-view canvas')
                        ?.getBoundingClientRect().height,
                      verdicts:[...document.querySelectorAll('.v-verdict')].every(
                        element=>element.querySelector('svg')&&element.innerText.trim())
                    })""")
                    relative = f"{width}x{height}/final-a-{theme}-{route.replace('/', '-')}.png"
                    path = OUT / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(path), full_page=width == 390)
                    row = {
                        "viewport": [width, height],
                        "theme": theme,
                        "route": route,
                        "screenshot": relative,
                        **geometry,
                    }
                    rows.append(row)
                    if (geometry["width"], geometry["height"]) != (width, height):
                        failures.append({**row, "reason": "wrong viewport"})
                    if geometry["scrollWidth"] > width or (
                        width > 640 and geometry["scrollHeight"] > height
                    ):
                        failures.append({**row, "reason": "document overflow"})
                    if not geometry["verdicts"]:
                        failures.append({**row, "reason": "verdict missing icon or word"})
                    if (
                        width > 640
                        and geometry["canvasHeight"] is not None
                        and geometry["canvasHeight"] < 180
                    ):
                        failures.append({**row, "reason": "scene below 180px"})
                failures.extend(
                    {"viewport": [width, height], "theme": theme, "reason": error}
                    for error in errors
                )
                context.close()
        browser.close()
    result = {
        "source": "9a8ced22",
        "start": start,
        "seconds": time.time() - start,
        "rows": rows,
        "failures": failures,
    }
    (OUT / "final-a-layout.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Independent layout: {len(rows)} states; {len(failures)} failures")
    for failure in failures:
        print(json.dumps(failure))


if __name__ == "__main__":
    main()
