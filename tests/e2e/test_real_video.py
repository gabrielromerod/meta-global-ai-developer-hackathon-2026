"""FIXTURE: actual HTML video decode, seeks and overlays on generated MP4, no cameras."""

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
    settings, _ = generated_session(root)
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
    app = create_app(
        settings.model_copy(update={"mode": "sandbox", "meta_cache_only": True}),
        bundle_dir=bundle,
        live_backend=UnreachableBackend(),
    )
    with running_app(app) as url:
        yield url, result["visits"][0]["id"]


def test_player_generated_mp4_decodes_seeks_and_draws_overlays(page: Page, video_server):
    url, visit_id = video_server
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{url}/#/visit/{visit_id}")
    wait_ready(page)
    video = page.locator("video.player-media")
    expect(video).to_have_count(1)
    page.wait_for_function("document.querySelector('video').readyState >= 2")
    assert video.evaluate("v => v.videoWidth") == 1280
    assert video.evaluate("v => v.duration") == pytest.approx(4, abs=0.1)
    page.evaluate("window.vigil.player.seekAbs(1)")
    page.wait_for_function("Math.abs(document.querySelector('video').currentTime - 1) < 0.1")
    # An actual overlay from overlay_json has been painted, including the decoded mask.
    assert page.locator("canvas.overlay").evaluate(
        "c => c.getContext('2d').getImageData(0, 0, c.width, c.height).data"
        ".some((v, i) => i % 4 === 3 && v > 0)"
    )
    page.click("#play-toggle")
    page.wait_for_function("document.querySelector('video').currentTime > 1.3")
    page.click("#play-toggle")
    assert not errors, errors
