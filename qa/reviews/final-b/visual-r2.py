"""FIXTURE: computed token contrast, focus, bounds and preserved orbit state."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

OUT = Path("qa/screens/c965bedf")
BASE = "http://127.0.0.1:8119/next/"


def main():
    result = {"evidence": {"kind": "fixture"}, "contrast": [], "bounds": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in ["dark", "light"]:
            ctx = browser.new_context(viewport={"width": 1470, "height": 870})
            ctx.add_init_script(f"localStorage.setItem('vigil_theme','{theme}')")
            p = ctx.new_page()
            p.goto(BASE)
            p.wait_for_function("document.body.dataset.ready==='1'")
            rows = p.evaluate("""()=>{
              const s=getComputedStyle(document.documentElement);
              const lum=k=>{let hex=s.getPropertyValue('--v-'+k).trim();
                if(hex.length===4)hex='#'+[...hex.slice(1)].map(c=>c+c).join('');
                const v=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255)
                  .map(c=>c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4));
                return .2126*v[0]+.7152*v[1]+.0722*v[2]};
              return [['text','bg'],['text','surface'],['muted','surface'],['accent','surface'],
                ['danger','surface'],['warning','surface'],['success','surface'],
                ['unknown','surface'],['accent-ink','accent']].map(([fg,bg])=>{
                const a=lum(fg),b=lum(bg);
                return {fg,bg,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)}})
            }""")
            assert all(r["ratio"] >= 4.5 for r in rows)
            result["contrast"] += [{"theme": theme, **r} for r in rows]
            # Roving wrapper's focus ring must survive Radix inline outline:none.
            p.keyboard.press("Tab")
            wrapper = p.get_by_role("tablist", name="House views", exact=True)
            wrapper.evaluate(
                """e=>{e.addEventListener('rovingFocusGroup.onEntryFocus',ev=>ev.preventDefault());e.focus()}"""
            )
            expect(wrapper).to_be_focused()
            ring = wrapper.evaluate(
                "e=>({visible:e.matches(':focus-visible'),shadow:getComputedStyle(e).boxShadow})"
            )
            assert ring["visible"]
            assert "inset" in ring["shadow"]
            assert "2px" in ring["shadow"]
            p.screenshot(path=str(OUT / "1470x870" / f"final-b-r2-wrapper-focus-{theme}.png"))
            result["focus_" + theme] = ring
            ctx.close()
        for w, h in [
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
        ]:
            p = browser.new_page(viewport={"width": w, "height": h}, reduced_motion="reduce")
            p.goto(BASE)
            p.locator(".twin-toolbar").wait_for()
            p.locator(".twin-toolbar").scroll_into_view_if_needed()
            bounds = p.locator(".twin-toolbar").evaluate(
                """e=>{const a=e.getBoundingClientRect();
                  return [...e.querySelectorAll('button')].filter(b=>b.getClientRects().length)
                    .map(b=>{const r=b.getBoundingClientRect();
                      return {name:b.getAttribute('aria-label')||b.textContent,
                        left:r.left,right:r.right,parentLeft:a.left,parentRight:a.right}})}"""
            )
            assert all(
                b["left"] >= b["parentLeft"] - 0.1 and b["right"] <= b["parentRight"] + 0.1
                for b in bounds
            ), bounds
            result["bounds"].append({"viewport": f"{w}x{h}", "controls": bounds})
            if w == 390:
                p.get_by_role("button", name="Camera and view controls", exact=True).click()
                menu = p.get_by_role("menu")
                expect(menu).to_be_visible()
                box = menu.bounding_box()
                assert box["x"] >= 0
                assert box["x"] + box["width"] <= w
                p.screenshot(path=str(OUT / "390x844" / "final-b-r2-compact-menu.png"))
            p.close()
        p = browser.new_page(viewport={"width": 1470, "height": 870}, reduced_motion="reduce")
        p.goto(BASE)
        canvas = p.locator(".twin-canvas")
        p.wait_for_function("document.querySelector('.twin-canvas')?.dataset.cameraPosition")
        box = canvas.bounding_box()
        x, y = box["x"] + box["width"] * 0.08, box["y"] + box["height"] * 0.3
        p.mouse.move(x, y)
        p.mouse.down(button="right")
        p.mouse.move(x + 75, y + 35, steps=12)
        p.mouse.up(button="right")
        p.wait_for_timeout(100)
        before = canvas.evaluate("e=>({position:e.dataset.cameraPosition,target:e.dataset.target})")
        p.emulate_media(reduced_motion="no-preference")
        expect(p.locator(".house-view")).to_have_attribute("data-motion-seconds", "0.48")
        after = canvas.evaluate("e=>({position:e.dataset.cameraPosition,target:e.dataset.target})")
        assert before == after, (before, after)
        result["pan_preserved"] = before
        p.screenshot(path=str(OUT / "1470x870" / "final-b-r2-panned-preference.png"))
        browser.close()
    (OUT / "final-b-r2-visual-probes.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(
        "18 AA pairs; wrapper focus in both themes;11 toolbars in bounds; panned pose preserved",
        flush=True,
    )


if __name__ == "__main__":
    main()
