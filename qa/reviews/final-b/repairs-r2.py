"""FIXTURE: independent integrated repair probes, no camera/model/audio hardware."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8119"
OUT = Path("qa/screens/c965bedf/1470x870")
SOURCE = "c965bedfd1649bc781e0ae211bd7848885f51b1f"


class Factory:
    def mktemp(self, name):
        from uuid import uuid4

        p = Path("data/qa-final-b") / (name + "-r2-" + uuid4().hex[:8])
        p.mkdir(parents=True)
        return p.resolve()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"evidence": {"kind": "fixture"}, "source": SOURCE}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1470, "height": 870}, reduced_motion="reduce"
        )
        page = context.new_page()
        page.goto(BASE + "/next/")
        page.wait_for_function("document.querySelector('.house-view')?.dataset.motionSeconds==='0'")
        canvas = page.locator(".twin-canvas")
        page.wait_for_function("document.querySelector('.twin-canvas')?.dataset.cameraPosition")
        before = canvas.get_attribute("data-camera-position")
        page.emulate_media(reduced_motion="no-preference")
        expect(page.locator(".house-view")).to_have_attribute("data-motion-seconds", "0.48")
        expect(page.locator(".house-view")).to_have_attribute("data-pulse-period", "1.6")
        assert canvas.get_attribute("data-camera-position") == before
        result["initial_reduced_to_ordinary"] = {
            "before": before,
            "after": canvas.get_attribute("data-camera-position"),
            "duration": 0.48,
            "pulse_period": 1.6,
        }
        for group in ["Front garden", "Left passage", "Backyard", "Porch"]:
            page.locator(".home-view-tabs>.v-tab-list").get_by_role(
                "tab", name=group, exact=True
            ).first.click()
            for preset in ["Front", "Left passage", "Backyard", "Top-down"]:
                tab = page.locator(".house-view").get_by_role("tab", name=preset, exact=True)
                tab.click()
                expect(tab).to_have_attribute("aria-selected", "true")
                page.wait_for_timeout(520)
        page.screenshot(path=str(OUT / "final-b-r2-manual-preset-after-groups.png"))
        result["group_then_manual_presets"] = 16
        page.locator(".app-messages-pill").click()
        popup = page.get_by_role("dialog", name="Messages")
        page.wait_for_function(
            "Number(getComputedStyle(document.querySelector('.v-chat-popup')).opacity)>.99"
        )
        field = popup.get_by_role("textbox", name="Message", exact=True)
        field.fill("Preserved second-review draft")
        field.focus()
        original = field.element_handle()
        popup_states = []
        for pref in ["no-preference", "reduce", "no-preference"]:
            page.emulate_media(reduced_motion=pref)
            page.wait_for_timeout(550)
            expect(field).to_have_value("Preserved second-review draft")
            expect(field).to_be_focused()
            assert field.evaluate("(e,old)=>e===old", original)
            state = popup.evaluate(
                "e=>({opacity:getComputedStyle(e).opacity,transform:getComputedStyle(e).transform})"
            )
            assert float(state["opacity"]) > 0.99
            assert state["transform"] in ("none", "matrix(1, 0, 0, 1, 0, 0)")
            popup_states.append({"preference": pref, **state})
            page.screenshot(path=str(OUT / ("final-b-r2-popup-" + pref + ".png")))
        result["popup"] = popup_states
        page.keyboard.press("Escape")
        expect(page.locator(".app-messages-pill")).to_be_focused()
        context.close()
        # Explicitly injected service failure, followed by real local service recovery.
        page = browser.new_page(viewport={"width": 1470, "height": 870}, reduced_motion="reduce")
        page.route(
            "**/api/ui/chat",
            lambda route: route.fulfill(status=503, json={"detail": "Fixture unavailable"}),
        )
        page.goto(BASE + "/next/#/messages")
        expect(page.get_by_role("heading", name="Messages unavailable")).to_be_visible()
        expect(page.get_by_role("alert")).to_be_visible()
        page.screenshot(path=str(OUT / "final-b-r2-chat-error-retry.png"))
        page.unroute("**/api/ui/chat")
        page.get_by_role("button", name="Try again").click()
        expect(page.get_by_role("tab", name="Ask your home", exact=True)).to_be_visible()
        result["chat_retry_recovered"] = True
        page.get_by_role("textbox", name="Message", exact=True).fill("side gate")
        page.get_by_role("button", name="Send message").click()
        page.get_by_role("button", name="Open evidence e17").click()
        expect(page.get_by_role("slider", name="Evidence time")).to_have_value("15245")
        expect(page.get_by_label("Recorded time", exact=True)).to_contain_text("6:14:05 PM")
        result["citation"] = {
            "event": "e17",
            "clock": page.get_by_role("slider", name="Evidence time").input_value(),
        }
        page.screenshot(path=str(OUT / "final-b-r2-citation-exact-time.png"))
        page.close()
        page = browser.new_page(viewport={"width": 1470, "height": 870}, reduced_motion="reduce")
        page.add_init_script("""(() => {
          window.fixtureMic={requested:0,stopped:0};
          Object.defineProperty(navigator.mediaDevices,'getUserMedia',{configurable:true,value:async()=>{
            window.fixtureMic.requested++;
            return {getTracks:()=>[{stop:()=>window.fixtureMic.stopped++}]};
          }});
          window.AudioContext=class {constructor(){throw new Error('Fixture context failure')}};
        })()""")
        page.goto(BASE + "/next/#/rules")
        page.get_by_role("button", name="Record a voice rule").click()
        page.get_by_role("button", name="Start microphone").click()
        expect(page.get_by_role("alert")).to_be_visible()
        during = page.evaluate("window.fixtureMic")
        assert during == {"requested": 1, "stopped": 1}
        page.screenshot(path=str(OUT / "final-b-r2-microphone-cleanup.png"))
        page.get_by_role("button", name="Close Voice rule").click()
        assert page.evaluate("window.fixtureMic") == during
        result["microphone_cleanup"] = during
        page.close()
        clocks = []
        for zone in ["UTC", "Asia/Tokyo", "America/Los_Angeles"]:
            ctx = browser.new_context(
                timezone_id=zone, viewport={"width": 1470, "height": 870}, reduced_motion="reduce"
            )
            p = ctx.new_page()
            p.goto(BASE + "/next/#/visit/v_c")
            p.get_by_role("button", name="Show evidence e17", exact=True).click()
            text = p.get_by_label("Recorded time", exact=True).inner_text()
            assert all(v in text for v in ["6:14:05 PM", "UTC-08:00", "Nov 2, 2026"]), text
            clocks.append({"viewer": zone, "recorded": text})
            p.screenshot(path=str(OUT / ("final-b-r2-clock-" + zone.replace("/", "-") + ".png")))
            ctx.close()
        result["recorded_clocks"] = clocks
        browser.close()
    (OUT / "final-b-r2-repairs.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
