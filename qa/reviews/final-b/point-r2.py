"""FIXTURE: point-selection review with explicit FakeBackend; crops exclude still pixels."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import respx
from playwright.sync_api import expect, sync_playwright
from pydantic import SecretStr

from tests.e2e.support import running_app
from tests.integration.test_api import FakeBackend
from tests.integration.test_cloud_process import generated_session, mock_models
from vigil.api.app import create_app
from vigil.meta.client import MetaClient
from vigil.pipeline import process_session
from vigil.store.export import export_session

OUT = Path("qa/screens/c965bedf/1470x870")


def main():
    root = Path("data/qa-final-b") / ("point-r2-" + uuid4().hex[:8])
    root.mkdir(parents=True)
    settings, _ = generated_session(root)
    with (
        respx.mock as router,
        MetaClient(
            settings, clock=lambda: datetime(2026, 11, 3, tzinfo=UTC), sleep=lambda _: None
        ) as client,
    ):
        mock_models(router)
        process_session("generated", settings=settings, client=client, confirm=True)
    bundle = export_session("generated", root / "bundle", settings=settings, synthetic=True)
    settings = settings.model_copy(
        update={"mode": "edge", "owner_token": SecretStr("synthetic-owner-token")}
    )
    backend = FakeBackend()
    app = create_app(settings, bundle_dir=bundle, live_backend=backend)
    assert app.state.live_backend is backend
    result = {
        "evidence": {"kind": "fixture"},
        "source": "c965bedfd1649bc781e0ae211bd7848885f51b1f",
        "backend": "explicit FakeBackend",
    }
    with running_app(app) as url, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1470, "height": 870}, reduced_motion="reduce")
        page.goto(url + "/next/#/settings")
        page.get_by_role("tab", name="Owner controls").click()
        page.get_by_role("textbox", name="Owner token").fill("synthetic-owner-token")
        page.get_by_role("button", name="Save owner token").click()
        expect(page.get_by_text("Owner session active")).to_be_visible()
        page.get_by_role("button", name="Select an object", exact=True).click()
        dialog = page.get_by_role("dialog", name="Select an object")
        page.wait_for_function(
            "document.querySelector('.protection-frame img')?.naturalWidth===1280"
        )
        # Actual still mouse coordinates derive from its rendered dimensions.
        frame = dialog.locator(".protection-frame img")
        box = frame.bounding_box()
        frame.evaluate("""e=>e.addEventListener('click',event=>{
          const b=e.getBoundingClientRect();window.reviewPoint={
            x:Math.round((event.clientX-b.left)*e.naturalWidth/b.width),
            y:Math.round((event.clientY-b.top)*e.naturalHeight/b.height)}})""")
        frame.click(position={"x": box["width"] * 0.125, "y": box["height"] * (600 / 720)})
        x = dialog.get_by_role("spinbutton", name="Pixel X")
        y = dialog.get_by_role("spinbutton", name="Pixel Y")
        clicked = page.evaluate("window.reviewPoint")
        assert float(x.input_value()) == clicked["x"]
        assert float(y.input_value()) == clicked["y"]
        result["clicked_point"] = clicked
        x.fill("160")
        y.fill("600")
        expect(x).to_have_value("160")
        expect(y).to_have_value("600")
        dialog.get_by_role("textbox", name="Object label").fill("Fixture gate")
        # Crop just opaque controls, never generated still pixels or transparent scrim.
        dialog.locator(".controls-form-row").screenshot(
            path=str(OUT / "final-b-r2-point-coordinates.png")
        )
        result["point"] = {"x": x.input_value(), "y": y.input_value()}
        dialog.get_by_role("button", name="Request point model").click()
        approval = page.get_by_role("dialog", name="Approve point model request")
        expect(approval).to_contain_text("$0.0025")
        assert backend.calls == []
        approval.screenshot(path=str(OUT / "final-b-r2-point-cost-approval.png"))
        result["before_approval_calls"] = list(backend.calls)
        approval.get_by_role("button", name="Approve and run").click()
        expect(dialog.get_by_label("Point model mask")).to_be_visible()
        expect(dialog).to_contain_text("Added to this server session")
        assert backend.calls == ["protect"]
        result["after_approval_calls"] = list(backend.calls)
        dialog.locator(".controls-status").screenshot(
            path=str(OUT / "final-b-r2-point-session-result.png")
        )
        dialog.get_by_role("button", name="Close Select an object").click()
        page.get_by_role("button", name="Rules and protected objects", exact=True).click()
        expect(page.get_by_role("heading", name="Fixture gate", exact=True)).to_be_visible()
        result["runtime_object_visible"] = True
        browser.close()
    (OUT / "final-b-r2-point.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
