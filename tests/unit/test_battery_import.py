"""FR-030/032: no battery stream, timestamped import and honest wake gaps."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from tests.fixtures.video.synth import texture_clip
from vigil.ingest.config import load_config
from vigil.models import Box, Track, TrackFrame
from vigil.reasoning.visits import assemble_visits

ROOT = Path(__file__).resolve().parents[2]


def test_battery_without_hub_probe_never_opens_stream():
    from vigil.reolink.probe import probe

    camera = load_config(ROOT / "config/cameras.yaml").camera("side_left")
    camera.hub_present = False

    class NoNetwork:
        async def host_info(self, *args):
            raise AssertionError("no device request in import mode")

        async def check_stream(self, *args):
            raise AssertionError("battery must not stream")

    report = asyncio.run(probe(camera, NoNetwork()))
    assert report.ok
    assert report.source_mode == "import"
    assert report.source_label == "Imported clips"


def test_battery_import_preserves_timestamp_and_requires_review(tmp_path):
    from vigil.ingest.imports import import_clips
    from vigil.ingest.review import privacy_digest

    camera = load_config(ROOT / "config/cameras.yaml").camera("side_left")
    incoming = tmp_path / "import" / camera.id
    incoming.mkdir(parents=True)
    source = texture_clip(incoming / "export.mp4", 0.3, size=(320, 180), audio=False)
    source.with_suffix(".mp4.json").write_text(json.dumps({"start": "2026-11-03T18:14:00-08:00"}))
    with pytest.raises(ValueError, match="owner privacy review"):
        import_clips(camera, incoming, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()
    camera.privacy_reviewed = True
    camera.privacy_still_sha256 = hashlib.sha256(b"generated-still").hexdigest()
    camera.privacy_polygons_sha256 = privacy_digest(camera, camera.privacy)
    manifest = import_clips(camera, incoming, tmp_path / "session")
    assert manifest["source_label"] == "Imported clips"
    assert manifest["session_start"] == "2026-11-03T18:14:00-08:00"
    assert manifest["windows"][0]["t0"] == 0
    assert source.exists()
    assert (tmp_path / "session/windows.json").exists()


def test_battery_wake_and_clock_drift_never_guess_links():
    cfg = load_config(ROOT / "config/cameras.yaml")
    edge = next(e for e in cfg.topology if e.from_ == "porch" and e.to == "side_left")
    edge.transit_measured = True
    edge.min_s = 0
    edge.max_s = 20

    def track(id, cam, start, end):
        return Track(
            id=id,
            camera_id=cam,
            cls="person",
            t_first=start,
            t_last=end,
            frames=[TrackFrame(t=start, box=Box(x1=500, y1=400, x2=550, y2=600))],
        )

    a, b = track("a", "porch", 0, 1), track("b", "side_left", 3, 4)
    result = assemble_visits([], [a, b], {}, [], cfg)
    assert not result.links
    assert any(g.kind == "battery_wake" and not g.resolved for g in result.gaps)
    cfg.camera("side_left").power_profile = "plugin_wifi"
    cfg.camera("side_left").clock_offset_s = 2.01
    result = assemble_visits([], [a, b], {}, [], cfg)
    assert not result.links
    assert any(g.kind == "clock_drift" and not g.resolved for g in result.gaps)
