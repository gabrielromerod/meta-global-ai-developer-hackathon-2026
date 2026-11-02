"""Continuous capture: 10 s stream-copy segments, no audio, 48 h ring (FR-031, NFR-029/033).

Pipeline on the edge machine (spec 6 "Near-real-time pipeline"):

1. go2rtc (`infra/go2rtc.yaml`) holds one connection per camera and re-serves it on
   `rtsp://127.0.0.1:8554/<camera_id>` (localhost needs no auth), so capture reads the
   restream by default and never handles camera credentials.
2. One ffmpeg per camera writes contiguous 10 s segments by stream copy with audio, data
   and subtitle streams dropped (`-an -dn -sn`), aligned to the wall clock and named
   `<camera>_<YYYYmmddTHHMMSS>Z.mp4` (UTC; the runner sets `TZ=UTC0` for ffmpeg).
   Segments are fragmented MP4 so a segment cut short by a crash is still readable.
3. `CaptureSupervisor` restarts ffmpeg when it exits (dropped stream, cable pull) with a
   capped backoff, kills it when no new segment appears for `stall_s`, and records each
   outage interval (UC-11: "the time is stored as an outage gap").
4. `cleanup_ring()` deletes raw segments older than 48 h.
5. `build_window()` gives a processing window: a segment plus the last 2 s of the one
   before, the overlap track stitching needs (FR-004, FR-007).

Every log line goes through `redact()`; `describe_cmd()` is the only way a command is
logged.
"""

from __future__ import annotations

import asyncio
import calendar
import contextlib
import itertools
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vigil.models import CameraCfg
from vigil.reolink.probe import StreamUrl, camera_rtsp_url, redact
from vigil.settings import ffmpeg_bin

log = logging.getLogger(__name__)

SEGMENT_S = 10
RETENTION_S = 48 * 3600
OVERLAP_S = 2.0
RESTREAM_BASE = "rtsp://127.0.0.1:8554"
NAME_PATTERN = "%Y%m%dT%H%M%SZ"
MEDIA_SUFFIXES = (".mp4", ".mkv", ".ts")
DEFAULT_BACKOFF: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 10.0)
"""Capped at 10 s so a returning stream is picked up well inside the 30 s target."""

_NAME_RE = re.compile(r"^(?P<cam>.+)_(?P<ts>\d{8}T\d{6})Z\.(?:mp4|mkv|ts)$")


# ---------------------------------------------------------------------------
# ffmpeg command
# ---------------------------------------------------------------------------


def restream_url(cam: CameraCfg, stream: str = "main", base: str = RESTREAM_BASE) -> str:
    """go2rtc restream for this camera: `<base>/<id>` (main) or `<base>/<id>_sub`."""
    return f"{base}/{cam.id}" if stream == "main" else f"{base}/{cam.id}_{stream}"


def ffmpeg_segment_cmd(
    url: str | StreamUrl,
    out_dir: Path,
    camera_id: str,
    segment_s: int = SEGMENT_S,
    *,
    ffmpeg: str | None = None,
    io_timeout_us: int = 5_000_000,
) -> list[str]:
    """ffmpeg argv for contiguous stream-copy segments without audio.

    RTSP input uses TCP and a socket timeout so a pulled cable makes ffmpeg exit (the
    supervisor restarts it). HTTP-FLV input (the spec 6 fallback) uses ffmpeg's HTTP
    reconnect options, which only apply to http(s).
    """
    src = url.secret() if isinstance(url, StreamUrl) else str(url)
    binary = ffmpeg or ffmpeg_bin()
    if src.startswith(("rtsp://", "rtsps://")):
        input_opts = ["-rtsp_transport", "tcp", "-timeout", str(io_timeout_us)]
    elif src.startswith(("http://", "https://")):
        input_opts = [
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1",
            "-reconnect_delay_max", "10",
            "-rw_timeout", str(io_timeout_us),
        ]  # fmt: skip
    else:
        input_opts = []
    pattern = Path(out_dir) / camera_id / f"{camera_id}_{NAME_PATTERN}.mp4"
    return [
        binary,
        "-hide_banner",
        "-nostdin",
        "-loglevel", "warning",
        *input_opts,
        "-fflags", "+genpts",
        "-i", src,
        "-map", "0:v:0",
        "-c:v", "copy",
        "-an", "-dn", "-sn",
        "-f", "segment",
        "-segment_time", str(segment_s),
        "-segment_atclocktime", "1",
        "-segment_format", "mp4",
        "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof",
        "-reset_timestamps", "1",
        "-strftime", "1",
        str(pattern),
    ]  # fmt: skip


