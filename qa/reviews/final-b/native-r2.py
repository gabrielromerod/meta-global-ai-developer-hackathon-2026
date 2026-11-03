"""FIXTURE: genuine generated two-camera native mouse and keyboard transport."""

import json
from contextlib import contextmanager
from pathlib import Path
from runpy import run_path

from playwright.sync_api import sync_playwright

from tests.e2e.test_real_video import multicamera_server

helpers = run_path("qa/reviews/final-b/native-controls.py", run_name="review_helpers")
Factory = helpers["Factory"]
native_toggle = helpers["native_toggle"]
OUT = Path("qa/screens/c965bedf/1470x870")


def state(page):
    return page.evaluate("""()=>({
      times:[...document.querySelectorAll('video')].map(v=>v.currentTime),
      paused:[...document.querySelectorAll('video')].map(v=>v.paused),
      clock:Number(document.querySelector('#evidence-clock').value),
      button:document.querySelector('.visit-clock button').getAttribute('aria-label')})""")


def readout(page, values, label):
    page.evaluate(
        """({values,label})=>{
      document.querySelector('.review-readout')?.remove();
      const box=document.createElement('aside');box.className='review-readout';
      Object.assign(box.style,{position:'fixed',top:'16px',left:'16px',width:'600px',
        zIndex:'99999',background:'#131a23',color:'#edf3fb',padding:'24px',font:'16px Inter'});
      const h=document.createElement('h2');h.textContent='FIXTURE: observed '+label;
      const p=document.createElement('p');
      p.textContent='Source c965bedf. Two generated MP4s. No video pixels.';
      const pre=document.createElement('pre');pre.textContent=JSON.stringify(values,null,2);
      box.append(h,p,pre);document.body.appendChild(box);
    }""",
        {"values": values, "label": label},
    )
    page.locator(".review-readout").screenshot(
        path=str(OUT / ("final-b-r2-native-" + label + ".png"))
    )
    page.locator(".review-readout").evaluate("e=>e.remove()")


def main():
    OUT.mkdir(exist_ok=True, parents=True)
    result = {
        "evidence": {"kind": "fixture"},
        "source": "c965bedfd1649bc781e0ae211bd7848885f51b1f",
        "observations": [],
    }
    with (
        contextmanager(multicamera_server.__wrapped__)(Factory()) as (url, visit_id),
        sync_playwright() as pw,
    ):
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1470, "height": 870}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url + "/next/#/visit/" + visit_id)
        page.wait_for_function(
            "document.querySelectorAll('video').length===2&&[...document.querySelectorAll('video')].every(v=>v.readyState>=2)"
        )
        page.get_by_role("slider", name="Evidence time").fill("1")
        page.wait_for_function(
            "[...document.querySelectorAll('video')].every(v=>Math.abs(v.currentTime-1)<.1)"
        )
        # Chromium native media play button uses real mouse coordinates, not video.play().
        video = page.locator("video").first
        video.scroll_into_view_if_needed()
        video.hover()
        box = video.bounding_box()
        page.mouse.click(box["x"] + 18, box["y"] + box["height"] - 46)
        page.wait_for_timeout(650)
        s = state(page)
        assert s["clock"] > 1.3, s
        assert not any(s["paused"]), s
        assert max(s["times"]) - min(s["times"]) < 0.2, s
        result["observations"].append({"kind": "mouse-play", **s})
        readout(page, s, "mouse-play")
        video.hover()
        box = video.bounding_box()
        page.mouse.click(box["x"] + 18, box["y"] + box["height"] - 46)
        page.wait_for_timeout(400)
        s = state(page)
        assert all(s["paused"]), s
        assert s["button"] == "Play evidence timeline", s
        frozen = s["clock"]
        page.wait_for_timeout(400)
        assert abs(state(page)["clock"] - frozen) < 0.01
        result["observations"].append({"kind": "mouse-pause", **s})
        readout(page, s, "mouse-pause")
        for index in (0, 1):
            page.get_by_role("slider", name="Evidence time").fill("1")
            chosen = page.locator("video").nth(index)
            chosen.focus()
            chosen.press("Space")
            page.wait_for_timeout(500)
            s = state(page)
            assert s["clock"] > 1.2, s
            assert not any(s["paused"]), s
            assert max(s["times"]) - min(s["times"]) < 0.2, s
            result["observations"].append({"kind": f"keyboard-play-{index}", **s})
            readout(page, s, f"keyboard-play-{index}")
            chosen.press("Space")
            page.wait_for_timeout(300)
            assert all(state(page)["paused"])
        result["errors"] = errors
        assert not errors
        browser.close()
    (OUT / "final-b-r2-native.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
