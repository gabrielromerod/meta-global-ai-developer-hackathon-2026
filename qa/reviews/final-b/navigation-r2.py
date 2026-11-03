"""FIXTURE: actual desktop/mobile navigation and notification actions."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path("qa/screens/c965bedf")
items = [
    ("Home", "home"),
    ("Attention", "attention"),
    ("Clips", "clips"),
    ("Media library", "media"),
    ("Messages", "messages"),
    ("Rules and protected objects", "rules"),
    ("Benchmark", "benchmark"),
    ("Settings", "settings"),
]
result = {"evidence": {"kind": "fixture"}, "actions": []}
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, height in [(1470, 870), (390, 844)]:
        for theme in ["dark", "light"]:
            context = browser.new_context(
                viewport={"width": width, "height": height}, reduced_motion="reduce"
            )
            context.add_init_script(f"localStorage.setItem('vigil_theme','{theme}')")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            page.goto("http://127.0.0.1:8119/next/")
            for label, route in items:
                if width == 390:
                    page.get_by_role("button", name="Open navigation", exact=True).click()
                    nav = page.get_by_role("navigation", name="Mobile navigation")
                else:
                    nav = page.get_by_role("navigation", name="Main navigation")
                nav.get_by_role("button", name=label, exact=True).click()
                page.wait_for_url("**/#/" + route)
                page.wait_for_load_state("networkidle")
                expect(page.get_by_role("main")).to_have_attribute("aria-label", label)
                page.screenshot(
                    path=str(ROOT / f"{width}x{height}" / f"final-b-r2-nav-{theme}-{route}.png")
                )
                result["actions"].append(
                    {"viewport": f"{width}x{height}", "theme": theme, "navigation": route}
                )
            notifications = page.request.get("http://127.0.0.1:8119/api/ui/state").json()[
                "notifications"
            ]
            for index in range(5):
                target = notifications[index]["visit_id"]
                page.locator(".v-notification-trigger").click()
                page.locator(".v-notification-item").nth(index).click()
                page.wait_for_url("**/#/visit/" + target)
                page.wait_for_load_state("networkidle")
                page.locator(".visit-workspace").wait_for()
                expected_id = target
                expect(page.get_by_test_id("visit-card")).to_have_attribute(
                    "data-visit", expected_id
                )
                page.wait_for_function(
                    "document.querySelector('.twin-canvas')?.dataset.cameraPosition"
                )
                expect(
                    page.get_by_role("heading", name="Visit evidence", exact=True)
                ).to_be_visible()
                page.screenshot(
                    path=str(
                        ROOT / f"{width}x{height}" / f"final-b-r2-notification-{theme}-{index}.png"
                    )
                )
                result["actions"].append(
                    {
                        "viewport": f"{width}x{height}",
                        "theme": theme,
                        "notification": index,
                        "hash": page.evaluate("location.hash"),
                    }
                )
            page.locator(".v-notification-trigger").click()
            page.get_by_role("menuitem", name="Open Attention", exact=True).click()
            page.wait_for_url("**/#/attention")
            assert not errors, errors
            context.close()
    browser.close()
(ROOT / "final-b-r2-navigation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(len(result["actions"]), "actual navigation/notification actions; no page errors")
