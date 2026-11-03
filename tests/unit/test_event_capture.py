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


def test_main_capture_normalizes_h264_height_and_wifi_bitrate(tmp_path):
    import subprocess

    from vigil.ingest.media import probe
    from vigil.reolink.event_capture import event_clip_cmd
    from vigil.settings import ffmpeg_bin

    source = tmp_path / "oversized.mp4"
    subprocess.run(
        [
            ffmpeg_bin(),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=2880x1620:rate=10:duration=0.3",
            "-c:v",
            "mpeg4",
            "-an",
            str(source),
        ],
        capture_output=True,
        check=True,
    )
    output = tmp_path / "main.mp4"
    command = event_clip_cmd(str(source), output)
    assert 2_000_000 <= int(command[command.index("-b:v") + 1]) <= 4_000_000
    assert int(command[command.index("-maxrate") + 1]) <= 4_000_000
    subprocess.run(command, capture_output=True, check=True)
    info = probe(output)
    assert info.video_codec == "h264"
    assert info.height == 1440
    assert info.audio_streams == 0


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


def test_event_recorder_preserves_previous_partial_attempt(tmp_path):
    from vigil.reolink.event_capture import EventRecorder

    camera = load_config(ROOT / "config/cameras.yaml").camera("porch")
    camera.evidence_kind = "fixture"
    ring = tmp_path / "ring"
    ring.mkdir()
    first = texture_clip(ring / "first.mp4", 0.2, size=(320, 180), audio=False)
    second = texture_clip(ring / "second.mp4", 0.3, size=(640, 360), audio=False)
    recorder = EventRecorder(ring, tmp_path / "events", camera)
    event = CameraAiEvent(id="retry", camera_id="porch", kind="person", t0=110, t1=112)
    prior = recorder.finish(event, first, main_start=110)
    path = Path(prior["parts"][-1]["path"])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    later = recorder.finish(event, second, main_start=111)
    assert later["parts"][-1]["path"] != str(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_partial_open_event_records_an_unknown_end_without_guessing_duration(tmp_path):
    from vigil.reolink.event_capture import EventRecorder

    camera = load_config(ROOT / "config/cameras.yaml").camera("porch")
    camera.evidence_kind = "fixture"
    ring = tmp_path / "ring"
    ring.mkdir()
    main = texture_clip(ring / "main.mp4", 0.2, size=(320, 180), audio=False)
    result = EventRecorder(ring, tmp_path / "events", camera).finish(
        CameraAiEvent(id="open", camera_id="porch", kind="person", t0=110), main, main_start=110
    )
    assert result["partial"]
    assert any(g["t1"] is None and not g["resolved"] for g in result["gaps"])


def test_event_service_excludes_batteries_and_pins_main_before_recording(tmp_path, monkeypatch):
    import asyncio

    from pydantic import SecretStr

    from vigil.reolink import event_capture
    from vigil.reolink.probe import HostInfo
    from vigil.reolink.retention import PinIndex

    cfg = load_config(ROOT / "config/cameras.yaml")
    camera = cfg.camera("porch")
    camera.evidence_kind = "fixture"
    monkeypatch.setenv("REOLINK_PORCH_HOST", "192.0.2.1")
    monkeypatch.setenv("REOLINK_USER", "fixture")
    monkeypatch.setenv("REOLINK_PASSWORD", "fixture-only")
    seen = []

    async def ring(cameras, *args, **kwargs):
        assert [c.id for c in cameras] == ["porch"]
        assert cameras[0].source.stream == "sub"
        seen.append("sub")
        await asyncio.Future()

    monkeypatch.setattr(event_capture, "run_capture", ring)

    class Adapter:
        async def host_info(self, *args):
            return HostInfo(
                sources_resolved=True,
                stream_sources={0: {"main": SecretStr("rtsp://127.0.0.1/main")}},
            )

    class Proc:
        def __init__(self):
            self.done = asyncio.Event()

        async def wait(self):
            await self.done.wait()
            return 0

        def kill(self):
            self.done.set()

    class Runner:
        async def start(self, command):
            source = Path(command[-1])
            assert PinIndex(tmp_path / "capture/ring").pinned(source)
            assert command[command.index("-i") + 1].endswith("/main")
            texture_clip(source, 0.2, size=(320, 180), audio=False)
            seen.append("main")
            return Proc()

    async def events():
        yield CameraAiEvent(id="sensor", camera_id="porch", kind="person", t0=110)

    asyncio.run(
        event_capture.run_event_capture(
            [camera, cfg.camera("side_left")],
            tmp_path / "capture",
            events=events(),
            adapter=Adapter(),
            runner=Runner(),
            free_floor_bytes=0,
            clock=lambda: 110,
        )
    )
    assert seen == ["sub", "main"]
    assert list((tmp_path / "capture/events").rglob("capture.json"))


def test_capture_parts_write_a_processable_relative_clock_session(tmp_path):
    import json

    from vigil.models import Window
    from vigil.reolink.event_capture import EventRecorder

    camera = load_config(ROOT / "config/cameras.yaml").camera("porch")
    camera.evidence_kind = "fixture"
    ring = tmp_path / "ring"
    ring.mkdir()
    source = texture_clip(ring / "main.mp4", 0.2, size=(320, 180), audio=False)
    result = EventRecorder(ring, tmp_path / "windows", camera).finish(
        CameraAiEvent(id="open", camera_id="porch", kind="person", t0=110), source, main_start=110
    )
    folder = Path(result["parts"][0]["path"]).parent
    windows = [Window.model_validate(w) for w in json.loads((folder / "windows.json").read_text())]
    metadata = json.loads((folder / "session.json").read_text())
    assert windows[0].t0 == 10
    assert metadata["session_start"] == "1970-01-01T00:01:40+00:00"
    assert metadata["camera_ai_events"][0]["t0"] == 10
    assert metadata["truncated_after"]["porch"] == 10.2
    assert result["session_id"] == folder.name
