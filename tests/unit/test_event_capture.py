"""FR-031/032: event-triggered main clips, pinned sub-stream pre-roll and partial evidence."""

import hashlib
from pathlib import Path

from tests.fixtures.video.synth import texture_clip
from vigil.ingest.config import load_config
from vigil.models import CameraAiEvent
from vigil.reolink.capture import segment_name

ROOT = Path(__file__).resolve().parents[2]


def test_event_clip_main_command_never_requests_audio():
    from vigil.reolink.event_capture import event_clip_cmd

    cmd = event_clip_cmd("rtsp://127.0.0.1/main", Path("event.mp4"), ffmpeg="ffmpeg")
    assert cmd[cmd.index("-allowed_media_types") + 1] == "video"
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    assert "-an" in cmd
    assert cmd[cmd.index("-t") + 1] == "120"
    assert "frag_keyframe" in cmd[cmd.index("-movflags") + 1]


def test_event_capture_preroll_is_pinned_and_partial_clip_kept(tmp_path):
    from vigil.ingest.review import privacy_digest
    from vigil.reolink.event_capture import EventRecorder
    from vigil.reolink.retention import PinIndex

    camera = load_config(ROOT / "config/cameras.yaml").camera("porch")
    camera.privacy_reviewed = True
    camera.privacy_still_sha256 = hashlib.sha256(b"generated-still").hexdigest()
    camera.privacy_polygons_sha256 = privacy_digest(camera, camera.privacy)
    ring = tmp_path / "ring"
    sub = ring / "porch" / segment_name("porch", 100)
    sub.parent.mkdir(parents=True)
    texture_clip(sub, 0.3, size=(320, 180), audio=False)
    main = ring / "main.mp4"
    texture_clip(main, 0.4, size=(640, 360), audio=False)
    event = CameraAiEvent(id="event", camera_id="porch", kind="person", t0=110, t1=111)
    recorder = EventRecorder(ring, tmp_path / "events", camera)
    recorder.pin(event, now=111)
    assert PinIndex(ring).pinned(sub)
    result = recorder.finish(event, main, main_start=110)
    assert result["partial"]
    assert [p["source_quality"] for p in result["parts"]] == ["sub", "main"]
    assert result["parts"][0]["t0"] == 100
    assert result["parts"][1]["t1"] == 110.4
    assert result["gaps"]
    assert main.exists()
    assert all(Path(p["path"]).exists() for p in result["parts"])
