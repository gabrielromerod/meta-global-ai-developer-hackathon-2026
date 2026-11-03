"""FIXTURE: fault/retry, session clocks, semantic contrast and fake-device safety."""

import hashlib
import json
import subprocess
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
SOURCE = subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], text=True).strip()
OUT = ROOT / "qa/screens" / SOURCE
BASE = "http://127.0.0.1:8118"
ROWS = []


def shot(page, label):
    viewport = page.viewport_size
    folder = OUT / f"{viewport['width']}x{viewport['height']}"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"final-a-supplement-{label}.png"
    page.screenshot(path=str(folder / filename))
    state = httpx.get(BASE + "/api/ui/state").content
    digest = hashlib.sha256(state).hexdigest()[:16]
    proof = OUT / "proofs" / f"api-state-{digest}.json"
    proof.parent.mkdir(exist_ok=True)
    proof.write_bytes(state)
    ROWS.append({"label": label, "file": str((folder / filename).relative_to(OUT))})


def luminance(value):
    raw = value.lstrip("#")
    if len(raw) == 3:
        raw = "".join(character * 2 for character in raw)
    channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(a * b for a, b in zip(linear, [0.2126, 0.7152, 0.0722], strict=True))


def main():
    contrast, facts = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        )
        for width, height in [(1470, 870), (390, 844)]:
            for theme in ["dark", "light"]:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    timezone_id="UTC",
                    permissions=["microphone"],
                )
                page = context.new_page()
                page.add_init_script(f"localStorage.setItem('vigil_theme','{theme}')")
                pending = []
                page.route(
                    "**/api/ui/chat", lambda route, request, pending=pending: pending.append(route)
                )
                page.goto(BASE + "/next/?fault=round2#/messages")
                expect(page.get_by_role("heading", name="Loading messages")).to_be_visible()
                shot(page, f"{theme}-chat-pending")
                assert len(pending) == 1
                pending[0].fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"Independent fixture service outage"}',
                )
                expect(page.get_by_role("heading", name="Messages unavailable")).to_be_visible()
                expect(page.get_by_role("alert")).to_have_text("Independent fixture service outage")
                shot(page, f"{theme}-chat-error")
                page.unroute("**/api/ui/chat")
                page.get_by_role("button", name="Try again").click()
                expect(page.get_by_role("textbox", name="Message", exact=True)).to_be_visible()
                shot(page, f"{theme}-chat-retry-restored")
                page.goto(BASE + "/next/#/visit/v_c")
                page.get_by_role("button", name="Show evidence e17", exact=True).click()
                clock = page.get_by_label("Recorded time", exact=True)
                expect(clock).to_contain_text("6:14:05 PM")
                expect(clock).to_contain_text("UTC-08:00")
                clock.scroll_into_view_if_needed()
                shot(page, f"{theme}-utc-session-clock")
                if width == 1470:
                    colors = page.evaluate("""() => {
                      const s=getComputedStyle(document.documentElement),names=[
                        'text','muted','accent','danger','warning','success','unknown',
                        'bg','surface','raised','accent-ink'];
                      return Object.fromEntries(names.map(n=>
                        [n,s.getPropertyValue('--v-'+n).trim()]));
                    }""")
                    for foreground in [
                        "text",
                        "muted",
                        "accent",
                        "danger",
                        "warning",
                        "success",
                        "unknown",
                    ]:
                        for background in ["bg", "surface", "raised"]:
                            a, b = luminance(colors[foreground]), luminance(colors[background])
                            ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
                            contrast.append(
                                {
                                    "theme": theme,
                                    "foreground": foreground,
                                    "background": background,
                                    "ratio": ratio,
                                }
                            )
                            assert ratio >= 4.5, contrast[-1]
                    a, b = luminance(colors["accent-ink"]), luminance(colors["accent"])
                    assert (max(a, b) + 0.05) / (min(a, b) + 0.05) >= 4.5
                    device = page.evaluate("""async()=>{
                      const stream=await navigator.mediaDevices.getUserMedia(
                        {audio:true,video:false});
                      const result={audio:stream.getAudioTracks().map(t=>t.label),
                        video:stream.getVideoTracks().length};
                      stream.getTracks().forEach(t=>t.stop());return result;
                    }""")
                    assert device["video"] == 0
                    assert all("fake" in label.lower() for label in device["audio"])
                    facts.append({"theme": theme, "device": device})
                context.close()
        browser.close()
    (OUT / "supplement-round2.json").write_text(
        json.dumps(
            {"source": SOURCE, "rows": ROWS, "contrast": contrast, "facts": facts}, indent=2
        ),
        encoding="utf-8",
    )
    print(
        f"Supplement: {len(ROWS)} screenshots; {len(contrast)} AA token checks; "
        "fake devices verified"
    )


if __name__ == "__main__":
    main()
