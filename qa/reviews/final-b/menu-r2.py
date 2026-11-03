import json
from pathlib import Path

from playwright.sync_api import sync_playwright

out = Path("qa/screens/c965bedf/390x844")
result = {"evidence": {"kind": "fixture"}, "menus": []}
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for theme in ["dark", "light"]:
        context = browser.new_context(
            viewport={"width": 390, "height": 844}, reduced_motion="reduce"
        )
        context.add_init_script(f"localStorage.setItem('vigil_theme','{theme}')")
        page = context.new_page()
        page.goto("http://127.0.0.1:8119/next/")
        trigger = page.get_by_role("button", name="Camera and view controls", exact=True)
        trigger.click()
        menu = page.get_by_role("menu")
        page.screenshot(path=str(out / f"final-b-r2-menu-top-{theme}.png"))
        menu.hover()
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(250)
        page.keyboard.press("End")
        reset = page.get_by_role("menuitem", name="Reset view", exact=True)
        box = reset.bounding_box()
        parent = menu.bounding_box()
        assert box["y"] >= parent["y"]
        assert box["y"] + box["height"] <= parent["y"] + parent["height"]
        assert reset.evaluate("e=>e===document.activeElement")
        result["menus"].append(
            {
                "theme": theme,
                **menu.evaluate(
                    "e=>({top:e.scrollTop,height:e.clientHeight,total:e.scrollHeight,gutter:getComputedStyle(e).scrollbarGutter})"
                ),
            }
        )
        page.screenshot(path=str(out / f"final-b-r2-menu-bottom-{theme}.png"))
        page.keyboard.press("Escape")
        assert trigger.evaluate("e=>e===document.activeElement")
        context.close()
    browser.close()
(out / "final-b-r2-menu-scroll.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result))
