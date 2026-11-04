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
    # side_left is never owner-reviewed in the real config (the front Duos are, Nov 3).
    texture_clip(clips / "side_left.mp4", 0.2, size=(320, 120), audio=False)
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
    # Start unreviewed whatever the live config says: the binding, not the inventory, is tested.
    camera.privacy_reviewed = False
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


def test_upload_guard_checks_metadata_when_extension_is_disguised(tmp_path):
    import subprocess

    import cv2
    import numpy as np

    from vigil.ingest.privacy import PrivacyViolation, assert_uploadable

    image = tmp_path / "generated.jpg"
    assert cv2.imwrite(str(image), np.zeros((24, 24, 3), dtype=np.uint8))
    subprocess.run(
        ["exiftool", "-overwrite_original", "-GPSLatitude=1", str(image)],
        capture_output=True,
        check=True,
    )
    disguised = tmp_path / "generated.dat"
    image.rename(disguised)
    with pytest.raises(PrivacyViolation, match="GPS"):
        assert_uploadable(disguised, [])


def test_still_review_is_invalidated_when_role_zone_geometry_changes():
    from vigil.ingest.review import privacy_digest, require_privacy_review

    camera = load_config(ROOT / "config/cameras.yaml").camera("doorbell")
    camera.privacy_reviewed = True
    camera.privacy_still_sha256 = hashlib.sha256(b"generated still").hexdigest()
    camera.privacy_polygons_sha256 = privacy_digest(camera, camera.privacy)
    require_privacy_review(camera)
    camera.zones["front_door_egress"][0] = (480, 250)
    with pytest.raises(ValueError, match="changed"):
        require_privacy_review(camera)