def describe_cmd(cmd: Sequence[str]) -> str:
    """Loggable form of a command: credentials redacted."""
    return redact(" ".join(cmd))


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Segment:
    path: Path
    t0: float
    """Start, epoch seconds (UTC), from the file name."""
    t1: float

    @property
    def duration(self) -> float:
        return self.t1 - self.t0


def segment_name(camera_id: str, t: float, suffix: str = ".mp4") -> str:
    return f"{camera_id}_{time.strftime(NAME_PATTERN, time.gmtime(t))}{suffix}"


def parse_segment_time(path: Path) -> float | None:
    m = _NAME_RE.match(Path(path).name)
    if not m:
        return None
    try:
        return float(calendar.timegm(time.strptime(m["ts"], "%Y%m%dT%H%M%S")))
    except ValueError:
        return None


def list_segments(cam_dir: Path, segment_s: float = SEGMENT_S) -> list[Segment]:
    """Segments in one camera folder, oldest first. A segment ends at the next one's start
    when that comes sooner than `segment_s`, otherwise after `segment_s`."""
    named = sorted(
        (t, p)
        for p in Path(cam_dir).glob("*")
        if p.is_file() and (t := parse_segment_time(p)) is not None
    )
    out: list[Segment] = []
    for i, (t, p) in enumerate(named):
        end = t + segment_s
        if i + 1 < len(named):
            end = min(end, named[i + 1][0])
        out.append(Segment(p, t, end))
    return out


def find_gaps(segments: Sequence[Segment], tolerance_s: float = 1.0) -> list[tuple[float, float]]:
    """Holes between consecutive segments longer than `tolerance_s` (NFR-029: none > 1 s)."""
    return [(a.t1, b.t0) for a, b in itertools.pairwise(segments) if b.t0 - a.t1 > tolerance_s]


def build_window(
    segments: Sequence[Segment],
    index: int,
    overlap_s: float = OVERLAP_S,
    max_gap_s: float = 1.0,
) -> tuple[float, float, list[tuple[Path, float, float]]]:
    """Window for `segments[index]`: the segment plus the last `overlap_s` of the previous
    one when that one is contiguous (gap <= `max_gap_s`). Pure.

    Returns (t0, t1, sources) where each source is (path, start, end) in seconds from the
    start of that file, in playback order.
    """
    if not 0 <= index < len(segments):
        raise IndexError(f"segment index {index} out of range ({len(segments)} segments)")
    seg = segments[index]
    sources: list[tuple[Path, float, float]] = []
    t0 = float(seg.t0)
    if index > 0:
        prev = segments[index - 1]
        if seg.t0 - prev.t1 <= max_gap_s:
            take = min(overlap_s, prev.duration)
            if take > 0:
                sources.append((prev.path, float(prev.duration - take), float(prev.duration)))
                t0 = float(prev.t1 - take)
    sources.append((seg.path, 0.0, float(seg.duration)))
    return t0, float(seg.t1), sources


def cleanup_ring(
    root: Path, retention_s: float = RETENTION_S, now: float | None = None
) -> list[Path]:
    """Delete media files under `root` older than `retention_s` (48 h by default).

    Age comes from the segment name, or the file's mtime for media without one. Other
    files are never touched. Returns the deleted paths.
    """
    now = time.time() if now is None else now
    cutoff = now - retention_s
    deleted: list[Path] = []
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file() or p.suffix.lower() not in MEDIA_SUFFIXES:
            continue
        t = parse_segment_time(p)
        if t is None:
            t = p.stat().st_mtime
        if t < cutoff:
            try:
                p.unlink()
            except OSError as err:  # pragma: no cover - file in use on Windows
                log.warning("could not delete %s: %s", p.name, err)
                continue
            deleted.append(p)
    if deleted:
        log.info(
            "ring cleanup: deleted %d segments older than %.0f h", len(deleted), retention_s / 3600
        )
    return deleted


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


