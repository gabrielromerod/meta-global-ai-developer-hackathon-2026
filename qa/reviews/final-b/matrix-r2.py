"""FIXTURE: independent API-backed full-app browser matrix. No live model actions."""

import json
import os
from datetime import datetime
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8119"
OUT = Path("qa/screens/c965bedf")
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
ROUTES = ["home", "attention", "clips", "media", "messages", "rules", "benchmark", "settings"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results, failures, fixture_states, network = [], [], [], []
    if os.environ.get("FINAL_B_RESUME"):
        previous = json.loads((OUT / "final-b-matrix.json").read_text(encoding="utf-8"))
        done = {
            (f"{w}x{h}", theme)
            for w, h in SIZES[: int(os.environ.get("FINAL_B_START", "0"))]
            for theme in ("dark", "light")
        }
        results = [row for row in previous["results"] if (row["case"], row["theme"]) in done]
        fixture_states = json.loads(
            (OUT / "final-b-fixture-api-states.json").read_text(encoding="utf-8")
        )["states"]
        network = previous["writes"]
    started = datetime.now().astimezone().isoformat()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in SIZES[int(os.environ.get("FINAL_B_START", "0")) :]:
            for theme in ("dark", "light"):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_init_script(f"localStorage.setItem('vigil_theme','{theme}')")
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message, errors=errors: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )
                page.on("requestfailed", lambda request, errors=errors: errors.append(request.url))
                page.on(
                    "response",
                    lambda response, errors=errors: (
                        errors.append(f"HTTP {response.status}: {response.url}")
                        if response.status >= 400
                        else None
                    ),
                )
                page.on(
                    "request",
                    lambda request: (
                        network.append({"url": request.url, "method": request.method})
                        if request.method != "GET"
                        else None
                    ),
                )
                counter = 0
                case = f"{width}x{height}"
                folder = OUT / case
                folder.mkdir(exist_ok=True)

                def capture(
                    name,
                    page=page,
                    theme=theme,
                    folder=folder,
                    width=width,
                    height=height,
                    case=case,
                ):
                    nonlocal counter
                    counter += 1
                    filename = f"final-b-r2-{theme}-{counter:03d}-{name}.png"
                    page.screenshot(path=str(folder / filename), full_page=False)
                    bounds = page.evaluate("""() => ({width:innerWidth,height:innerHeight,
                      scrollWidth:document.documentElement.scrollWidth,
                      scrollHeight:document.documentElement.scrollHeight})""")
                    row = {
                        "case": case,
                        "theme": theme,
                        "state": name,
                        "file": f"{case}/{filename}",
                        **bounds,
                    }
                    results.append(row)
                    if bounds["width"] != width or bounds["height"] != height:
                        failures.append({**row, "failure": "wrong viewport"})
                    if bounds["scrollWidth"] > width or (
                        width > 640 and bounds["scrollHeight"] > height
                    ):
                        failures.append({**row, "failure": "document overflow"})

                def go(route, page=page):
                    page.goto(BASE + "/next/#/" + route, wait_until="networkidle")
                    page.wait_for_function("document.body.dataset.ready==='1'")
                    page.evaluate("document.fonts.ready")
                    if route == "home" or route.startswith("visit/"):
                        page.wait_for_function(
                            "document.querySelector('.twin-canvas')?.dataset.cameraY"
                        )
                    fixture_states.append(page.request.get(BASE + "/api/ui/state").json())

                def hover_controls(label, page=page, capture=capture, case=case, theme=theme):
                    controls = page.locator(
                        "button,a,input,textarea,select,summary,[role=tab],[role=combobox]"
                    )
                    for index in range(controls.count()):
                        control = controls.nth(index)
                        if not control.is_visible() or control.evaluate(
                            "e=>Boolean(e.closest('[aria-hidden=true]'))"
                        ):
                            continue
                        try:
                            control.hover(timeout=1000)
                            capture(f"{label}-hover-{index:02d}")
                        except Exception as error:
                            failures.append(
                                {
                                    "case": case,
                                    "theme": theme,
                                    "state": label,
                                    "failure": "hover inaccessible",
                                    "index": index,
                                    "detail": str(error)[:350],
                                }
                            )

                def scroll_panels(label, page=page, capture=capture):
                    panels = page.locator("*").evaluate_all("""els=>els.filter(e=>{
                      const s=getComputedStyle(e);
                      return /auto|scroll/.test(s.overflowY)&&e.scrollHeight>e.clientHeight+1;
                    }).map((e,i)=>{e.dataset.finalBScroll=String(i);
                      return {id:String(i),gutter:getComputedStyle(e).scrollbarGutter}})""")
                    for panel in panels:
                        element = page.locator(f'[data-final-b-scroll="{panel["id"]}"]')
                        if not element.is_visible():
                            continue
                        element.evaluate("e=>{e.scrollTop=0}")
                        capture(f"{label}-panel-{panel['id']}-top")
                        element.evaluate("e=>{e.scrollTop=e.scrollHeight}")
                        capture(f"{label}-panel-{panel['id']}-bottom")

                try:
                    for route in ROUTES:
                        go(route)
                        capture(route)
                        hover_controls(route)
                        scroll_panels(route)
                        if route == "home":
                            comparison = page.get_by_role(
                                "region", name="Same action, different context"
                            )
                            expect(comparison).to_contain_text("Normal")
                            expect(comparison).to_contain_text("Needs attention")
                            tabs = page.locator(".home-view-tabs>.v-tab-list [role=tab]")
                            for index in range(tabs.count()):
                                tabs.nth(index).click()
                                capture(f"home-view-{index}")
                            page.get_by_role("tab", name="Overview", exact=True).click()
                            for preset in ("Front", "Left passage", "Backyard", "Top-down"):
                                page.locator(".house-view").get_by_role(
                                    "tab", name=preset, exact=True
                                ).click()
                                page.wait_for_timeout(500)
                                capture("preset-" + preset.replace(" ", "-"))
                            for name in (
                                "Zoom in",
                                "Zoom out",
                                "Toggle camera coverage",
                                "Reset view",
                            ):
                                control = page.get_by_role("button", name=name, exact=True)
                                if control.is_visible():
                                    control.click()
                                else:
                                    page.get_by_role(
                                        "button", name="Camera and view controls", exact=True
                                    ).click()
                                    capture("view-controls-menu")
                                    role = (
                                        "menuitemcheckbox"
                                        if name == "Toggle camera coverage"
                                        else "menuitem"
                                    )
                                    item_name = (
                                        "Camera coverage" if role == "menuitemcheckbox" else name
                                    )
                                    page.get_by_role(role, name=item_name, exact=True).click()
                                capture(name.replace(" ", "-"))
                            for index in range(7):
                                menu = page.get_by_role(
                                    "button", name="Camera and view controls", exact=True
                                )
                                if menu.is_visible():
                                    menu.click()
                                    capture(f"camera-menu-{index}")
                                    option = page.get_by_role("menuitemradio").nth(index)
                                    option.hover()
                                    capture(f"camera-menu-option-{index}")
                                    option.click()
                                else:
                                    page.locator(".twin-camera-list button").nth(index).click()
                                capture(f"camera-selected-{index}")
                            canvas = page.locator(".twin-canvas")
                            canvas.scroll_into_view_if_needed()
                            box = canvas.bounding_box()
                            start = None
                            for fx, fy in ((0.08, 0.3), (0.9, 0.3), (0.08, 0.7), (0.9, 0.7)):
                                sx, sy = box["x"] + box["width"] * fx, box["y"] + box["height"] * fy
                                if (
                                    page.evaluate(
                                        "p=>document.elementFromPoint(p.x,p.y)?.tagName",
                                        {"x": sx, "y": sy},
                                    )
                                    == "CANVAS"
                                ):
                                    start = (sx, sy)
                                    break
                            if start is None:
                                raise RuntimeError("No unobstructed canvas drag surface")
                            before_pose = canvas.get_attribute("data-camera-position")
                            page.mouse.move(*start)
                            page.mouse.down()
                            page.mouse.move(
                                start[0], min(height - 4, box["y"] + box["height"] * 0.95), steps=15
                            )
                            page.mouse.up()
                            page.wait_for_timeout(150)
                            if canvas.get_attribute("data-camera-position") == before_pose:
                                raise RuntimeError("Drag did not move the actual camera")
                            camera_y = float(canvas.get_attribute("data-camera-y"))
                            if camera_y <= 0:
                                failures.append(
                                    {
                                        "case": case,
                                        "theme": theme,
                                        "failure": "camera below ground",
                                        "y": camera_y,
                                    }
                                )
                            capture("dragged-down")
                            page.emulate_media(reduced_motion="reduce")
                            capture("reduced-motion")
                            page.emulate_media(reduced_motion="no-preference")
                        elif route in {"clips", "media"}:
                            for label in ("Camera", "Verdict"):
                                combo = page.get_by_role("combobox", name=label, exact=True)
                                combo.click()
                                options = page.get_by_role("option")
                                count = options.count()
                                for index in range(count):
                                    options.nth(index).hover()
                                    capture(f"{route}-{label.lower()}-option-{index}")
                                page.keyboard.press("Escape")
                            page.get_by_role("searchbox", name="Search evidence").fill("gate")
                            page.get_by_role("button", name="Apply filters").click()
                            expect(page.get_by_role("dialog", name="Media search")).to_be_visible()
                            capture(route + "-server-search")
                            page.get_by_role("button", name="Close Media search").click()
                            page.get_by_role("button", name="Clear filters").click()
                            expect(page.get_by_role("dialog", name="Media search")).to_be_visible()
                            page.get_by_role("button", name="Close Media search").click()
                            if route == "media":
                                page.get_by_role("button", name="Time range").click()
                                capture("time-range")
                                page.get_by_label("From (local time)").fill("2026-11-02T18:00")
                                page.get_by_label("Until (local time)").fill("2026-11-02T18:30")
                                capture("time-range-set")
                                page.get_by_role("button", name="Done", exact=True).click()
                        elif route == "settings":
                            for label in ("Cameras", "Privacy", "Household", "Owner controls"):
                                page.get_by_role("tab", name=label, exact=True).click()
                                capture("settings-" + label.replace(" ", "-"))
                                scroll_panels("settings-" + label.replace(" ", "-"))
                            expect(
                                page.get_by_role("button", name="Select an object")
                            ).to_be_disabled()
                        elif route == "rules":
                            samples = page.request.get(BASE + "/api/voice/fixtures").json()[
                                "fixtures"
                            ]
                            for index, sample in enumerate(samples):
                                page.get_by_role("button", name=sample["label"]).click()
                                expect(page.get_by_role("textbox", name="Rule text")).to_have_value(
                                    sample["transcript"]
                                )
                                page.get_by_role("button", name="Review rule draft").click()
                                expect(
                                    page.get_by_role("region", name="Rule draft")
                                ).to_be_visible()
                                capture(f"voice-draft-{index}")
                            page.get_by_role("button", name="Record a voice rule").click()
                            capture("voice-dialog-not-recording")
                            page.get_by_role("button", name="Close Voice rule").click()
                        elif route == "messages":
                            page.get_by_role("tab", name="Household", exact=True).click()
                            page.get_by_role("textbox", name="Message", exact=True).fill(
                                "Fixture household note"
                            )
                            page.get_by_role("button", name="Send message").click()
                            capture("household-local-note")
                            page.get_by_role("button", name="Share options").click()
                            capture("message-share-menu")
                            page.get_by_role("menuitem", name="Share a clip", exact=True).click()
                            capture("share-clip-dialog")
                            page.get_by_role("dialog", name="Share a clip").get_by_role(
                                "button"
                            ).nth(1).click()
                            page.get_by_role("tab", name="Ask your home", exact=True).click()
                            page.get_by_role("textbox", name="Message", exact=True).fill(
                                "side gate"
                            )
                            page.get_by_role("button", name="Send message").click()
                            expect(page.get_by_role("log")).to_contain_text(
                                "They touched the side gate"
                            )
                            capture("assistant-cited-answer")
                    go("visit/v_c")
                    capture("visit-c")
                    hover_controls("visit")
                    for citation in page.locator(".visit-citation").all():
                        citation.click()
                        capture("citation-" + citation.get_attribute("aria-label").split()[-1])
                    page.get_by_role("slider", name="Evidence time").fill("15280")
                    capture("explicit-gap")
                    page.locator(".visit-trace summary").click()
                    page.get_by_role("button", name="Rebuild story from cache").click()
                    expect(
                        page.get_by_role("status").filter(has_text="Recorded story")
                    ).to_be_visible()
                    capture("cached-rebuild")
                    page.get_by_role("button", name="This was expected").click()
                    expect(
                        page.get_by_role("status").filter(has_text="never changes a verdict")
                    ).to_be_visible()
                    capture("feedback")
                    scroll_panels("visit")
                    go("home")
                    trigger = page.locator(".app-messages-pill")
                    trigger.click()
                    popup = page.get_by_role("dialog", name="Messages")
                    page.wait_for_function(
                        "Number(getComputedStyle(document.querySelector('.v-chat-popup')).opacity)>.99"
                    )
                    popup.get_by_role("textbox", name="Message", exact=True).fill(
                        "Preserved fixture draft"
                    )
                    capture("floating-messages-draft")
                    page.keyboard.press("Escape")
                    expect(trigger).to_be_focused()
                    bell = page.get_by_role("button", name="Notifications, 5 unread")
                    if bell.count() == 0:
                        bell = page.locator(".v-notification-trigger")
                    bell.click()
                    capture("notifications")
                    for index in range(page.locator(".v-notification-item").count()):
                        page.locator(".v-notification-item").nth(index).hover()
                        capture(f"notification-hover-{index}")
                    page.keyboard.press("Escape")
                    expect(bell).to_be_focused()
                    page.keyboard.press("Tab")
                    seen = set()
                    for index in range(100):
                        active = page.evaluate("""() => {
                          const e=document.activeElement,s=getComputedStyle(e);return {
                            tag:e.tagName,name:e.getAttribute('aria-label')||e.textContent.slice(0,80),
                            outline:s.outlineStyle,outlineWidth:s.outlineWidth,shadow:s.boxShadow
                          }}""")
                        signature = (active["tag"], active["name"])
                        if signature in seen:
                            break
                        seen.add(signature)
                        capture(f"keyboard-{index}")
                        page.keyboard.press("Tab")
                    if errors:
                        failures.append(
                            {
                                "case": case,
                                "theme": theme,
                                "failure": "console/network",
                                "errors": errors,
                            }
                        )
                except Exception as error:
                    failures.append(
                        {
                            "case": case,
                            "theme": theme,
                            "failure": "review harness/action",
                            "detail": str(error)[:1000],
                        }
                    )
                    capture("action-failure")
                finally:
                    context.close()
                    record = {
                        "source": "c965bedfd1649bc781e0ae211bd7848885f51b1f",
                        "started": started,
                        "results": results,
                        "failures": failures,
                        "writes": network,
                    }
                    (OUT / "final-b-matrix.json").write_text(
                        json.dumps(record, indent=2), encoding="utf-8"
                    )
                    (OUT / "final-b-fixture-api-states.json").write_text(
                        json.dumps(
                            {"evidence": {"kind": "fixture"}, "states": fixture_states}, indent=2
                        ),
                        encoding="utf-8",
                    )
                    print(
                        f"{case} {theme}: {counter} captures, "
                        f"{len(failures)} accumulated findings/harness checks",
                        flush=True,
                    )
        browser.close()


if __name__ == "__main__":
    main()
