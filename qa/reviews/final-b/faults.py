"""FIXTURE: isolated service/microphone failures; no real microphone or model request."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    out = Path("qa/screens/9a8ced22/1470x870")
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1470, "height": 870}, reduced_motion="reduce")
        page.route(
            "**/api/ui/chat",
            lambda route: route.fulfill(status=503, json={"detail": "Fixture chat unavailable"}),
        )
        page.goto("http://127.0.0.1:8119/next/#/messages")
        page.get_by_role("heading", name="No threads available").wait_for()
        page.screenshot(path=str(out / "final-b-chat-service-error-as-empty.png"))
        chat = {
            "text": page.locator(".v-chat-page").inner_text(),
            "alerts": page.get_by_role("alert").count(),
        }
        page.close()
        page = browser.new_page(viewport={"width": 1470, "height": 870}, reduced_motion="reduce")
        page.add_init_script("""(() => {
          window.fixtureMic={requested:0,stopped:0};
          Object.defineProperty(navigator.mediaDevices,'getUserMedia',{configurable:true,value:async()=>{
            window.fixtureMic.requested++;
            return {getTracks:()=>[{stop:()=>{window.fixtureMic.stopped++}}]};
          }});
          window.AudioContext=class {constructor(){
            throw new Error('Fixture AudioContext unavailable')}};
        })()""")
        page.goto("http://127.0.0.1:8119/next/#/rules")
        page.get_by_role("button", name="Record a voice rule").click()
        page.get_by_role("button", name="Start microphone").click()
        page.get_by_role("alert").wait_for()
        during = page.evaluate("window.fixtureMic")
        page.screenshot(path=str(out / "final-b-microphone-start-failure.png"))
        page.get_by_role("button", name="Close Voice rule").click()
        after = page.evaluate("window.fixtureMic")
        result = {"chat": chat, "microphone_failure": during, "after_dialog_close": after}
        (out / "final-b-faults.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
        browser.close()


if __name__ == "__main__":
    main()
