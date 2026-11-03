"""FIXTURE: generated session -> masked bundle -> API video URL and production overlays."""

from datetime import UTC, datetime

import respx
from fastapi.testclient import TestClient

from tests.integration.test_cloud_process import generated_session, mock_models
from vigil.api.app import create_app
from vigil.meta.client import MetaClient
from vigil.pipeline import process_session
from vigil.store import export


def test_serve_uses_explicit_bundle_dir(tmp_path):
    from vigil.api.app import resolve_bundle_dir
    from vigil.settings import Settings

    assert resolve_bundle_dir(Settings(bundle_dir=tmp_path)) == tmp_path


def test_export_session_generated_mp4(tmp_path):
    exporter = getattr(export, "export_session", None)
    assert callable(exporter), "processed sessions need a media-aware export entry"
    settings, _ = generated_session(tmp_path)
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
    out = exporter("generated", tmp_path / "bundle", settings=settings, synthetic=True)
    with TestClient(create_app(settings, bundle_dir=out)) as browser:
        scenario = browser.get("/api/scenarios/generated").json()
        assert scenario["t0"] == 0
        assert scenario["t1"] == 4
        assert scenario["overlays"]["side_left"]
        assert scenario["cameras"][0]["clip_url"]
        response = browser.get(scenario["cameras"][0]["clip_url"], headers={"Range": "bytes=0-31"})
        assert response.status_code == 206
        assert b"ftyp" in response.content
        assert browser.get("/api/twin").status_code == 200
    assert result["tracks"]
