"""FR-003/NFR-032: real cameras fail closed before ingest, regardless of template masks."""

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.fixtures.video.synth import texture_clip
from vigil.cli import app
from vigil.ingest.config import load_config
from vigil.ingest.privacy import mask_clip, scan_media

ROOT = Path(__file__).resolve().parents[2]


def test_unreviewed_camera_blocked_at_ingest_before_output(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    texture_clip(clips / "front_left_duo.mp4", 0.2, size=(320, 120), audio=False)
    out = tmp_path / "out"
    result = CliRunner().invoke(
        app,
        [
            "ingest",
            str(clips),
            "--no-sync",
            "--config",
            str(ROOT / "config/cameras.yaml"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 1
    assert "owner privacy review" in result.output.lower()
    assert not out.exists()


def test_privacy_review_bound_to_still_and_exact_polygons():
    from vigil.ingest.review import privacy_digest, require_privacy_review

    camera = load_config(ROOT / "config/cameras.yaml").camera("front_left_duo")
    with pytest.raises(ValueError, match="owner privacy review"):
        require_privacy_review(camera)
    camera.privacy_reviewed = True
    camera.privacy_still_sha256 = hashlib.sha256(b"generated-review-still").hexdigest()
    camera.privacy_polygons_sha256 = privacy_digest(camera, camera.privacy)
    require_privacy_review(camera)
    camera.privacy = camera.privacy[:-1]
    with pytest.raises(ValueError, match="changed"):
        require_privacy_review(camera)


def test_duo_export_masks_sky_ridgeline_curb_every_frame(tmp_path):
    camera = load_config(ROOT / "config/cameras.yaml").camera("front_left_duo")
    source = texture_clip(tmp_path / "generated-panorama.mp4", 0.4, size=(1920, 720), audio=False)
    target = mask_clip(source, tmp_path / "export.mp4", camera.privacy, ref_size=(1920, 720))
    for region in ("sky_ridgeline", "curb_numbers", "timestamp_watermark", "opposite_houses_cars"):
        report = scan_media(target, [camera.privacy_regions[region]], ref_size=(1920, 720))
        assert report.frames == 4
        assert report.nonzero_pixels == 0
        assert report.ok
    from scripts.metadata_scan import scan

    assert not scan(target)


def test_ingest_audio_is_error_even_with_reviewed_masks(tmp_path):
    from vigil.ingest.review import require_silent_source

    source = texture_clip(tmp_path / "audio.mp4", 0.3, size=(160, 90), audio=True)
    with pytest.raises(ValueError, match="audio stream"):
        require_silent_source(source)
