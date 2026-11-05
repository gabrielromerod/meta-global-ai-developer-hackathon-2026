"""FIXTURE: generated session -> masked bundle -> API video URL and production overlays."""

from datetime import UTC, datetime

import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

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
    from tests.unit.test_glb_import import generated_glb
    from vigil.spatial.glb import import_glb
    from vigil.spatial.scan import world_frame

    import_glb(
        generated_glb(tmp_path / "fixture.glb"),
        settings.data_dir / "spatial",
        frame=world_frame([15, 0, 20], [15, 0, 21], [15, 1, 20]),
    )
    import json

    from tests.unit.test_coverage import cam
    from vigil.spatial.coverage import coverage
    from vigil.spatial.glb import load_glb_scene

    cal = cam("side_left", (2, 2, 1), (2, 0, -2), f=1600)
    (settings.config_path.parent / "calibration.json").write_text(
        json.dumps([cal.model_dump(mode="json")])
    )
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
    assert result["positions"]
    grid = coverage(load_glb_scene(settings.data_dir / "spatial" / "model.glb"), [cal])
    (settings.data_dir / "coverage.json").write_text(json.dumps(grid.to_dict()))
    out = exporter("generated", tmp_path / "bundle", settings=settings, synthetic=True)
    still = out / "media/stills/side_left.png"
    assert still.is_file()
    from vigil.ingest.metadata import scan
    from vigil.ingest.privacy import scan_media

    assert scan(still) == []
    assert scan_media(still, [[(0, 0), (1280, 0), (1280, 60), (0, 60)]]).ok
    with TestClient(create_app(settings, bundle_dir=out)) as browser:
        scenario = browser.get("/api/scenarios/generated").json()
        assert scenario["t0"] == 0
        assert scenario["t1"] == 4
        assert scenario["overlays"]["side_left"]
        assert scenario["cameras"][0]["clip_url"]
        response = browser.get(scenario["cameras"][0]["clip_url"], headers={"Range": "bytes=0-31"})
        assert response.status_code == 206
        assert b"ftyp" in response.content
        twin = browser.get("/api/twin").json()
        assert twin["glb_url"] == "/media/model.glb"
        assert twin["cameras"][0]["position"] == pytest.approx([2, 2, 1])
        assert twin["coverage"]
        assert browser.get(twin["glb_url"]).content.startswith(b"glTF")
    assert result["tracks"]
    owner_settings = settings.model_copy(
        update={
            "mode": "edge",
            "owner_token": SecretStr("synthetic-owner-token"),
            "meta_cache_only": True,
        }
    )
    with TestClient(create_app(owner_settings, bundle_dir=out), client=("127.0.0.1", 50000)) as api:
        unauthenticated = api.get("/api/ui/protection-frames")
        assert unauthenticated.status_code == 200
        assert unauthenticated.json()["frames"] == []
        frames = api.get(
            "/api/ui/protection-frames", headers={"X-Vigil-Owner": "synthetic-owner-token"}
        ).json()["frames"]
        frames = [f for f in frames if f.get("source") != "capture"]  # bundle stills only
        assert len(frames) == 1
        assert frames[0]["camera_id"] == "side_left"
        assert frames[0]["width"] == 1280
        assert frames[0]["height"] == 720
        assert frames[0]["frame_ts"] == 0
        availability = api.get(
            "/api/ui/protection-frames", headers={"X-Vigil-Owner": "synthetic-owner-token"}
        ).json()["live"]
        assert not availability["available"]
        assert "Cache-only" in availability["reason"]
        assert availability["estimate_usd"] > 0
        assert api.get(frames[0]["url"]).content == still.read_bytes()
        import cv2

        tampered = cv2.imread(str(still))
        tampered[:60] = 255
        assert cv2.imwrite(str(still), tampered)
        refused = api.get(
            "/api/ui/protection-frames", headers={"X-Vigil-Owner": "synthetic-owner-token"}
        )
        assert refused.status_code == 200
        assert [f for f in refused.json()["frames"] if f.get("source") != "capture"] == []


