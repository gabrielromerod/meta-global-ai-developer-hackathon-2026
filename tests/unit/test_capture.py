"""Unit: continuous capture (FR-031, NFR-029, NFR-033).

ffmpeg command shape (stream copy, no audio, 10 s segments, timestamped names), the
supervisor restarting ffmpeg after a dropped stream with bounded backoff and recorded
outages (fake process runner, fake clock), the 48 h ring cleanup and the window builder
(segment + last 2 s of the previous one, FR-004/FR-007 overlap). No camera, no ffmpeg run.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from vigil.models import CameraCfg, CameraSource
from vigil.reolink import capture
from vigil.reolink.capture import (
    CaptureSupervisor,
    Outage,
    Segment,
    build_window,
    cleanup_ring,
    ffmpeg_segment_cmd,
    find_gaps,
    list_segments,
    parse_segment_time,
    restream_url,
    segment_name,
)
from vigil.reolink.probe import rtsp_url

PASSWORD = "pw-Zx9!q"


# ---------------------------------------------------------------------------
# ffmpeg command
# ---------------------------------------------------------------------------


def _cmd(url: str = "rtsp://127.0.0.1:8554/front") -> list[str]:
    return ffmpeg_segment_cmd(url, Path("data/segments"), "front", segment_s=10, ffmpeg="ffmpeg")


def _after(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_cmd_stream_copy_without_audio() -> None:
    cmd = _cmd()
    assert _after(cmd, "-c:v") == "copy"
    assert "-an" in cmd
    assert "-dn" in cmd
    assert "libx264" not in cmd  # NFR-033: no re-encode on the capture path


def test_cmd_segment_muxer_10s_with_strftime_names() -> None:
    cmd = _cmd()
    assert _after(cmd, "-f") == "segment"
    assert _after(cmd, "-segment_time") == "10"
    assert _after(cmd, "-strftime") == "1"
    assert _after(cmd, "-reset_timestamps") == "1"
    assert _after(cmd, "-segment_atclocktime") == "1"
    out = cmd[-1].replace("\\", "/")
    assert out.startswith("data/segments/front/front_")
    assert "%Y%m%dT%H%M%SZ" in out


def test_cmd_rtsp_uses_tcp_and_socket_timeout() -> None:
    cmd = _cmd()
    assert _after(cmd, "-rtsp_transport") == "tcp"
    assert int(_after(cmd, "-timeout")) > 0
    assert _after(cmd, "-i") == "rtsp://127.0.0.1:8554/front"


def test_cmd_http_flv_uses_reconnect_flags() -> None:
    cmd = ffmpeg_segment_cmd("http://192.0.2.1/flv?x", Path("o"), "front", ffmpeg="ffmpeg")
    assert _after(cmd, "-reconnect") == "1"
    assert _after(cmd, "-reconnect_streamed") == "1"
    assert _after(cmd, "-reconnect_on_network_error") == "1"
    assert int(_after(cmd, "-reconnect_delay_max")) <= 30
    assert "-rtsp_transport" not in cmd


def test_cmd_accepts_stream_url_and_resolves_ffmpeg(monkeypatch) -> None:
    monkeypatch.setattr(capture, "ffmpeg_bin", lambda: "C:/fake/ffmpeg.exe")
    url = rtsp_url("192.0.2.5", "u", PASSWORD)
    cmd = ffmpeg_segment_cmd(url, Path("o"), "front")
    assert cmd[0] == "C:/fake/ffmpeg.exe"
    encoded = quote(PASSWORD, safe="")
    assert encoded in " ".join(cmd)  # ffmpeg needs the real URL...
    assert encoded not in capture.describe_cmd(cmd)  # ...but logs never see it
    assert "Zx9" not in capture.describe_cmd(cmd)


def test_restream_url_points_at_go2rtc() -> None:
    cam = CameraCfg(id="backyard", name="Backyard", source=CameraSource(host_env="X"))
    assert restream_url(cam) == "rtsp://127.0.0.1:8554/backyard"
    assert restream_url(cam, stream="sub") == "rtsp://127.0.0.1:8554/backyard_sub"


# ---------------------------------------------------------------------------
# Segment names and listing
# ---------------------------------------------------------------------------


def test_segment_name_round_trip() -> None:
    t = 1_793_000_000.0
    name = segment_name("front", t)
    assert name.startswith("front_")
    assert name.endswith("Z.mp4")
    assert parse_segment_time(Path(name)) == t


def test_parse_segment_time_rejects_foreign_files() -> None:
    assert parse_segment_time(Path("notes.txt")) is None
    assert parse_segment_time(Path("front_garbage.mp4")) is None


def _touch_segments(d: Path, cam: str, starts: list[float]) -> list[Path]:
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for t in starts:
        p = d / segment_name(cam, t)
        p.write_bytes(b"\x00")
        out.append(p)
    return out


def test_list_segments_sorted_with_durations(tmp_path: Path) -> None:
    base = 1_793_000_000.0
    _touch_segments(tmp_path / "front", "front", [base + 20, base, base + 10])
    segs = list_segments(tmp_path / "front", segment_s=10)
    assert [s.t0 - base for s in segs] == [0, 10, 20]
    assert [s.t1 - s.t0 for s in segs] == [10, 10, 10]


def test_find_gaps_reports_holes_over_tolerance() -> None:
    segs = [Segment(Path("a"), 0, 10), Segment(Path("b"), 10.4, 20), Segment(Path("c"), 25, 35)]
    gaps = find_gaps(segs, tolerance_s=1.0)
    assert gaps == [(20, 25)]


# ---------------------------------------------------------------------------
# Window builder (FR-031, FR-004 overlap)
# ---------------------------------------------------------------------------


def test_window_is_segment_plus_last_2s_of_previous() -> None:
    segs = [Segment(Path("s0.mp4"), 100, 110), Segment(Path("s1.mp4"), 110, 120)]
    t0, t1, sources = build_window(segs, 1)
    assert (t0, t1) == (108, 120)
    assert sources == [(Path("s0.mp4"), 8.0, 10.0), (Path("s1.mp4"), 0.0, 10.0)]


def test_first_segment_has_no_overlap() -> None:
    segs = [Segment(Path("s0.mp4"), 100, 110)]
    assert build_window(segs, 0) == (100, 110, [(Path("s0.mp4"), 0.0, 10.0)])


def test_no_overlap_across_a_capture_gap() -> None:
    """A previous segment that ended long before is not glued on (that time was an outage)."""
    segs = [Segment(Path("s0.mp4"), 100, 110), Segment(Path("s1.mp4"), 130, 140)]
    t0, _t1, sources = build_window(segs, 1)
    assert t0 == 130
    assert len(sources) == 1


def test_short_previous_segment_contributes_what_it_has() -> None:
    segs = [Segment(Path("s0.mp4"), 109, 110), Segment(Path("s1.mp4"), 110, 120)]
    t0, _, sources = build_window(segs, 1, overlap_s=2.0)
    assert t0 == 109
    assert sources[0] == (Path("s0.mp4"), 0.0, 1.0)


def test_consecutive_windows_overlap_by_exactly_2s() -> None:
    segs = [Segment(Path(f"s{i}"), 100 + 10 * i, 110 + 10 * i) for i in range(5)]
    windows = [build_window(segs, i) for i in range(5)]
    for (_, a1, _), (b0, _, _) in itertools.pairwise(windows):
        assert a1 - b0 == pytest.approx(2.0)


def test_window_index_out_of_range() -> None:
    with pytest.raises(IndexError):
        build_window([], 0)


# ---------------------------------------------------------------------------
# 48 h ring cleanup
# ---------------------------------------------------------------------------


def test_cleanup_ring_deletes_only_segments_older_than_retention(tmp_path: Path) -> None:
    now = 1_793_000_000.0
    hour = 3600.0
    old = _touch_segments(tmp_path / "front", "front", [now - 49 * hour, now - 48.1 * hour])
    keep = _touch_segments(tmp_path / "front", "front", [now - 47 * hour, now - 60])
    other = tmp_path / "front" / "keep_me.json"
    other.write_text("{}")
    deleted = cleanup_ring(tmp_path, retention_s=48 * hour, now=now)
    assert sorted(deleted) == sorted(old)
    assert all(not p.exists() for p in old)
    assert all(p.exists() for p in keep)
    assert other.exists()


def test_cleanup_ring_falls_back_to_mtime_for_unnamed_media(tmp_path: Path) -> None:
    now = time.time()
    stale = tmp_path / "back" / "manual.mp4"
    stale.parent.mkdir()
    stale.write_bytes(b"\x00")
    os.utime(stale, (now - 50 * 3600, now - 50 * 3600))
    assert cleanup_ring(tmp_path, now=now) == [stale]


# ---------------------------------------------------------------------------
# Supervisor: restart after a dropped stream (spec 12.1 "Integration: Reolink")
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s
        await asyncio.sleep(0)


class FakeProc:
    def __init__(self, clock: FakeClock, runs_for: float, rc: int) -> None:
        self.clock, self.runs_for, self.rc = clock, runs_for, rc
        self.killed = False

    async def wait(self) -> int:
        self.clock.t += self.runs_for
        await asyncio.sleep(0)
        return self.rc

    def kill(self) -> None:
        self.killed = True


class FakeRunner:
    """Scripted ffmpeg lifetimes: (seconds it runs, exit code)."""

    def __init__(self, clock: FakeClock, script: list[tuple[float, int]]) -> None:
        self.clock, self.script = clock, list(script)
        self.started: list[float] = []
        self.cmds: list[list[str]] = []

    async def start(self, cmd: list[str]) -> FakeProc:
        self.started.append(self.clock.t)
        self.cmds.append(cmd)
        runs_for, rc = self.script.pop(0) if self.script else (0.0, 0)
        return FakeProc(self.clock, runs_for, rc)


def _supervisor(clock: FakeClock, runner: FakeRunner, **kw) -> CaptureSupervisor:
    return CaptureSupervisor(
        camera_id="side_left",
        cmd_factory=lambda: ["ffmpeg", "-i", "rtsp://127.0.0.1:8554/side_left"],
        runner=runner,
        clock=clock,
        sleep=clock.sleep,
        **kw,
    )


def test_supervisor_restarts_after_dropped_stream_and_records_outage() -> None:
    """Cable pulled at t=1600 for 40 s: ffmpeg exits, retries fail fast, then it recovers."""
    clock = FakeClock(1000.0)
    script = [(600.0, 1)] + [(5.0, 1)] * 4 + [(3600.0, 0)]
    runner = FakeRunner(clock, script)
    sup = _supervisor(clock, runner, max_restarts=5)
    asyncio.run(sup.run())
    assert len(runner.started) == 6
    assert all(s <= 10.0 for s in clock.sleeps)  # backoff capped well inside 30 s
    assert len(sup.outages) == 1  # consecutive failed attempts merge into one outage
    out = sup.outages[0]
    assert isinstance(out, Outage)
    assert out.camera_id == "side_left"
    assert out.t0 == 1600.0
    assert out.t1 == runner.started[-1]


def test_reconnects_within_30s_after_the_stream_returns() -> None:
    """FR-031 acceptance: whenever the camera is back, ffmpeg is running again in < 30 s."""
    clock = FakeClock(0.0)
    back_at = 0.0 + 600 + 5 * 20  # stream returns after 20 failed attempts' worth of time
    script = [(600.0, 1)] + [(5.0, 1)] * 20 + [(100.0, 0)]
    runner = FakeRunner(clock, script)
    sup = _supervisor(clock, runner, max_restarts=21)
    asyncio.run(sup.run())
    first_ok = next(t for t in runner.started if t >= back_at)
    gap_between_attempts = max(
        b - a for a, b in zip(runner.started, runner.started[1:], strict=False) if a >= 600
    )
    assert gap_between_attempts <= 5.0 + 10.0
    assert first_ok - back_at < 30.0


def test_backoff_grows_then_resets_after_a_stable_run() -> None:
    clock = FakeClock(0.0)
    script = [(1.0, 1), (1.0, 1), (1.0, 1), (500.0, 1), (1.0, 1)]
    runner = FakeRunner(clock, script)
    sup = _supervisor(clock, runner, max_restarts=4, backoff=(1.0, 2.0, 4.0, 8.0))
    asyncio.run(sup.run())
    assert clock.sleeps[:3] == [1.0, 2.0, 4.0]
    assert clock.sleeps[3] == 1.0  # the 500 s run counts as stable: backoff resets


def test_stop_ends_supervisor_without_outage() -> None:
    clock = FakeClock(0.0)
    runner = FakeRunner(clock, [(10.0, 0)] * 10)
    sup = _supervisor(clock, runner)

    async def go() -> None:
        task = asyncio.create_task(sup.run())
        await asyncio.sleep(0)
        sup.stop()
        await task

    asyncio.run(go())
    assert sup.outages == [] or all(o.t1 is not None for o in sup.outages)


def test_watchdog_kills_stalled_ffmpeg(tmp_path: Path) -> None:
    """ffmpeg can hang without exiting; no new segment for 3 segments' time -> kill."""
    clock = FakeClock(0.0)

    class HangingProc(FakeProc):
        async def wait(self) -> int:
            while not self.killed:
                await asyncio.sleep(0)
            return 255

    class HangRunner(FakeRunner):
        async def start(self, cmd):
            self.started.append(clock.t)
            return HangingProc(clock, 0, 255)

    runner = HangRunner(clock, [])
    sup = _supervisor(clock, runner, max_restarts=0, stall_s=30.0, latest_segment_time=lambda: 0.0)

    async def advance() -> None:
        task = asyncio.create_task(sup.run())
        for _ in range(50):
            clock.t += 5
            await asyncio.sleep(0)
            if task.done():
                break
        await task

    asyncio.run(advance())
    assert sup.stalls == 1


def test_run_capture_supervises_every_camera(tmp_path: Path, sample_config) -> None:
    clock = FakeClock(0.0)
    runner = FakeRunner(clock, [(1.0, 0)] * 20)
    asyncio.run(
        capture.run_capture(
            sample_config.cameras,
            tmp_path,
            runner=runner,
            clock=clock,
            sleep=clock.sleep,
            max_restarts=0,
            ffmpeg="ffmpeg",
        )
    )
    inputs = sorted(_after(c, "-i") for c in runner.cmds)
    assert inputs == sorted(f"rtsp://127.0.0.1:8554/{c.id}" for c in sample_config.cameras)
    assert all((tmp_path / c.id).is_dir() for c in sample_config.cameras)
