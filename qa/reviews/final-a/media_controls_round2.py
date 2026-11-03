"""FIXTURE: genuine silent MP4s and point UI; only media-redacted crops are published."""

import hashlib
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
from pydantic import SecretStr

from tests.e2e.support import running_app
from tests.e2e.test_real_video import _video_bundle
from tests.integration.test_api import FakeBackend
from vigil.api.app import create_app
from vigil.ingest.metadata import scan

ROOT = Path(__file__).resolve().parents[3]
SOURCE = subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], text=True).strip()
OUT = ROOT / "qa/screens" / SOURCE
DATA = ROOT / "data/qa-final-a-media-r2" / uuid4().hex[:8]
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


def control_crop(page, element, filename, facts):
    # Visibility redaction retains the tested layout and values. No media is repainted.
    media = page.locator("img,video")
    original = media.evaluate_all("es=>es.map(e=>e.style.visibility)")
    media.evaluate_all("es=>es.forEach(e=>e.style.visibility='hidden')")
    page.evaluate("() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
    element.screenshot(path=str(filename))
    media.evaluate_all("(es,values)=>es.forEach((e,i)=>e.style.visibility=values[i])", original)
    record = {
        "evidence": {"kind": "fixture"},
        "source": SOURCE,
        "media_hidden_for_control_crop": True,
        "observed": facts,
    }
    raw = json.dumps(record, sort_keys=True).encode()
    proof = OUT / "proofs" / f"control-{hashlib.sha256(raw).hexdigest()[:16]}.json"
    proof.parent.mkdir(parents=True, exist_ok=True)
    proof.write_bytes(raw)
    return str(proof.relative_to(ROOT))


def native_click(page, name):
    """Use the real Chromium accessibility/control box, not a guessed video offset."""
    session = page.context.new_cdp_session(page)
    nodes = session.send("Accessibility.getFullAXTree")["nodes"]
    node = next(
        n
        for n in nodes
        if n.get("role", {}).get("value") == "button"
        and str(n.get("name", {}).get("value", "")).lower() == name
    )
    session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": node["backendDOMNodeId"]})
    quad = session.send("DOM.getBoxModel", {"backendNodeId": node["backendDOMNodeId"]})["model"][
        "content"
    ]
    page.mouse.click(sum(quad[::2]) / 4, sum(quad[1::2]) / 4)
    session.detach()


def main():
    DATA.mkdir(parents=True)
    settings, bundle, visit_id = _video_bundle(DATA, multiple=True)
    settings = settings.model_copy(
        update={
            "mode": "edge",
            "owner_token": SecretStr("final-a-synthetic-owner-token"),
            "model_api_key": SecretStr("invalid"),
            "meta_base_url": "http://127.0.0.1:9/v1",
            "meta_cache_only": False,
        }
    )
    backend = FakeBackend()
    app = create_app(settings, bundle_dir=bundle, live_backend=backend)
    assert app.state.live_backend is backend
    assert settings.meta_base_url == "http://127.0.0.1:9/v1"
    rows = []
    last_approval = 0.0
    with running_app(app) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in SIZES:
            for theme in ["dark", "light"]:
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.add_init_script(f"localStorage.setItem('vigil_theme','{theme}')")
                page.goto(base + "/next/#/visit/" + visit_id)
                page.wait_for_function(
                    "[...document.querySelectorAll('video')].length===2&&"
                    "[...document.querySelectorAll('video')].every(v=>v.readyState>=2)"
                )
                slider = page.get_by_role("slider", name="Evidence time")
                slider.fill("1")
                page.wait_for_function(
                    "[...document.querySelectorAll('video')].every(v=>Math.abs(v.currentTime-1)<.1)"
                )
                videos = page.locator("video")
                first = videos.first
                first.scroll_into_view_if_needed()
                first.hover()
                native_click(page, "play")
                page.wait_for_function(
                    "document.querySelector('video').currentTime>1.3&&"
                    "!document.querySelector('video').paused"
                )
                times = videos.evaluate_all("es=>es.map(v=>v.currentTime)")
                assert max(times) - min(times) < 0.2, times
                assert abs(float(slider.input_value()) - times[0]) < 0.2
                native_click(page, "pause")
                page.wait_for_function("[...document.querySelectorAll('video')].every(v=>v.paused)")
                before = float(slider.input_value())
                page.wait_for_timeout(250)
                assert abs(float(slider.input_value()) - before) < 0.2
                videos.last.focus()
                videos.last.press("Space")
                page.wait_for_timeout(300)
                times2 = videos.evaluate_all("es=>es.map(v=>v.currentTime)")
                assert max(times2) - min(times2) < 0.2, times2
                videos.last.press("Space")
                page.wait_for_function("[...document.querySelectorAll('video')].every(v=>v.paused)")
                folder = OUT / f"{width}x{height}"
                folder.mkdir(parents=True, exist_ok=True)
                transport = {
                    "mouse_play_times": times,
                    "keyboard_play_times": times2,
                    "common_clock": float(slider.input_value()),
                    "both_paused": True,
                }
                proof1 = control_crop(
                    page,
                    page.locator(".visit-clock"),
                    folder / f"final-a-media-{theme}-transport.png",
                    transport,
                )
                page.get_by_role("button", name="Messages", exact=True).last.click()
                page.get_by_role("button", name="Take snapshot", exact=True).click()
                snapshot = page.get_by_role("dialog", name="Camera snapshot")
                image = snapshot.get_by_role("img")
                expect(image).to_be_visible()
                page.wait_for_function(
                    "document.querySelector('.app-snapshot')?.naturalWidth===1280"
                )
                assert image.evaluate("e=>e.naturalWidth") == 1280
                with page.expect_download() as download:
                    snapshot.get_by_role("link", name="Save PNG snapshot").click()
                saved = DATA / f"snapshot-{width}-{height}-{theme}.png"
                download.value.save_as(saved)
                assert scan(saved) == []
                snapshot.get_by_role("button", name="Close Camera snapshot").click()
                page.keyboard.press("Escape")
                page.goto(base + "/next/#/settings")
                page.get_by_role("tab", name="Owner controls").click()
                page.get_by_label("Owner token", exact=True).fill("final-a-synthetic-owner-token")
                page.get_by_role("button", name="Save owner token").click()
                page.get_by_role("button", name="Select an object", exact=True).click()
                dialog = page.get_by_role("dialog", name="Select an object")
                frame = dialog.locator(".protection-frame img")
                page.wait_for_function(
                    "document.querySelector('.protection-frame img')?.naturalWidth===1280"
                )
                frame.scroll_into_view_if_needed()
                frame.evaluate("""image=>image.addEventListener('click',event=>{
                  const r=image.getBoundingClientRect();
                  window.reviewPoint={x:Math.round((event.clientX-r.left)*image.naturalWidth/r.width),
                    y:Math.round((event.clientY-r.top)*image.naturalHeight/r.height)};
                },{once:true})""")
                rect = frame.bounding_box()
                frame.click(
                    position={"x": rect["width"] * 160 / 1280, "y": rect["height"] * 600 / 720}
                )
                observed_point = page.evaluate("window.reviewPoint")
                expect(dialog.get_by_label("Pixel X", exact=True)).to_have_value(
                    str(observed_point["x"])
                )
                expect(dialog.get_by_label("Pixel Y", exact=True)).to_have_value(
                    str(observed_point["y"])
                )
                dialog.get_by_label("Pixel X", exact=True).fill("640")
                dialog.get_by_label("Pixel Y", exact=True).fill("360")
                facts = {
                    "point": [640, 360],
                    "dimensions": [1280, 720],
                    "mouse_point_verified": observed_point,
                }
                proof2 = control_crop(
                    page,
                    dialog.locator(".controls-form-row"),
                    folder / f"final-a-media-{theme}-point-coordinates.png",
                    facts,
                )
                count = len(backend.calls)
                # Preserve the production 10/min guard while exercising all 22 cases.
                elapsed = time.monotonic() - last_approval
                if elapsed < 6.1:
                    time.sleep(6.1 - elapsed)
                dialog.get_by_role("button", name="Request point model").click()
                approval = page.get_by_role("dialog", name="Approve point model request")
                expect(approval).to_contain_text("$0.0025")
                assert len(backend.calls) == count
                proof3 = control_crop(
                    page,
                    approval,
                    folder / f"final-a-media-{theme}-cost-approval.png",
                    {
                        "estimate_usd": 0.0025,
                        "backend": "FakeBackend",
                        "calls_before_approval": count,
                    },
                )
                approval.get_by_role("button", name="Approve and run").click()
                last_approval = time.monotonic()
                expect(dialog.get_by_label("Point model mask")).to_be_visible()
                assert len(backend.calls) == count + 1
                assert not errors, errors
                rows.append(
                    {
                        "viewport": [width, height],
                        "theme": theme,
                        "transport": transport,
                        "proofs": [proof1, proof2, proof3],
                    }
                )
                print(width, height, theme, "media/point passed", flush=True)
                context.close()
        browser.close()
    (OUT / "media-controls-round2.json").write_text(
        json.dumps(
            {"source": SOURCE, "rows": rows, "backend": "FakeBackend", "calls": backend.calls},
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
