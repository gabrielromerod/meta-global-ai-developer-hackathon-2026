"""Motion gate: frame differencing outside masked areas (FR-005).

:func:`motion_score` samples a frame every ``sample_interval_s`` (0.2 s), downsizes to
``analysis_width`` (320 px) grey, blurs, and measures the fraction of pixels outside the
(slightly dilated) privacy polygons whose brightness changed by more than ``pixel_delta``
between consecutive samples. The score is the largest such fraction in the clip, in
``[0, 1]``. :func:`gate_window` compares it with the camera's ``motion_threshold``
(:data:`DEFAULT_MOTION_THRESHOLD` when unset) and marks quiet windows ``idle``; idle
windows are never uploaded or sent to any model (:func:`select_active`). A Reolink AI event
overlapping the window (FR-033) or a manual trigger forces processing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import cv2
import numpy as np

from vigil.ingest.media import iter_frames, polygon_mask
from vigil.models import CameraCfg, Polygon, Window

__all__ = [
    "DEFAULT_MOTION_THRESHOLD",
    "gate_window",
    "motion_score",
    "select_active",
    "threshold_for",
]

DEFAULT_MOTION_THRESHOLD = 0.002
"""Fraction of unmasked pixels that must change between samples (0.2% of the frame;
a person-sized object walking at 10 m+ distance on a 1280x720 view)."""


def motion_score(
    path: Path | str,
    polygons: Sequence[Polygon],
    *,
    ref_size: tuple[int, int] | None = None,
    sample_interval_s: float = 0.2,
    analysis_width: int = 320,
    pixel_delta: int = 25,
    margin_px: int = 2,
) -> float:
    """Largest fraction of unmasked pixels that changed between frame samples.

    ``polygons`` are in ``ref_size`` pixels (default: the clip's own frame) and are
    excluded together with a ``margin_px`` border (analysis pixels) so codec noise at a
    masked edge is not counted.
    """
    prev: np.ndarray | None = None
    valid: np.ndarray | None = None
    n_valid = 0
    best = 0.0
    next_t = 0.0
    for _i, t, frame in iter_frames(path):
        if t + 1e-6 < next_t:
            continue
        next_t = t + sample_interval_s
        h, w = frame.shape[:2]
        aw = min(analysis_width, w)
        ah = max(1, round(h * aw / w))
        if valid is None:
            excluded = polygon_mask(
                (aw, ah), polygons, ref_size=ref_size or (w, h), margin_px=margin_px
            )
            valid = ~excluded
            n_valid = int(valid.sum())
            if n_valid == 0:
                return 0.0
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, (aw, ah), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (5, 5), 0)
        if prev is not None:
            changed = (cv2.absdiff(small, prev) > pixel_delta) & valid
            best = max(best, float(np.count_nonzero(changed)) / n_valid)
        prev = small
    return best


def threshold_for(cam: CameraCfg) -> float:
    """The camera's motion threshold, or :data:`DEFAULT_MOTION_THRESHOLD`."""
    return cam.motion_threshold if cam.motion_threshold is not None else DEFAULT_MOTION_THRESHOLD


def gate_window(
    window: Window,
    cam: CameraCfg,
    *,
    polygons: Sequence[Polygon] | None = None,
    camera_ai: bool = False,
    threshold: float | None = None,
) -> Window:
    """Score ``window.path`` and return a copy with ``motion``, ``status`` and ``trigger`` set.

    ``polygons`` default to ``cam.privacy`` (pass
    :func:`vigil.ingest.config.privacy_polygons` to include ``config/privacy`` files); they
    are in the camera frame ``cam.width`` x ``cam.height``. Quiet windows become ``idle``
    unless ``camera_ai`` is set or the window was triggered manually.
    """
    if not window.path:
        raise ValueError(f"window {window.id} has no file to score")
    polys = list(cam.privacy) if polygons is None else list(polygons)
    score = motion_score(window.path, polys, ref_size=(cam.width, cam.height))
    thr = threshold if threshold is not None else threshold_for(cam)
    moving = score >= thr
    if window.trigger == "manual":
        trigger, active = "manual", True
    elif camera_ai:
        trigger, active = "camera_ai", True
    elif moving:
        trigger, active = "motion", True
    else:
        trigger, active = None, False
    return window.model_copy(
        update={"motion": score, "trigger": trigger, "status": "pending" if active else "idle"}
    )


def select_active(windows: Iterable[Window]) -> list[Window]:
    """Windows that may be uploaded and sent to models (everything not ``idle``)."""
    return [w for w in windows if w.status != "idle"]