@dataclass
class Outage:
    """A capture outage on one camera (UC-11): no segments between t0 and t1 (epoch s)."""

    camera_id: str
    t0: float
    t1: float | None = None
    attempts: int = 0


class Proc(Protocol):
    async def wait(self) -> int: ...

    def kill(self) -> None: ...


class ProcessRunner(Protocol):
    async def start(self, cmd: list[str]) -> Proc: ...


class _AsyncioProc:
    def __init__(self, proc: asyncio.subprocess.Process, camera_id: str) -> None:
        self.proc = proc
        self.camera_id = camera_id
        self._drain = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        async for line in self.proc.stderr:
            text = line.decode(errors="replace").strip()
            if text:
                log.debug("ffmpeg[%s] %s", self.camera_id, redact(text))

    async def wait(self) -> int:
        rc = await self.proc.wait()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._drain, 2.0)
        return rc

    def kill(self) -> None:
        if self.proc.returncode is None:
            self.proc.kill()


class SubprocessRunner:
    """Real runner: asyncio subprocess, stdin closed, stderr drained into the redacted log."""

    def __init__(self, camera_id: str = "?") -> None:
        self.camera_id = camera_id

    async def start(self, cmd: list[str]) -> Proc:
        env = {**os.environ, "TZ": "UTC0"}  # strftime segment names are UTC
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        return _AsyncioProc(proc, self.camera_id)


class CaptureSupervisor:
    """Keeps one ffmpeg running for one camera; restarts with capped backoff (FR-031).

    A run that lasts at least `stable_s` counts as healthy: it closes any open outage (at
    the run's start) and resets the backoff. A run shorter than that is a failed attempt:
    the outage that began when the last healthy run exited stays open.
    """

    def __init__(
        self,
        camera_id: str,
        cmd_factory: Callable[[], list[str]],
        runner: ProcessRunner,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        backoff: Sequence[float] = DEFAULT_BACKOFF,
        stable_s: float = 60.0,
        max_restarts: int | None = None,
        stall_s: float | None = None,
        latest_segment_time: Callable[[], float | None] | None = None,
        check_every_s: float = SEGMENT_S,
    ) -> None:
        self.camera_id = camera_id
        self.cmd_factory = cmd_factory
        self.runner = runner
        self.clock = clock
        self.sleep = sleep
        self.backoff = tuple(backoff) or DEFAULT_BACKOFF
        self.stable_s = stable_s
        self.max_restarts = max_restarts
        self.stall_s = stall_s
        self.latest_segment_time = latest_segment_time
        self.check_every_s = check_every_s
        self.outages: list[Outage] = []
        self.restarts = 0
        self.stalls = 0
        self.gave_up_at: float | None = None
        self._stop = False
        self._proc: Proc | None = None

    def stop(self) -> None:
        self._stop = True
        if self._proc is not None:
            self._proc.kill()

    @property
    def open_outage(self) -> Outage | None:
        if self.outages and self.outages[-1].t1 is None:
            return self.outages[-1]
        return None

    async def _wait_with_watchdog(self, proc: Proc, started: float) -> int:
        if self.stall_s is None or self.latest_segment_time is None:
            return await proc.wait()
        wait_task = asyncio.ensure_future(proc.wait())
        try:
            while not wait_task.done():
                tick = asyncio.ensure_future(self.sleep(self.check_every_s))
                await asyncio.wait({wait_task, tick}, return_when=asyncio.FIRST_COMPLETED)
                if wait_task.done():
                    tick.cancel()
                    break
                last = self.latest_segment_time()
                ref = max(last or 0.0, started)
                if self.clock() - ref > self.stall_s:
                    self.stalls += 1
                    log.warning(
                        "capture %s stalled: no segment for %.0f s, killing ffmpeg",
                        self.camera_id,
                        self.clock() - ref,
                    )
                    proc.kill()
                    break
            return await wait_task
        finally:
            if not wait_task.done():  # pragma: no cover - cancelled from outside
                wait_task.cancel()

    async def run(self) -> list[Outage]:
        failures = 0
        while not self._stop:
            cmd = self.cmd_factory()
            started = self.clock()
            log.info("capture %s: starting %s", self.camera_id, describe_cmd(cmd[1:]))
            self._proc = await self.runner.start(cmd)
            rc = await self._wait_with_watchdog(self._proc, started)
            self._proc = None
            ended = self.clock()
            if self._stop:
                break
            healthy = ended - started >= self.stable_s
            if healthy:
                if (o := self.open_outage) is not None:
                    o.t1 = started
                    log.info(
                        "capture %s: recovered after %.1f s outage", self.camera_id, o.t1 - o.t0
                    )
                failures = 0
            if self.max_restarts is not None and self.restarts >= self.max_restarts:
                self.gave_up_at = ended
                log.error("capture %s: ffmpeg exited (rc=%s), giving up", self.camera_id, rc)
                break
            if healthy or self.open_outage is None:
                self.outages.append(Outage(self.camera_id, t0=ended))
            outage = self.open_outage
            if outage is not None:
                outage.attempts += 1
            delay = self.backoff[min(failures, len(self.backoff) - 1)]
            log.warning(
                "capture %s: ffmpeg exited rc=%s after %.1f s; restart in %.0f s",
                self.camera_id,
                rc,
                ended - started,
                delay,
            )
            failures += 1
            self.restarts += 1
            await self.sleep(delay)
        return self.outages


