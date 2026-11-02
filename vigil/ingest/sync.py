"""Clock alignment from one clap + phone-flash sync event (FR-002, UC-01).

Each camera films the same sync event at session start: a hand clap with a phone flash.

- :func:`detect_flashes` finds sudden whole-frame brightness jumps (mean grey level above a
  running median of the previous second by at least ``min_jump`` levels); the event time is
  the first bright frame's timestamp, so it is accurate to one frame.
- :func:`detect_audio_onsets` finds clap onsets in the audio track, if the clip has one
  (5 ms RMS envelope against the median noise floor). Audio is used only when no flash is
  visible, and the flash/clap disagreement is reported as ``av_delta_s``.
- :func:`sync_session` turns the first event of each camera into an offset relative to a
  reference camera (``offset_s`` is added to camera time to get session time, as in
  ``CameraCfg.offset_s``), so the sync event lands at the same session time everywhere.
  If the session also has later sync events (for example an end-of-session clap), each is
  aligned with the same offsets and the largest disagreement is the session ``residual_s``;
  a session over :data:`MAX_RESIDUAL_S` (0.5 s) raises :class:`SyncResidualError`
  (spec 3, "Camera clocks drift"). A camera whose sync event is not found is excluded,
  with the reason, until fixed (UC-01).
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, Field

from vigil.ingest.media import MediaError, count_audio_streams, iter_frames
from vigil.models import Config
from vigil.settings import ffmpeg_bin

__all__ = [
    "ALIGN_TOLERANCE_S",
    "MAX_RESIDUAL_S",
    "SyncError",
    "SyncEvent",
    "SyncEventNotFoundError",
    "SyncResidualError",
    "SyncResult",
    "apply_offsets",
    "detect_audio_onsets",
    "detect_flashes",
    "detect_sync_events",
    "measure_offsets",
    "sync_session",
]

MAX_RESIDUAL_S = 0.5
"""Sessions whose aligned sync events disagree by more than this are rejected."""
ALIGN_TOLERANCE_S = 0.2
"""FR-002 acceptance: aligned sync times agree within this on every session."""


class SyncError(RuntimeError):
    """The session cannot be aligned."""


class SyncEventNotFoundError(SyncError):
    """No flash or clap was found in a clip."""


class SyncResidualError(SyncError):
    """Aligned sync events disagree by more than the allowed residual."""

    def __init__(self, camera_id: str, residual_s: float, limit_s: float) -> None:
        self.camera_id = camera_id
        self.residual_s = residual_s
        self.limit_s = limit_s
        super().__init__(
            f"camera {camera_id!r}: sync residual {residual_s:.3f}s exceeds {limit_s:.2f}s; "
            "re-film the sync clap for this session"
        )


class SyncEvent(BaseModel):
    t: float
    """Clip time in seconds (from the clip's first frame)."""
    source: Literal["video", "audio"]
    av_delta_s: float | None = None
    """Audio onset minus flash time, when both were found."""


class SyncResult(BaseModel):
    reference: str
    offsets: dict[str, float]
    """camera_id -> seconds added to camera time to get session time."""
    residual_s: float = 0.0
    events: dict[str, list[SyncEvent]] = Field(default_factory=dict)
    excluded: dict[str, str] = Field(default_factory=dict)
    """camera_id -> reason it could not be aligned."""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _rising_edges(
    times: np.ndarray, signal: np.ndarray, thr: float, min_gap_s: float
) -> list[float]:
    out: list[float] = []
    above = signal >= thr
    for i in np.flatnonzero(above):
        if i > 0 and above[i - 1]:
            continue
        t = float(times[i])
        if out and t - out[-1] < min_gap_s:
            continue
        out.append(t)
    return out


def detect_flashes(
    path: Path | str,
    *,
    min_jump: float = 40.0,
    baseline_s: float = 1.0,
    min_gap_s: float = 1.0,
    analysis_width: int = 160,
) -> list[float]:
    """Clip times (s) of whole-frame brightness jumps (phone flash), earliest first."""
    times: list[float] = []
    levels: list[float] = []
    for _i, t, frame in iter_frames(path):
        h, w = frame.shape[:2]
        aw = min(analysis_width, w)
        small = cv2.resize(frame, (aw, max(1, round(h * aw / w))), interpolation=cv2.INTER_AREA)
        times.append(t)
        levels.append(float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean()))
    if len(levels) < 2:
        return []
    tt = np.asarray(times)
    lv = np.asarray(levels)
    spike = np.zeros_like(lv)
    lo = 0
    for i in range(1, len(lv)):
        while tt[i] - tt[lo] > baseline_s:
            lo += 1
        lo = min(lo, i - 1)
        spike[i] = lv[i] - float(np.median(lv[lo:i]))
    peak = float(spike.max())
    if peak < min_jump:
        return []
    return _rising_edges(tt, spike, max(min_jump, 0.5 * peak), min_gap_s)


