"""FIXTURE: actual HTML video decode, seeks and overlays on generated MP4, no cameras."""

import json
from datetime import UTC, datetime

import pytest
import respx
from playwright.sync_api import Page, expect

from tests.e2e.conftest import UnreachableBackend, wait_ready
from tests.e2e.support import running_app
from tests.integration.test_cloud_process import generated_session, mock_models
from vigil.api.app import create_app
from vigil.meta.client import MetaClient
from vigil.pipeline import process_session
from vigil.store.export import export_session

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def video_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("video-browser")
    settings, bundle, visit_id = _video_bundle(root)
    app = create_app(
        settings.model_copy(update={"mode": "sandbox", "meta_cache_only": True}),
        bundle_dir=bundle,
        live_backend=UnreachableBackend(),
    )
    with running_app(app) as url:
        yield url, visit_id


def _video_bundle(root, *, multiple=False):
    settings, _ = generated_session(root)
    if multiple:
        config = json.loads(settings.config_path.read_text(encoding="utf-8"))
        config["cameras"].append(
            {
                **config["cameras"][0],
                "id": "porch",
                "name": "Porch",
                "zones": {"porch_yard": config["cameras"][0]["zones"]["yard"]},
            }
        )
        settings.config_path.write_text(json.dumps(config), encoding="utf-8")
        windows_file = settings.data_dir / "windows/generated/windows.json"
        windows = json.loads(windows_file.read_text(encoding="utf-8"))
        windows.append({**windows[0], "id": "w1", "camera_id": "porch"})
        windows_file.write_text(json.dumps(windows), encoding="utf-8")
    with (
        respx.mock as router,
        MetaClient(
            settings,
            clock=lambda: datetime(2026, 11, 3, tzinfo=UTC),
            sleep=lambda _: None,
        ) as client,
    ):
        mock_models(router)
        result = process_session("generated", settings=settings, client=client, confirm=True)
    bundle = export_session("generated", root / "bundle", settings=settings, synthetic=True)
    return settings, bundle, result["visits"][0]["id"]


@pytest.fixture(scope="module")
def multicamera_server(tmp_path_factory):
    settings, bundle, visit_id = _video_bundle(
        tmp_path_factory.mktemp("multicamera-browser"), multiple=True
    )
    app = create_app(
        settings.model_copy(update={"mode": "sandbox", "meta_cache_only": True}),
        bundle_dir=bundle,
        live_backend=UnreachableBackend(),
    )
    with running_app(app) as url:
        yield url, visit_id


def test_player_generated_mp4_decodes_seeks_and_draws_overlays(page: Page, video_server):
    url, visit_id = video_server
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{url}/next/#/visit/{visit_id}")
    wait_ready(page)
    video = page.locator("video.player-media")
    expect(video).to_have_count(1)
    page.wait_for_function("document.querySelector('video').readyState >= 2")
    assert video.evaluate("v => v.videoWidth") == 1280
    assert video.evaluate("v => v.duration") == pytest.approx(4, abs=0.1)
    page.get_by_role("slider", name="Evidence time").fill("1")
    page.wait_for_function("Math.abs(document.querySelector('video').currentTime - 1) < 0.1")
    # An actual overlay from overlay_json has been painted, including the decoded mask.
    assert page.locator("canvas.overlay").evaluate(
        "c => c.getContext('2d').getImageData(0, 0, c.width, c.height).data"
        ".some((v, i) => i % 4 === 3 && v > 0)"
    )
    page.get_by_role("button", name="Play evidence timeline").click()
    page.wait_for_function("document.querySelector('video').currentTime > 1.3")
    page.get_by_role("button", name="Pause evidence timeline").click()
    assert not errors, errors


def test_native_multicamera_controls_drive_shared_clock_and_stay_in_step(page, multicamera_server):
    """FR-018: the original 0.2 s drift threshold now uses genuine generated MP4s."""
    url, visit_id = multicamera_server
    page.goto(f"{url}/next/#/visit/{visit_id}")
    wait_ready(page)
    videos = page.locator("video.player-media")
    expect(videos).to_have_count(2)
    page.wait_for_function("[...document.querySelectorAll('video')].every(v=>v.readyState>=2)")
    page.get_by_role("slider", name="Evidence time").fill("1")
    page.wait_for_function(
        "[...document.querySelectorAll('video')].every(v=>Math.abs(v.currentTime-1)<.1)"
    )
    videos.first.focus()
    videos.first.press("Space")
    page.wait_for_function("document.querySelector('video').currentTime>1.4")
    assert float(page.get_by_role("slider", name="Evidence time").input_value()) > 1.3
    times = videos.evaluate_all("elements=>elements.map(v=>v.currentTime)")
    assert max(times) - min(times) < 0.2, times
    videos.first.press("Space")
    expect(page.get_by_role("button", name="Play evidence timeline")).to_be_visible()
    before = float(page.get_by_role("slider", name="Evidence time").input_value())
    page.wait_for_timeout(400)
    after = float(page.get_by_role("slider", name="Evidence time").input_value())
    assert abs(after - before) < 0.2
    assert videos.evaluate_all("elements=>elements.every(v=>v.paused)")