async def run_capture(
    cams: list[CameraCfg],
    out_dir: Path,
    segment_s: int = SEGMENT_S,
    *,
    runner: ProcessRunner | None = None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_restarts: int | None = None,
    ffmpeg: str | None = None,
    via_restreamer: bool = True,
    restream_base: str = RESTREAM_BASE,
    retention_s: float = RETENTION_S,
    cleanup_every_s: float = 600.0,
    stall_factor: float = 3.0,
) -> list[CaptureSupervisor]:
    """Capture every camera until stopped (or until `max_restarts` is exhausted).

    Reads the go2rtc restream by default; `via_restreamer=False` reads the camera directly
    with credentials from the environment. Returns the supervisors (outages, restarts).
    """
    out_dir = Path(out_dir)
    ff = ffmpeg or ffmpeg_bin()
    sups: list[CaptureSupervisor] = []
    for cam in cams:
        cam_dir = out_dir / cam.id
        cam_dir.mkdir(parents=True, exist_ok=True)
        url: str | StreamUrl = (
            restream_url(cam, base=restream_base) if via_restreamer else camera_rtsp_url(cam)
        )

        def factory(url: str | StreamUrl = url, cam_id: str = cam.id) -> list[str]:
            return ffmpeg_segment_cmd(url, out_dir, cam_id, segment_s, ffmpeg=ff)

        def latest(cam_dir: Path = cam_dir) -> float | None:
            segs = list_segments(cam_dir, segment_s)
            return segs[-1].t0 if segs else None

        sups.append(
            CaptureSupervisor(
                cam.id,
                factory,
                runner or SubprocessRunner(cam.id),
                clock=clock,
                sleep=sleep,
                max_restarts=max_restarts,
                stall_s=stall_factor * segment_s,
                latest_segment_time=latest,
                check_every_s=segment_s,
            )
        )

    async def ring() -> None:
        while True:
            cleanup_ring(out_dir, retention_s, now=clock())
            await sleep(cleanup_every_s)

    ring_task = asyncio.ensure_future(ring())
    try:
        await asyncio.gather(*(s.run() for s in sups))
    finally:
        for s in sups:
            s.stop()
        ring_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ring_task
    return sups
