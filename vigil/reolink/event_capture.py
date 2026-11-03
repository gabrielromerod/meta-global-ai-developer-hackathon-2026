"""AC event capture: sub-stream pre-roll, bounded main-stream recording, honest gaps."""

import asyncio
import contextlib
import hashlib
import json
import shutil
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

from vigil.ingest.media import probe
from vigil.ingest.panorama import illumination_mode
from vigil.ingest.review import require_privacy_review, require_silent_source
from vigil.ingest.windows import cut_window
from vigil.models import CameraAiEvent, CameraCfg
from vigil.reolink.capture import SubprocessRunner, cleanup_ring, list_segments, run_capture
from vigil.reolink.probe import ReolinkAioAdapter, camera_credentials, resolved_rtsp_url
from vigil.reolink.retention import PinIndex, cleanup_processing
from vigil.settings import ffmpeg_bin


def event_clip_cmd(url: str, destination: Path, *, ffmpeg: str | None = None) -> list[str]:
    input_options = (
        ["-rtsp_transport", "tcp", "-allowed_media_types", "video", "-timeout", "5000000"]
        if url.startswith(("rtsp://", "rtsps://"))
        else ["-rw_timeout", "5000000"]
        if url.startswith(("http://", "https://"))
        else []
    )
    return [
        ffmpeg or ffmpeg_bin(),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
        *input_options,
        "-i",
        url,
        "-map",
        "0:v:0",
        "-t",
        "120",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-vf",
        r"scale=-2:min(1440\,ih)",
        "-b:v",
        "3000000",
        "-maxrate",
        "4000000",
        "-bufsize",
        "6000000",
        "-force_key_frames",
        "expr:gte(t,n_forced*1)",
        "-an",
        "-dn",
        "-sn",
        "-map_metadata",
        "-1",
        "-movflags",
        "+frag_keyframe+empty_moov+default_base_moof",
        "-frag_duration",
        "100000",
        "-flush_packets",
        "1",
        str(destination),
    ]


