"""FIXTURE: independent native video controls probe with recorded models/generated MP4."""

import json
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright

from tests.e2e.test_real_video import video_server


class Factory:
    def mktemp(self, name):
        path = Path("data/qa-final-b") / (name + "-" + uuid4().hex[:8])
        path.mkdir(parents=True)
        return path.resolve()


def state(page):
    return page.evaluate("""() => ({
      videoTime:document.querySelector('video').currentTime,
      paused:document.querySelector('video').paused,
      clock:Number(document.querySelector('#evidence-clock').value),
      timelineButton:document.querySelector('.visit-clock button').getAttribute('aria-label')
    })""")


def native_toggle(page):
    video = page.locator("video")
    video.scroll_into_view_if_needed()
    video.hover()
    box = video.bounding_box()
    page.mouse.click(box["x"] + 18, box["y"] + box["height"] - 46)


def readout(page, values, label, path):
    page.evaluate(
        """({values,label}) => {
      document.querySelector('.final-b-readout')?.remove();
      const box=document.createElement('aside');box.className='final-b-readout';
      Object.assign(box.style,{position:'fixed',top:'16px',left:'16px',width:'600px',
        zIndex:'99999',background:'#131a23',color:'#edf3fb',padding:'24px',font:'16px Inter'});
      const heading=document.createElement('h2');heading.textContent='FIXTURE — observed '+label;
      const note=document.createElement('p');
      note.textContent='Source 9a8ced22. Actual generated-video properties; '+
        'no video pixels are included.';
      const details=document.createElement('pre');details.textContent=JSON.stringify(values,null,2);
      box.append(heading,note,details);document.body.appendChild(box);
    }""",
        {"values": values, "label": label},
    )
    page.locator(".final-b-readout").screenshot(path=str(path))


def main():
    out = Path("qa/screens/9a8ced22/1470x870")
    out.mkdir(parents=True, exist_ok=True)
    with (
        contextmanager(video_server.__wrapped__)(Factory()) as (url, visit_id),
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1470, "height": 870}, reduced_motion="reduce")
        page.goto(url + "/next/#/visit/" + visit_id)
        page.wait_for_function("document.querySelector('video')?.readyState>=2")
        page.get_by_role("slider", name="Evidence time").fill("1")
        page.wait_for_function("Math.abs(document.querySelector('video').currentTime-1)<.1")
        native_toggle(page)
        page.wait_for_timeout(650)
        native_play = state(page)
        page.screenshot(path=str(out / "final-b-native-play-desync-untracked.png"))
        readout(page, native_play, "native Play", out / "final-b-native-play-readout.png")
        page.locator(".final-b-readout").evaluate("e=>e.remove()")
        print("PLAY", native_play, flush=True)
        page.get_by_role("button", name="Play evidence timeline").click()
        page.wait_for_timeout(250)
        native_toggle(page)
        page.wait_for_timeout(250)
        native_pause = state(page)
        page.screenshot(path=str(out / "final-b-native-pause-ignored-untracked.png"))
        readout(page, native_pause, "native Pause", out / "final-b-native-pause-readout.png")
        print("PAUSE", native_pause, flush=True)
        (out / "final-b-native-controls.json").write_text(
            json.dumps(
                {
                    "evidence": {"kind": "fixture"},
                    "native_play": native_play,
                    "native_pause": native_pause,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()


if __name__ == "__main__":
    main()
