"""FIXTURE transport probe; published crop deliberately excludes all media pixels."""

import json
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright

from tests.e2e.test_real_video import video_server

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "qa/screens/9a8ced22/1470x870"


class Factory:
    def mktemp(self, name):
        folder = ROOT / "data/qa-final-a-generated" / (name + "-" + uuid4().hex[:8])
        folder.mkdir(parents=True)
        return folder


def main():
    with (
        contextmanager(video_server.__wrapped__)(Factory()) as (url, visit_id),
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1470, "height": 870})
        page.goto(url + "/next/#/visit/" + visit_id)
        page.wait_for_function("document.querySelector('video')?.readyState>=2")
        page.get_by_role("slider", name="Evidence time").fill("0.5")
        page.wait_for_function("Math.abs(document.querySelector('video').currentTime-.5)<.1")
        page.locator("video").focus()
        page.keyboard.press("Space")
        page.wait_for_timeout(650)
        observation = page.evaluate("""() => {
          const video=document.querySelector('video');
          const clock=document.querySelector('#evidence-clock');
          const result={video_time:video.currentTime,native_paused:video.paused,
            common_clock:Number(clock.value),clock_label:document.querySelector('output').textContent};
          const diagnostic=document.createElement('aside');
          diagnostic.id='final-a-diagnostic';
          diagnostic.style.cssText='padding:8px;font:14px/1.5 sans-serif';
          diagnostic.textContent='FIXTURE diagnostic: observed generated-MP4 transport. '
            +'Native video time: '+result.video_time.toFixed(4)+' s; '
            +'native paused: '+result.native_paused+'; '
            +'shared evidence clock: '+result.common_clock.toFixed(4)+' s. '
            +'This diagnostic crop contains no video pixels.';
          document.querySelector('.visit-clock').before(diagnostic);
          document.querySelector('.visit-player-card').scrollTop=0;
          return result;
        }""")
        page.evaluate("document.activeElement.blur()")
        page.locator("#final-a-diagnostic").scroll_into_view_if_needed()
        page.evaluate(
            "() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))"
        )
        geometry = page.evaluate("""() => {
          const a=document.querySelector('#final-a-diagnostic').getBoundingClientRect();
          const b=document.querySelector('.visit-clock').getBoundingClientRect();
          const video=document.querySelector('.visit-video').getBoundingClientRect();
          return {crop:{x:Math.min(a.x,b.x),y:a.y,
                width:Math.max(a.right,b.right)-Math.min(a.x,b.x),
            height:b.bottom-a.y},video_top:video.top};
        }""")
        assert geometry["crop"]["y"] + geometry["crop"]["height"] <= geometry["video_top"]
        OUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(OUT / "final-a-native-clock-diagnostic.png"), clip=geometry["crop"]
        )
        record = {
            "evidence": {"kind": "fixture"},
            "source_commit": "9a8ced22",
            "source_generator": "tests/e2e/test_real_video.py::video_server",
            "observation": observation,
            "media_free_crop": geometry,
        }
        (ROOT / "qa/reviews/final-a/native-transport.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        print(json.dumps(record))
        browser.close()


if __name__ == "__main__":
    main()