class EventRecorder:
    def __init__(self, ring: Path, destination: Path, camera: CameraCfg, pre_roll_s: float = 10):
        require_privacy_review(camera)
        if camera.power_profile not in {"plugin_wifi", "doorbell"}:
            raise ValueError("Battery cameras never hold a stream open; use imported clips")
        self.ring, self.destination, self.camera = ring, destination, camera
        self.pre_roll_s = pre_roll_s
        self.index = PinIndex(ring)

    def pin(self, event: CameraAiEvent, *, now: float) -> None:
        segments = list_segments(self.ring / self.camera.id)
        self.index.pin(
            event.id,
            [
                s.path
                for s in segments
                if s.t1 > event.t0 - self.pre_roll_s and s.t0 <= (event.t1 or now) + 5
            ],
        )

    def finish(self, event: CameraAiEvent, main: Path, *, main_start: float) -> dict:
        self.pin(event, now=event.t1 or main_start)
        self.index.pin(event.id, [main])
        key = hashlib.sha256(event.id.encode()).hexdigest()[:20]
        attempt = hashlib.sha256(f"{main_start}|{main.name}".encode()).hexdigest()[:12]
        out = self.destination / f"{self.camera.id}-{key}-{attempt}"
        out.mkdir(parents=True, exist_ok=True)
        sources = []
        for segment in list_segments(self.ring / self.camera.id):
            if segment.t0 < main_start and segment.t1 > event.t0 - self.pre_roll_s:
                sources.append((segment.t0, segment.path, "sub"))
        sources.append((main_start, main, "main"))
        parts, gaps, windows = [], [], []
        desired_start = event.t0 - self.pre_roll_s
        covered = desired_start
        for index, (start, path, quality) in enumerate(sorted(sources)):
            require_silent_source(path)
            info = probe(path)
            end = start + info.duration
            a, b = max(start, desired_start), end
            if quality == "sub":
                b = min(b, main_start)
            if b <= a:
                continue
            if a > covered + 0.05:
                gaps.append(
                    {"t0": covered, "t1": a, "reason": "missing capture", "resolved": False}
                )
            destination = out / f"part-{index:03d}.mp4"
            window = cut_window(
                path,
                destination,
                a - start,
                b - start,
                camera_id=self.camera.id,
                session_start_s=start,
                polygons=self.camera.privacy,
                ref_size=(self.camera.width, self.camera.height),
                max_width=1920 if self.camera.frame_layout == "duo_panorama" else 2560,
            )
            window.illumination = illumination_mode(window.path)
            parts.append(
                {
                    "path": str(destination),
                    "t0": window.t0,
                    "t1": window.t1,
                    "source_quality": quality,
                }
            )
            windows.append(
                window.model_copy(
                    update={
                        "t0": round(window.t0 - desired_start, 6),
                        "t1": round(window.t1 - desired_start, 6),
                    }
                )
            )
            covered = max(covered, b)
        partial = event.t1 is None or covered < event.t1
        if event.t1 is None:
            gaps.append(
                {
                    "t0": covered,
                    "t1": None,
                    "reason": "recording ended while the camera event remained active",
                    "resolved": False,
                }
            )
        if event.t1 is not None and covered < event.t1:
            gaps.append(
                {
                    "t0": covered,
                    "t1": event.t1,
                    "reason": "Wi-Fi drop or interrupted capture",
                    "resolved": False,
                }
            )
        result = {
            "event": event.model_dump(mode="json"),
            "parts": parts,
            "gaps": gaps,
            "partial": partial,
            "source_label": "Event clips",
            "camera_id": self.camera.id,
            "session_id": out.name,
        }
        relative_event = event.model_copy(
            update={
                "t0": round(event.t0 - desired_start, 6),
                "t1": None if event.t1 is None else round(event.t1 - desired_start, 6),
            }
        )
        metadata = {
            "session_start": datetime.fromtimestamp(desired_start, UTC).isoformat(),
            "camera_ai_events": [relative_event.model_dump(mode="json")],
            "camera_ai_events_measured": True,
            "source_label": "Event clips",
            "truncated_after": {self.camera.id: round(covered - desired_start, 6)}
            if partial
            else {},
            "capture_gaps": gaps,
            "illumination_basis": "observed chroma heuristic; hardware IR state is not verified",
        }
        (out / "windows.json").write_text(
            json.dumps([w.model_dump(mode="json") for w in windows], indent=2), encoding="utf-8"
        )
        (out / "session.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        (out / "capture.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


async def run_event_capture(
    cameras: list[CameraCfg],
    root: Path,
    *,
    events: AsyncIterator[CameraAiEvent] | None = None,
    adapter=None,
    runner=None,
    free_floor_bytes: int = 2 * 1024**3,
    destination: Path | None = None,
    clock: Callable[[], float] = time.time,
) -> None:
    """Hardware entry point; invoked only by an explicit owner CLI command."""
    from vigil.reolink.ai_events import ReolinkAioPushAdapter, stream_ai_events

    ac = [c for c in cameras if c.power_profile in {"plugin_wifi", "doorbell"}]
    if not ac:
        raise ValueError("No AC cameras configured; battery cameras use import mode")
    for camera in ac:
        require_privacy_review(camera)
    root.mkdir(parents=True, exist_ok=True)
    ring = root / "ring"
    ring.mkdir(exist_ok=True)
    destination = destination or root / "events"
    recorders = {c.id: EventRecorder(ring, destination, c) for c in ac}
    cleanup_ring(ring, free_floor_bytes=free_floor_bytes)
    if shutil.disk_usage(root).free < free_floor_bytes:
        raise RuntimeError("disk free-space floor reached; pinned event evidence retained")
    sub_cameras = [
        c.model_copy(update={"source": c.source.model_copy(update={"stream": "sub"})})
        for c in ac
        if c.source
    ]
    adapter = adapter or ReolinkAioAdapter()
    runner = runner or SubprocessRunner("event")
    active = {}
    attempts = {}
    tasks = set()
    ring_task = asyncio.create_task(
        run_capture(sub_cameras, ring, via_restreamer=False, adapter=adapter)
    )

    async def watch(event_id, proc, source, started, recorder):
        try:
            await proc.wait()
            event = active[event_id][0]
            if source.exists():
                await asyncio.to_thread(recorder.finish, event, source, main_start=started)
        finally:
            active.pop(event_id, None)

    async def stop_after(proc):
        await asyncio.sleep(5)
        proc.kill()

    async def housekeeping():
        while True:
            for event, _, _, recorder in list(active.values()):
                recorder.pin(event, now=clock())
            cleanup_ring(ring, free_floor_bytes=free_floor_bytes)
            if shutil.disk_usage(root).free < free_floor_bytes:
                raise RuntimeError(
                    "disk floor reached; capture paused and pinned evidence retained"
                )
            cleanup_processing(destination, 48 * 3600)
            cleanup_processing(root / "cache", 72 * 3600)
            await asyncio.sleep(1)

    maintenance = asyncio.create_task(housekeeping())

    async def consume_events():
        event_source = (
            events
            if events is not None
            else stream_ai_events(ac, adapter=ReolinkAioPushAdapter(session_start=0))
        )
        async for event in event_source:
            if ring_task.done():
                await ring_task
                raise RuntimeError("sub-stream ring stopped")
            if maintenance.done():
                await maintenance
            if event.camera_id not in recorders or event.kind not in {
                "person",
                "vehicle",
                "doorbell_press",
            }:
                continue
            recorder = recorders[event.camera_id]
            recorder.pin(event, now=clock())
            if event.id in active:
                _, proc, source, _ = active[event.id]
                active[event.id] = (event, proc, source, recorder)
                if event.t1 is not None:
                    task = asyncio.create_task(stop_after(proc))
                    tasks.add(task)
                continue
            if event.t1 is not None:
                continue
            camera = next(c for c in ac if c.id == event.camera_id)
            creds = camera_credentials(camera)
            info = await adapter.host_info(
                creds.host, creds.user.get_secret_value(), creds.password.get_secret_value()
            )
            url = resolved_rtsp_url(info, camera, creds, "main")
            if url is None:
                raise RuntimeError(f"camera {camera.id}: main stream unavailable")
            key = hashlib.sha256(event.id.encode()).hexdigest()[:20]
            attempt = attempts.get(event.id, 0)
            source = ring / f"event-{key}-{attempt:03d}.mp4"
            while source.exists():
                attempt += 1
                source = ring / f"event-{key}-{attempt:03d}.mp4"
            attempts[event.id] = attempt + 1
            recorder.index.pin(event.id, [source])
            proc = await runner.start(event_clip_cmd(url.secret(), source))
            started = clock()
            active[event.id] = (event, proc, source, recorder)
            task = asyncio.create_task(watch(event.id, proc, source, started, recorder))
            tasks.add(task)

    consumer = asyncio.create_task(consume_events())
    try:
        done, _ = await asyncio.wait(
            [consumer, maintenance, ring_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            await task
        if consumer not in done:
            raise RuntimeError("capture service stopped; evidence retained")
    finally:
        for _, proc, _, _ in list(active.values()):
            proc.kill()
        ring_task.cancel()
        maintenance.cancel()
        consumer.cancel()
        for task in (ring_task, maintenance, consumer):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=False)
