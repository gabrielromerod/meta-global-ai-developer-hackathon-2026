"""Independent full-control FIXTURE review on the immutable composed R2 source."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
SOURCE = subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], text=True).strip()
OUT = ROOT / "qa/screens" / SOURCE
BASE = os.environ.get("QA_BASE_URL", "http://127.0.0.1:8118")
EDGE = os.environ.get("QA_EDGE_URL", "http://127.0.0.1:8128")
BLOCK = os.environ.get("QA_BLOCK", "all")
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
if os.environ.get("QA_SIZES"):
    SIZES = json.loads(os.environ["QA_SIZES"])


class Review:
    def __init__(self):
        self.rows, self.failures, self.focus, self.proofs = [], [], [], set()
        self.sequence = 0
        self.run_tag = uuid4().hex[:6]
        self.http = httpx.Client()

    def capture(self, label):
        self.sequence += 1
        folder = OUT / f"{self.width}x{self.height}"
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^a-z0-9-]", "-", label.lower())[:46]
        relative = (
            folder.relative_to(OUT) / f"final-a-{BLOCK}-{self.theme}-{self.sequence:04}-{safe}.png"
        )
        self.page.screenshot(path=str(OUT / relative))
        base = EDGE if self.page.url.startswith(EDGE) else BASE
        headers = {}
        if base == EDGE and self.page.evaluate("sessionStorage.getItem('vigil_owner_token')"):
            headers = {"X-Vigil-Owner": "final-a-synthetic-owner-token"}
        data = self.http.get(base + "/api/ui/state", headers=headers).content
        digest = hashlib.sha256(data).hexdigest()[:16]
        proof = OUT / "proofs" / f"api-state-{digest}.json"
        proof.parent.mkdir(exist_ok=True)
        proof.write_bytes(data)
        self.proofs.add(str(proof.relative_to(ROOT)))
        self.rows.append(
            {
                "viewport": [self.width, self.height],
                "theme": self.theme,
                "label": label,
                "screenshot": relative.as_posix(),
                "proof": proof.name,
            }
        )
        self.bounds(label)

    def bounds(self, label):
        values = self.page.evaluate("""() => ({w:innerWidth,h:innerHeight,
          sw:document.documentElement.scrollWidth,sh:document.documentElement.scrollHeight})""")
        assert values["w"] == self.width, values
        assert values["h"] == self.height, values
        assert values["sw"] <= self.width, (label, values)
        if self.width > 640:
            assert values["sh"] <= self.height, (label, values)

    def go(self, route, base=BASE):
        self.page.goto(base + "/next/?review=round2#/" + route)
        self.page.wait_for_function("document.body.dataset.ready==='1'")
        self.page.wait_for_load_state("networkidle")
        self.page.evaluate("document.fonts.ready")
        self.page.wait_for_function("""() => {
          const e=document.querySelector('.v-motion-view');
          return e&&Math.abs(new DOMMatrixReadOnly(getComputedStyle(e).transform).m42)<.01;
        }""")

    def hover(self, label, scope="main"):
        controls = self.page.locator(scope).locator(
            "button,input:not([type=hidden]),select,textarea,summary,[role=tab]"
        )
        for index in range(controls.count()):
            control = controls.nth(index)
            if not control.is_visible() or control.get_attribute("aria-hidden") == "true":
                continue
            control.scroll_into_view_if_needed()
            control.hover()
            delay = (
                800
                if control.get_attribute("data-state") == "closed"
                and not control.get_attribute("aria-haspopup")
                else 140
            )
            self.page.wait_for_timeout(delay)
            self.capture(f"{label}-hover-{index}")

    def scroll(self, label):
        elements = self.page.locator("main *")
        for index in range(elements.count()):
            element = elements.nth(index)
            if not element.is_visible():
                continue
            scrollable = element.evaluate("""e=>e.scrollHeight>e.clientHeight+1&&
              ['auto','scroll'].includes(getComputedStyle(e).overflowY)""")
            if not scrollable:
                continue
            for end in [True, False]:
                element.evaluate(
                    "(e,end)=>e.scrollTo({top:end?e.scrollHeight:0,behavior:'instant'})", end
                )
                self.capture(f"{label}-scroll-{index}-{'bottom' if end else 'top'}")

    def tabs(self, scope, label):
        tabs = self.page.locator(scope).get_by_role("tab")
        for index in range(tabs.count()):
            tab = tabs.nth(index)
            tab.click()
            self.capture(f"{label}-{index}")

    def keyboard(self, label, steps=45):
        self.page.keyboard.press("Tab")
        for step in range(steps):
            self.page.keyboard.press("Tab")
            self.page.evaluate(
                "() => new Promise(resolve=>requestAnimationFrame("
                "()=>requestAnimationFrame(resolve)))"
            )
            self.page.wait_for_function(
                """() => {
              const e=document.activeElement;if(e===document.body)return true;
              const r=e.getBoundingClientRect();
              let left=Math.max(0,r.left),right=Math.min(innerWidth,r.right),
                top=Math.max(0,r.top),bottom=Math.min(innerHeight,r.bottom);
              for(let p=e.parentElement;p;p=p.parentElement){
                const c=getComputedStyle(p),b=p.getBoundingClientRect();
                if(/hidden|auto|scroll|clip/.test(c.overflowY)){
                  top=Math.max(top,b.top);bottom=Math.min(bottom,b.bottom);}
                if(/hidden|auto|scroll|clip/.test(c.overflowX)){
                  left=Math.max(left,b.left);right=Math.min(right,b.right);}
              }
              return right-left>=Math.min(40,r.width)-1&&bottom-top>=Math.min(40,r.height)-1;
            }""",
                timeout=1000,
            )
            item = self.page.evaluate("""() => {
              const e=document.activeElement,s=getComputedStyle(e),r=e.getBoundingClientRect();
              let left=Math.max(0,r.left),right=Math.min(innerWidth,r.right),
                top=Math.max(0,r.top),bottom=Math.min(innerHeight,r.bottom);
              for(let p=e.parentElement;p;p=p.parentElement){
                const c=getComputedStyle(p),b=p.getBoundingClientRect();
                if(/hidden|auto|scroll|clip/.test(c.overflowY)){
                  top=Math.max(top,b.top);bottom=Math.min(bottom,b.bottom);}
                if(/hidden|auto|scroll|clip/.test(c.overflowX)){
                  left=Math.max(left,b.left);right=Math.min(right,b.right);}
              }
              return {tag:e.tagName,role:e.getAttribute('role'),pseudo:e.matches(':focus-visible'),
                label:e.getAttribute('aria-label')||e.textContent?.trim().slice(0,60),
                ring:parseFloat(s.outlineWidth)>0&&s.outlineStyle!=='none',shadow:s.boxShadow,
                visible:right-left>=Math.min(40,r.width)-1&&bottom-top>=Math.min(40,r.height)-1,
                visibleWidth:right-left,visibleHeight:bottom-top,body:e===document.body};
            }""")
            if not item["body"]:
                assert item["visible"], (label, step, item)
                if not (item["ring"] or item["shadow"] != "none"):
                    self.failures.append(
                        {
                            "viewport": [self.width, self.height],
                            "theme": self.theme,
                            "reason": "settled keyboard focus has no indicator",
                            "stage": label,
                            "step": step,
                            "observed": item,
                        }
                    )
                    self.capture(f"{label}-focus-failure-{step}")
            self.focus.append(
                {
                    "viewport": [self.width, self.height],
                    "theme": self.theme,
                    "stage": label,
                    "step": step,
                    **item,
                }
            )
            if step % 9 == 0:
                self.capture(f"{label}-keyboard-{step}")

    def home(self):
        self.go("home")
        self.page.wait_for_function("document.querySelector('[data-camera-y]')?.dataset.cameraY")
        house = self.page.get_by_test_id("house-view")
        assert house.get_attribute("data-reduced-motion") == "true"
        assert float(house.get_attribute("data-motion-seconds")) == 0
        self.page.emulate_media(reduced_motion="no-preference")
        self.page.wait_for_function(
            "document.querySelector('.house-view')?.dataset.reducedMotion==='false'"
        )
        self.page.wait_for_function(
            "Number(document.querySelector('.house-view')?.dataset.motionSeconds)===.48"
        )
        assert float(house.get_attribute("data-pulse-period")) == 1.6
        header = house.evaluate("""e=>{
          const r=e.getBoundingClientRect();
          return [...e.querySelectorAll('.twin-toolbar button')]
            .filter(b=>b.getBoundingClientRect().width&&b.getBoundingClientRect().height)
            .map(b=>({name:b.getAttribute('aria-label')||b.textContent,
              left:b.getBoundingClientRect().left,right:b.getBoundingClientRect().right,
              min:r.left,max:r.right}));
        }""")
        assert all(
            item["left"] >= item["min"] - 1 and item["right"] <= item["max"] + 1 for item in header
        ), header
        self.capture("home-initial")
        self.hover("home")
        self.tabs(".home-view-tabs > .v-tab-list", "home-view")
        outer = self.page.locator(".home-view-tabs > .v-tab-list")
        for area in ["Front garden", "Porch", "Left passage", "Backyard"]:
            outer.get_by_role("tab", name=area, exact=True).first.click()
            for preset in ["Top-down", "Front"]:
                house.get_by_role("tab", name=preset, exact=True).click()
                expect(house.get_by_role("tab", name=preset, exact=True)).to_have_attribute(
                    "aria-selected", "true"
                )
                self.capture("area-preset-" + area + "-" + preset)
        for preset in ["Front", "Left passage", "Backyard", "Top-down"]:
            house.get_by_role("tab", name=preset, exact=True).click()
            self.page.wait_for_timeout(520)
            self.capture("preset-" + preset)
        for camera in self.state["cameras"]:
            menu = house.get_by_role("button", name="Camera and view controls")
            if menu.is_visible():
                menu.click()
                option = self.page.get_by_role("menuitemradio").filter(has_text=camera["name"])
                option.hover()
                self.capture("camera-menu-" + camera["id"])
                option.click()
            else:
                house.locator(".twin-camera-list").get_by_role(
                    "button", name=camera["name"], exact=True
                ).click()
                self.capture("camera-row-" + camera["id"])
        for action in ["Zoom in", "Zoom out", "Reset view"]:
            menu = house.get_by_role("button", name="Camera and view controls")
            if menu.is_visible():
                menu.click()
                self.page.get_by_role("menuitem", name=action, exact=True).click()
            else:
                house.get_by_role("button", name=action, exact=True).click()
            self.capture("camera-action-" + action)
        for coverage in [False, True]:
            menu = house.get_by_role("button", name="Camera and view controls")
            if menu.is_visible():
                menu.click()
                self.page.get_by_role("menuitemcheckbox", name="Camera coverage").click()
            else:
                house.get_by_role("button", name="Toggle camera coverage").click()
            self.capture("coverage-" + str(coverage))
        canvas = self.page.locator(".house-view canvas")
        canvas.scroll_into_view_if_needed()
        box = canvas.bounding_box()
        for _ in range(5):
            self.page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.25)
            self.page.mouse.down()
            self.page.mouse.move(
                box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.9, steps=8
            )
            self.page.mouse.up()
            assert float(self.page.locator("[data-camera-y]").get_attribute("data-camera-y")) >= 0.6
        self.page.mouse.wheel(0, 20000)
        self.page.wait_for_timeout(250)
        assert (
            float(self.page.locator("[data-orbit-distance]").get_attribute("data-orbit-distance"))
            <= 55.01
        )
        self.capture("drag-and-zoom-bounds")
        self.scroll("home")
        self.keyboard("home", 55)

    def evidence(self, route):
        self.go(route)
        self.hover(route)
        for name in ["Camera", "Verdict"]:
            trigger = self.page.get_by_role("combobox", name=name, exact=True)
            trigger.click()
            options = self.page.get_by_role("option")
            count = options.count()
            self.page.keyboard.press("Escape")
            for index in range(count):
                trigger.click()
                self.page.get_by_role("option").nth(index).hover()
                self.capture(f"{route}-{name}-option-{index}")
                self.page.get_by_role("option").nth(index).click()
        self.page.get_by_role("button", name="Clear filters").click()
        clear_result = self.page.get_by_role("dialog", name="Media search")
        expect(clear_result).to_be_visible()
        self.capture(route + "-clear-result")
        self.page.keyboard.press("Escape")
        self.page.get_by_role("searchbox", name="Search evidence").fill("side gate")
        self.page.get_by_role("button", name="Apply filters").click()
        modal = self.page.get_by_role("dialog", name="Media search")
        expect(modal).to_be_visible()
        self.capture(route + "-server-result")
        self.page.keyboard.press("Escape")
        if route == "media":
            self.page.get_by_role("button", name="Time range", exact=False).click()
            dialog = self.page.get_by_role("dialog", name="Time range")
            self.hover("time-dialog", "[role=dialog]")
            dialog.get_by_label("From (local time)").fill("2026-11-02T18:00")
            dialog.get_by_label("Until (local time)").fill("2026-11-02T18:30")
            self.capture("time-range-selected")
            dialog.get_by_role("button", name="Done").click()
        self.page.get_by_role("button", name="Clear filters").click()
        clear_result = self.page.get_by_role("dialog", name="Media search")
        expect(clear_result).to_be_visible()
        self.capture(route + "-clear-result")
        self.page.keyboard.press("Escape")
        self.tabs(".evidence-kind-tabs > .v-tab-list", route + "-kind")
        self.page.get_by_role("tab", name="All clips", exact=True).click()
        self.scroll(route)
        self.keyboard(route)

    def messages(self):
        self.go("home")
        trigger = self.page.get_by_role("button", name="Messages", exact=True).last
        trigger.click()
        popup = self.page.get_by_role("dialog", name="Messages")
        self.page.wait_for_function(
            "getComputedStyle(document.querySelector('.v-chat-popup')).opacity==='1'"
        )
        field = popup.get_by_role("textbox", name="Message", exact=True)
        field.fill("Fixture retained draft")
        field.focus()
        self.page.evaluate(
            "window.reviewInput=document.activeElement;"
            "window.reviewCanvas=document.querySelector('.house-view canvas')"
        )
        for preference in ["reduce", "no-preference"]:
            self.page.emulate_media(reduced_motion=preference)
            self.page.wait_for_timeout(45)
            assert self.page.evaluate("document.activeElement===window.reviewInput")
            assert self.page.evaluate(
                "document.querySelector('.house-view canvas')===window.reviewCanvas"
            )
            assert field.input_value() == "Fixture retained draft"
            self.capture("popup-preference-" + preference)
        self.hover("popup", "[role=dialog]")
        self.keyboard("popup", 22)
        self.page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        self.page.get_by_role("button", name="Messages", exact=True).last.click()
        popup.get_by_role("tab", name="Household", exact=True).click()
        popup.get_by_role("textbox", name="Message", exact=True).fill("Fixture household draft")
        self.page.keyboard.press("Escape")
        if self.width <= 640:
            self.page.get_by_role("button", name="Open navigation").click()
        self.page.get_by_role("button", name="Messages", exact=True).first.click()
        expect(self.page.get_by_role("textbox", name="Message", exact=True)).to_have_value(
            "Fixture household draft"
        )
        self.page.get_by_role("button", name="Send message").click()
        expect(self.page.get_by_role("log")).to_contain_text("Fixture household draft")
        self.page.get_by_role("button", name="Share options").click()
        self.page.get_by_role("menuitem", name="Share a clip", exact=False).click()
        self.capture("share-clip-picker")
        self.page.get_by_role("dialog", name="Share a clip").get_by_role("button").nth(1).click()
        self.page.get_by_role("tab", name="Ask your home", exact=True).click()
        self.page.get_by_role("textbox", name="Message", exact=True).fill("side gate")
        self.page.get_by_role("button", name="Send message").click()
        cite = self.page.get_by_role("button", name=re.compile("Open evidence")).first
        cite.wait_for()
        event_id = cite.get_attribute("aria-label").removeprefix("Open evidence ")
        cite.click()
        self.page.get_by_test_id("visit-card").wait_for()
        event = next(e for e in self.state["events"] if e["event_id"] == event_id)
        expect(self.page.get_by_role("slider", name="Evidence time")).to_have_value(
            str(int(event["t"]))
        )
        self.capture("chat-exact-citation")

    def pages(self):
        for route in ["attention", "rules", "settings", "benchmark", "visit/v_c"]:
            self.go(route)
            self.hover(route)
            if route == "attention":
                self.tabs(".attention-tabs > .v-tab-list", "attention-verdict")
            if route == "settings":
                self.tabs(".controls-tabs > .v-tab-list", "settings-section")
                expect(self.page.get_by_role("button", name="I'm outside")).to_be_disabled()
                expect(
                    self.page.get_by_role("button", name="Select an object", exact=True)
                ).to_be_disabled()
            if route == "rules":
                fixtures = self.http.get(BASE + "/api/voice/fixtures").json()["fixtures"]
                for fixture in fixtures:
                    self.page.get_by_role("button", name=fixture["label"]).click()
                    expect(self.page.get_by_role("textbox", name="Rule text")).to_have_value(
                        fixture["transcript"]
                    )
                    self.page.get_by_role("button", name="Review rule draft").click()
                    self.page.get_by_role("region", name="Rule draft").wait_for()
                    self.capture("voice-draft-" + fixture["id"])
                self.page.get_by_role("button", name="Record a voice rule").click()
                self.capture("phone-microphone-dialog")
                self.page.get_by_role("button", name="Start microphone", exact=True).click()
                self.page.wait_for_timeout(500)
                self.capture("synthetic-phone-microphone-recording")
                self.page.get_by_role("button", name="Stop and transcribe").click()
                expect(self.page.get_by_role("dialog", name="Voice rule")).not_to_be_visible()
                self.capture("synthetic-phone-microphone-result")
            if route == "visit/v_c":
                citations = self.page.get_by_role("button", name=re.compile("Show evidence"))
                for index in range(citations.count()):
                    citations.nth(index).click()
                    self.capture("visit-citation-" + str(index))
                self.page.get_by_text("How this was decided", exact=True).click()
                self.capture("visit-validator-trace")
                self.page.get_by_role("button", name="Rebuild story from cache").click()
                self.page.get_by_text(
                    "Recorded story shown. No model request was made.", exact=True
                ).wait_for()
                self.page.get_by_role("button", name="This was expected").click()
                self.capture("visit-feedback")
            self.scroll(route)
            self.keyboard(route)

    def notifications(self):
        self.go("home")
        self.hover("global", ".v-sidebar,.v-topbar")
        bell = self.page.get_by_role("button", name=re.compile("^Notifications"))
        bell.click()
        items = self.page.locator(".v-notification-item")
        for index in range(items.count()):
            items.nth(index).hover()
            self.capture(f"notification-hover-{index}")
        self.page.locator(".v-notification-scroll").evaluate("e=>e.scrollTop=e.scrollHeight")
        self.capture("notifications-bottom")
        self.page.locator(".v-notification-scroll").evaluate("e=>e.scrollTop=0")
        items.first.click()
        expect(self.page.get_by_test_id("visit-card")).to_have_attribute("data-visit", "v_c")
        self.capture("notification-visit")
        bell.click()
        self.page.get_by_role("menuitem", name="Open Attention", exact=False).click()
        self.capture("notification-attention")

    def owner(self):
        self.go("settings", EDGE)
        self.page.get_by_role("tab", name="Owner controls", exact=True).click()
        self.page.get_by_label("Owner token", exact=True).fill("final-a-synthetic-owner-token")
        self.page.get_by_role("button", name="Save owner token").click()
        expect(self.page.get_by_text("Owner session active", exact=True)).to_be_visible()
        self.capture("owner-authenticated")
        self.page.get_by_role("button", name="I'm outside").click()
        expect(self.page.get_by_role("status").filter(has_text="s remaining")).to_be_visible()
        self.page.get_by_role("button", name="New expected window").click()
        dialog = self.page.get_by_role("dialog", name="New expected window")
        self.hover("owner-window-dialog", "[role=dialog]")
        self.keyboard("owner-window-dialog", 18)
        dates = self.page.evaluate("""() => {
          const local=d=>new Date(d.getTime()-d.getTimezoneOffset()*60000)
            .toISOString().slice(0,16);
          return [local(new Date(Date.now()+600000)),local(new Date(Date.now()+1200000))];
        }""")
        label = f"Fixture A {self.width}x{self.height} {self.theme} {self.run_tag}"
        dialog.get_by_label("Window label", exact=True).fill(label)
        dialog.get_by_label("Window starts", exact=True).fill(dates[0])
        dialog.get_by_label("Window ends", exact=True).fill(dates[1])
        for camera in self.state["cameras"]:
            dialog.get_by_label("Window camera", exact=True).select_option(camera["id"])
            self.capture("owner-scope-" + camera["id"])
        dialog.get_by_role("button", name="Create expected window").click()
        expect(dialog).not_to_be_visible()
        row = self.page.get_by_role("article", name=label, exact=True)
        expect(row).to_contain_text("Scheduled")
        row.get_by_role("button", name="Cancel window").click()
        expect(row).to_contain_text("Cancelled")
        self.capture("owner-window-cancelled")
        self.page.reload()
        self.page.get_by_role("tab", name="Owner controls", exact=True).click()
        expect(self.page.get_by_role("article", name=label, exact=True)).to_contain_text(
            "Cancelled"
        )
        expect(
            self.page.get_by_role("button", name="Select an object", exact=True)
        ).to_be_disabled()
        self.scroll("owner-controls")
        self.keyboard("owner-controls", 55)
        self.go("rules", EDGE)
        self.page.get_by_role("textbox", name="Rule text").fill(
            "Tell me if anyone except family touches the bin after 9 PM"
        )
        self.page.get_by_role("button", name="Review rule draft").click()
        self.page.get_by_role("button", name="Confirm rule", exact=True).click()
        expect(self.page.get_by_role("button", name="Confirm rule", exact=True)).to_have_count(0)
        self.capture("owner-confirmed-rule")

    def case(self, browser, width, height, theme):
        self.width, self.height, self.theme = width, height, theme
        context = browser.new_context(
            viewport={"width": width, "height": height},
            reduced_motion="reduce",
            permissions=["microphone"],
        )
        self.page = context.new_page()
        self.page.add_init_script(f"localStorage.setItem('vigil_theme','{theme}')")
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))
        self.page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        try:
            self.state = self.http.get(BASE + "/api/ui/state").json()
            self.home()
            self.evidence("clips")
            self.evidence("media")
            self.messages()
            self.notifications()
            self.pages()
            self.owner()
            assert not errors, errors
            self.capture("case-complete")
        except Exception as error:
            self.failures.append(
                {"viewport": [width, height], "theme": theme, "reason": str(error)}
            )
            self.capture("case-failure")
        finally:
            context.close()
            self.save()

    def save(self):
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"full-round2-{BLOCK}.json").write_text(
            json.dumps(
                {
                    "source": SOURCE,
                    "rows": self.rows,
                    "failures": self.failures,
                    "focus": self.focus,
                    "proofs": sorted(self.proofs),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def main():
    review = Review()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        )
        for width, height in SIZES:
            for theme in ["dark", "light"]:
                review.case(browser, width, height, theme)
                print(width, height, theme, len(review.rows), len(review.failures), flush=True)
        browser.close()
    print(f"Full R2: {len(review.rows)} captures; {len(review.failures)} failures", flush=True)


if __name__ == "__main__":
    main()
