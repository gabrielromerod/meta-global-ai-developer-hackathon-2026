"""FR-003: each upload checks its actual media, including malformed inputs."""

from pathlib import Path

import pytest

from vigil.ingest.privacy import PrivacyViolation
from vigil.meta.sam import ensure_uploaded
from vigil.meta.spark import appearance_notes
from vigil.models import Window


class NoUpload:
    def __init__(self):
        self.uploads = []

    def upload(self, path):
        self.uploads.append(path)
        return "fake-file"

    def responses(self, *args, **kwargs):
        return {"output_text": '{"tracks": []}'}


@pytest.mark.parametrize("boundary", ["sam", "spark"])
def test_assert_uploadable_at_every_upload_boundary(tmp_path: Path, boundary: str):
    clip = tmp_path / "invalid.mp4"
    clip.write_bytes(b"unreadable media must never reach an upload")
    client = NoUpload()
    if boundary == "sam":

        def upload():
            return ensure_uploaded(
                client, Window(id="w", camera_id="front", t0=0, t1=1, path=str(clip))
            )
    else:

        def upload():
            return appearance_notes(client, clip, ["T1"])

    with pytest.raises(PrivacyViolation):
        upload()
    assert client.uploads == []


def test_ingest_refuses_missing_privacy_before_writing(tmp_path: Path):
    from typer.testing import CliRunner

    from tests.fixtures.video.synth import blob_clip
    from vigil.cli import app

    clips = tmp_path / "clips"
    clips.mkdir()
    blob_clip(clips / "front.mp4", 0.5, size=(160, 90))
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text("cameras:\n  - id: front\n    name: Front\n", encoding="utf-8")
    out = tmp_path / "windows"
    result = CliRunner().invoke(
        app, ["ingest", str(clips), "--config", str(cfg), "--out", str(out), "--no-sync"]
    )
    assert result.exit_code == 1, result.output
    assert "privacy" in result.output.lower()
    assert "front" in result.output
    assert not out.exists()


def test_camera_privacy_none_needed_is_explicit():
    from vigil.models import CameraCfg

    cam = CameraCfg.model_validate({"id": "front", "name": "Front", "privacy": "none_needed"})
    assert cam.privacy == []
    assert cam.privacy_none_needed


@pytest.mark.parametrize("boundary", ["sam", "spark"])
def test_upload_boundaries_refuse_unmasked_pixels(tmp_path: Path, boundary: str):
    from tests.fixtures.video.synth import texture_clip

    clip = texture_clip(tmp_path / "raw.mp4", 0.3, size=(160, 90))
    polygons = [[(0, 0), (50, 0), (50, 30), (0, 30)]]
    client = NoUpload()
    if boundary == "sam":

        def upload():
            return ensure_uploaded(
                client,
                Window(id="w", camera_id="front", t0=0, t1=0.3, path=str(clip)),
                polygons=polygons,
                ref_size=(160, 90),
            )
    else:

        def upload():
            return appearance_notes(client, clip, ["T1"], polygons=polygons)

    with pytest.raises(PrivacyViolation):
        upload()
    assert not client.uploads