def detect_audio_onsets(
    path: Path | str,
    *,
    rate: int = 16000,
    hop_s: float = 0.005,
    ratio: float = 10.0,
    min_level: float = 0.02,
    min_gap_s: float = 1.0,
) -> list[float]:
    """Clip times (s) of clap onsets in the audio track; ``[]`` when there is no audio."""
    if count_audio_streams(path) == 0:
        return []
    cmd = [ffmpeg_bin(), "-hide_banner", "-v", "error", "-nostdin", "-i", str(path),
           "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, timeout=300, check=False)
    if proc.returncode != 0:
        raise MediaError(f"audio decode failed for {path}: {proc.stderr.decode(errors='replace')}")
    pcm = np.frombuffer(proc.stdout, dtype="<i2").astype(np.float64) / 32768.0
    hop = max(1, int(rate * hop_s))
    n = len(pcm) // hop
    if n < 2:
        return []
    env = np.sqrt((pcm[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    floor = float(np.median(env)) + 1e-6
    gate = max(floor * ratio, min_level)
    peak = float(env.max())
    if peak < gate:
        return []
    times = np.arange(n) * hop / rate
    return _rising_edges(times, env, max(gate, 0.3 * peak), min_gap_s)


def detect_sync_events(path: Path | str, *, max_av_gap_s: float = 0.5) -> list[SyncEvent]:
    """Sync events in one clip: flashes (preferred) or, without any flash, audio claps.

    Raises :class:`SyncEventNotFoundError` when neither is found.
    """
    flashes = detect_flashes(path)
    onsets = detect_audio_onsets(path)
    if flashes:
        events = []
        for f in flashes:
            near = [o for o in onsets if abs(o - f) <= max_av_gap_s]
            delta = min((o - f for o in near), key=abs) if near else None
            events.append(SyncEvent(t=f, source="video", av_delta_s=delta))
        return events
    if onsets:
        return [SyncEvent(t=o, source="audio") for o in onsets]
    raise SyncEventNotFoundError(f"no flash or clap found in {path}")


# ---------------------------------------------------------------------------
# Session alignment
# ---------------------------------------------------------------------------


def _pair_residual(ref: list[float], other: list[float]) -> float:
    """Largest disagreement between later aligned events (the first defines the offset)."""
    if len(ref) < 2 or len(other) < 2:
        return 0.0
    if len(ref) == len(other):
        return max(abs(a - b) for a, b in zip(ref[1:], other[1:], strict=True))
    return max(min(abs(a - b) for b in other[1:]) for a in ref[1:])


def sync_session(
    clips: Mapping[str, Path | str],
    *,
    clip_starts: Mapping[str, float] | None = None,
    reference: str | None = None,
    max_residual_s: float = MAX_RESIDUAL_S,
) -> SyncResult:
    """Measure per-camera offsets for one recording session.

    ``clip_starts`` gives each clip's first-frame time on that camera's own clock (default
    0). The reference camera (default: the first camera with an event) gets offset 0.
    """
    starts = dict(clip_starts or {})
    events: dict[str, list[SyncEvent]] = {}
    excluded: dict[str, str] = {}
    for cam, path in clips.items():
        try:
            events[cam] = detect_sync_events(path)
        except (SyncEventNotFoundError, MediaError) as exc:
            excluded[cam] = str(exc).splitlines()[0]
    if reference is None:
        reference = next((c for c in clips if c in events), None)
        if reference is None:
            raise SyncError(f"no sync event found on any camera: {excluded}")
    elif reference not in events:
        reason = excluded.get(reference, "not in this session")
        raise SyncError(f"reference camera {reference!r} has no sync event: {reason}")

    def local(cam: str) -> list[float]:
        return [starts.get(cam, 0.0) + e.t for e in events[cam]]

    ref_times = local(reference)
    offsets: dict[str, float] = {}
    worst = (reference, 0.0)
    for cam in events:
        times = local(cam)
        off = 0.0 if cam == reference else ref_times[0] - times[0]
        offsets[cam] = off
        residual = _pair_residual(ref_times, [t + off for t in times])
        if residual > worst[1]:
            worst = (cam, residual)
    if worst[1] > max_residual_s:
        raise SyncResidualError(worst[0], worst[1], max_residual_s)
    return SyncResult(
        reference=reference,
        offsets=offsets,
        residual_s=worst[1],
        events=events,
        excluded=excluded,
    )


def measure_offsets(clips: Mapping[str, Path | str], **kwargs: object) -> dict[str, float]:
    """``camera_id -> offset_s`` for the cameras whose sync event was found (spec 9.5)."""
    return sync_session(clips, **kwargs).offsets  # type: ignore[arg-type]


def apply_offsets(cfg: Config, offsets: Mapping[str, float]) -> Config:
    """A copy of ``cfg`` with ``offset_s`` set for the given cameras."""
    known = {c.id for c in cfg.cameras}
    unknown = set(offsets) - known
    if unknown:
        raise SyncError(f"offsets for unknown cameras: {sorted(unknown)}")
    cams = [
        c.model_copy(update={"offset_s": float(offsets[c.id])}) if c.id in offsets else c
        for c in cfg.cameras
    ]
    return cfg.model_copy(update={"cameras": cams})
