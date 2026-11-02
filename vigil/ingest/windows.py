"""10 s windows, 2 s overlap, H.264 MP4, 10 fps, <=1280 px, faststart (FR-004).

:func:`plan_windows` lays out ``[t0, t1]`` as windows of ``length_s`` starting every
``length_s - overlap_s`` seconds (start ``k`` is computed as ``t0 + k * step``, so edges never
drift); the last window is cut at ``t1`` and no window is added that would end at or before
the previous one. :func:`cut_window` re-encodes one window with accurate seeking: the first
output frame is the source frame nearest ``t0`` (within one source frame), then one frame
every 0.1 s, keeping aspect with even dimensions, with no audio, no metadata and the
``moov`` atom first. Privacy polygons, when given, are blanked after scaling (FR-003).

Note: spec section 6 (Reolink near-real-time pipeline) describes a window as "a 10 s
segment plus the last 2 s of the one before" (12 s windows every 10 s); FR-004 says 10 s
windows with 2 s overlap. This module follows FR-004; for the live path call
``plan_windows(t0, t1, length_s=12, overlap_s=2)`` to get the section 6 layout.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from vigil.ingest.media import fit_width, polygon_mask, probe, transcode_masked
from vigil.ingest.privacy import DEFAULT_MARGIN_PX
from vigil.models import Polygon, Window, WindowTrigger

__all__ = ["WindowError", "cut_window", "cut_windows", "plan_windows", "window_id"]

WINDOW_FPS = 10.0
MAX_WIDTH = 1280
_EPS = 1e-9


class WindowError(ValueError):
    """A window cannot be cut (outside the clip, empty)."""


def plan_windows(
    t0: float, t1: float, length_s: float = 10.0, overlap_s: float = 2.0
) -> list[tuple[float, float]]:
    """Window edges covering ``[t0, t1]``: ``[(t0, t0+10), (t0+8, t0+18), ..., (.., t1)]``."""
    if length_s <= 0:
        raise ValueError("length_s must be positive")
    if overlap_s < 0 or overlap_s >= length_s:
        raise ValueError("overlap_s must be in [0, length_s)")
    if not t1 > t0:
        raise ValueError(f"empty span: t1 ({t1}) must be after t0 ({t0})")
    step = length_s - overlap_s
    out: list[tuple[float, float]] = []
    k = 0
    while True:
        a = t0 + k * step
        end = a + length_s
        if end >= t1 - _EPS:
            out.append((a, t1))
            return out
        out.append((a, end))
        k += 1


def window_id(camera_id: str, t0: float) -> str:
    """Stable id from camera and session start time in ms, e.g. ``side_left_000008000``."""
    return f"{camera_id}_{round(t0 * 1000):09d}"


def cut_window(
    src: Path | str,
    dst: Path | str,
    t0: float,
    t1: float,
    *,
    camera_id: str = "",
    id: str | None = None,
    session_start_s: float = 0.0,
    polygons: Sequence[Polygon] | None = None,
    ref_size: tuple[int, int] | None = None,
    fps: float = WINDOW_FPS,
    max_width: int = MAX_WIDTH,
    margin_px: int = DEFAULT_MARGIN_PX,
    crf: int = 23,
    trigger: WindowTrigger | None = None,
) -> Window:
    """Re-encode ``src[t0:t1]`` (seconds from the clip start) into the window file ``dst``.

    ``session_start_s`` is the session-clock time of the clip's first frame (camera clip
    start plus the FR-002 offset); the returned :class:`Window` carries session times.
    The end is clamped to the clip's duration; a start at or past the end raises
    :class:`WindowError`. ``polygons`` (in ``ref_size`` pixels, default the source frame)
    are blanked as in :func:`vigil.ingest.privacy.mask_clip`.
    """
    if not t1 > t0:
        raise ValueError(f"empty window: t1 ({t1}) must be after t0 ({t0})")
    if t0 < 0:
        raise ValueError("t0 must be >= 0 (seconds from the clip start)")
    info = probe(src)
    duration = info.duration
    if duration and t0 >= duration - 1.0 / max(fps, 1.0) + _EPS:
        raise WindowError(f"window starts at {t0:.3f}s, past the clip end ({duration:.3f}s)")
    t1c = min(t1, duration) if duration else t1
    out_w, out_h = fit_width(info.width, info.height, max_width)
    mask = None
    if polygons:
        ref = ref_size or (info.width, info.height)
        mask = polygon_mask((out_w, out_h), polygons, ref_size=ref, margin_px=margin_px)
    transcode_masked(
        src,
        dst,
        out_size=(out_w, out_h),
        mask=mask,
        fps=fps,
        start_s=t0,
        duration_s=t1c - t0,
        crf=crf,
    )
    s0 = session_start_s + t0
    return Window(
        id=id or window_id(camera_id, s0),
        camera_id=camera_id,
        t0=s0,
        t1=session_start_s + t1c,
        path=str(dst),
        trigger=trigger,
        status="pending",
        fps=fps,
        width=out_w,
        height=out_h,
    )


def cut_windows(
    src: Path | str,
    out_dir: Path | str,
    camera_id: str,
    *,
    length_s: float = 10.0,
    overlap_s: float = 2.0,
    session_start_s: float = 0.0,
    polygons: Sequence[Polygon] | None = None,
    ref_size: tuple[int, int] | None = None,
    **kwargs: object,
) -> list[Window]:
    """Plan and cut every window of a whole clip into ``out_dir/<window_id>.mp4``."""
    info = probe(src)
    out_dir = Path(out_dir)
    windows = []
    for a, b in plan_windows(0.0, info.duration, length_s, overlap_s):
        wid = window_id(camera_id, session_start_s + a)
        windows.append(
            cut_window(
                src,
                out_dir / f"{wid}.mp4",
                a,
                b,
                camera_id=camera_id,
                id=wid,
                session_start_s=session_start_s,
                polygons=polygons,
                ref_size=ref_size,
                **kwargs,  # type: ignore[arg-type]
            )
        )
    return windows