def test_export_coverage_preserves_holes():
    from shapely.geometry import Point, Polygon

    grid = {"x0": 0, "z0": 0, "cell_m": 1, "visible": {"front": ["111", "101", "111"]}}
    shapes = export._coverage_polygons(grid)
    polygons = [Polygon(s["polygon_m"], s["holes"]) for s in shapes]
    assert sum(p.area for p in polygons) == 8
    assert not any(p.covers(Point(1.5, 1.5)) for p in polygons)


def test_public_real_session_never_exports_private_glb(tmp_path):
    import hashlib
    import json

    from tests.unit.test_glb_import import generated_glb
    from vigil.ingest.config import load_config
    from vigil.ingest.review import privacy_digest
    from vigil.spatial.glb import import_glb
    from vigil.spatial.scan import world_frame

    settings, _ = generated_session(tmp_path)
    cfg = load_config(settings.config_path)
    cfg.evidence_kind = "real"
    for camera in cfg.cameras:
        camera.evidence_kind = "real"
        camera.privacy_regions = {"timestamp_watermark": camera.privacy[0]}
        camera.privacy_reviewed = True
        camera.privacy_still_sha256 = hashlib.sha256(
            b"generated still; simulated owner review"
        ).hexdigest()
        camera.privacy_polygons_sha256 = privacy_digest(camera, camera.privacy)
    settings.config_path.write_text(json.dumps(cfg.model_dump(mode="json", by_alias=True)))
    with (
        respx.mock as router,
        MetaClient(
            settings, clock=lambda: datetime(2026, 11, 3, tzinfo=UTC), sleep=lambda _: None
        ) as client,
    ):
        mock_models(router)
        process_session("generated", settings=settings, client=client, confirm=True)
    import_glb(
        generated_glb(tmp_path / "private.glb"),
        settings.data_dir / "spatial",
        frame=world_frame([0, 0, 0], [0, 0, 1], [0, 1, 0]),
    )
    out = export.export_session("generated", tmp_path / "public", settings=settings)
    assert not (out / "media/model.glb").exists()
    twin = json.loads((out / "twin.json").read_text())
    assert twin.get("glb_url") is None


def test_bundle_export_rejects_unmasked_media_before_creating_public_directory(
    tmp_path, sample_config
):
    from tests.fixtures.video.synth import texture_clip
    from tests.integration.test_store import _tiny_db
    from vigil.ingest.privacy import PrivacyViolation

    path = tmp_path / "source.db"
    conn = _tiny_db(path)
    conn.commit()
    conn.close()
    raw = texture_clip(tmp_path / "raw.mp4", 0.2, size=(320, 180), audio=False)
    out = tmp_path / "public"
    with pytest.raises(PrivacyViolation):
        export.export_bundle(out, path, config=sample_config, media={"clips/C/side_left.mp4": raw})
    assert not out.exists()


def test_bundle_export_media_path_cannot_escape_destination(tmp_path, sample_config):
    from tests.integration.test_store import _tiny_db

    path = tmp_path / "source.db"
    conn = _tiny_db(path)
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="outside"):
        export.export_bundle(
            tmp_path / "public", path, config=sample_config, media={"../../outside.glb": b"bad"}
        )
    assert not (tmp_path / "outside.glb").exists()


def test_bundle_export_rejects_audio_even_without_identifying_metadata(tmp_path, sample_config):
    import wave

    from tests.integration.test_store import _tiny_db

    source = tmp_path / "audio.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 1600)
    path = tmp_path / "source.db"
    conn = _tiny_db(path)
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="unsupported"):
        export.export_bundle(
            tmp_path / "public", path, config=sample_config, media={"audio.wav": source}
        )


def test_fixture_config_cannot_export_a_real_evidence_label(tmp_path, sample_config):
    import json

    from tests.integration.test_store import _tiny_db

    path = tmp_path / "fixture.db"
    conn = _tiny_db(path)
    conn.commit()
    conn.close()
    out = export.export_bundle(
        tmp_path / "bundle", path, config=sample_config, meta={"synthetic": False}
    )
    assert json.loads((out / "manifest.json").read_text())["synthetic"] is True
