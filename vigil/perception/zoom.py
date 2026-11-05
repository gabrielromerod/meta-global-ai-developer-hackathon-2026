"""Zoomed person crops so SAM can see small carried objects (field result, Nov 4).

A knife is a few pixels wide in a wide event clip: on a real clip SAM 3.1 found nothing on the
full frame and found the blade on a 2.75x crop. Code picks each crop from SAM's own person
boxes, and SAM still does the detecting. Boxes are mapped back to the full frame, so nothing
after this module knows a crop was used.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from vigil.models import Box, Polygon, SamFrame, SamObject
from vigil.settings import ffmpeg_bin

log = logging.getLogger(__name__)

MAX_CROP_SHARE = 0.25
"""A crop spans at most this share of the frame width; a walker gets a new crop past it."""
REACH_SHARE = 0.5
"""Margin around a person box, as a share of its height: an arm's reach holding something."""
TARGET_WIDTH = 1280
MAX_SCALE = 3.0
MAX_CROPS = 3
"""Crops per window: each one costs one SAM call per carried object."""
MIN_SPAN_S = 1.0
"""SAM reads video, so a crop always covers at least this long."""
ID_STRIDE = 1000
"""Keeps object ids from different crops of one window apart."""


@dataclass(frozen=True)
class CropPlan:
    t0: float
    t1: float
    x0: int
    y0: int
    w: int
    h: int
    scale: float
    out_w: int
    out_h: int


def _even(v: float) -> int:
    return max(2, int(v) // 2 * 2)


def _plan(t0: float, t1: float, box: Box, reach: float, fw: int, fh: int) -> CropPlan:
    x0 = max(0, int(box.x1 - reach))
    y0 = max(0, int(box.y1 - reach))
    w = _even(min(fw, box.x2 + reach) - x0)
    h = _even(min(fh, box.y2 + reach) - y0)
    scale = min(MAX_SCALE, TARGET_WIDTH / w)
    return CropPlan(t0, t1, x0, y0, w, h, scale, _even(w * scale), _even(h * scale))


def _union(a: Box, b: Box) -> Box:
    return Box(x1=min(a.x1, b.x1), y1=min(a.y1, b.y1), x2=max(a.x2, b.x2), y2=max(a.y2, b.y2))


def _spans(person: SamObject, fw: int, fh: int) -> list[tuple[float, float, Box, float]]:
    """Split one person's frames wherever a single crop would grow past MAX_CROP_SHARE."""
    frames = sorted(person.frames, key=lambda f: f.t)
    if not frames:
        return []
    reach = REACH_SHARE * max(f.box.y2 - f.box.y1 for f in frames)
    extent = max(f.box.x2 for f in frames) - min(f.box.x1 for f in frames)
    # A fast walker keeps full coverage within MAX_CROPS at a lower zoom, never a time gap.
    limit = max(MAX_CROP_SHARE * fw, extent / MAX_CROPS + 2 * reach + 1)
    spans = []
    start, box, last = frames[0].t, frames[0].box, frames[0].t
    for f in frames[1:]:
        grown = _union(box, f.box)
        if grown.x2 - grown.x1 + 2 * reach > limit:
            spans.append((start, f.t, box, reach))
            start, box = f.t, f.box
        else:
            box = grown
        last = f.t
    spans.append((start, last, box, reach))
    return spans


def plan_crops(
    persons: Sequence[SamObject], frame_w: int, frame_h: int, *, t0: float, t1: float
) -> list[CropPlan]:
    """Crops covering every person in a window, longest first when over MAX_CROPS."""
    spans = [s for p in persons for s in _spans(p, frame_w, frame_h)]
    if len(spans) > MAX_CROPS:
        log.warning("window has %d person spans; zooming on the longest %d", len(spans), MAX_CROPS)
        spans = sorted(spans, key=lambda s: s[0] - s[1])[:MAX_CROPS]
    plans = []
    for a, b, box, reach in sorted(spans, key=lambda s: s[0]):
        pad = max(0.0, MIN_SPAN_S - (b - a)) / 2
        plans.append(_plan(max(t0, a - pad), min(t1, b + pad), box, reach, frame_w, frame_h))
    return plans


def shift_polygons(
    polygons: Sequence[Polygon],
    plan: CropPlan,
    ref_size: tuple[int, int],
    frame_size: tuple[int, int],
) -> list[Polygon]:
    """Camera privacy polygons in the crop's pixels, so the upload guard still checks them."""
    sx, sy = frame_size[0] / ref_size[0], frame_size[1] / ref_size[1]
    return [
        [((p[0] * sx - plan.x0) * plan.scale, (p[1] * sy - plan.y0) * plan.scale) for p in poly]
        for poly in polygons
    ]


def map_back(
    found: SamObject,
    plan: CropPlan,
    *,
    window_id: str,
    index: int,
    frame_size: tuple[int, int],
    fps: float,
    window_t0: float,
) -> SamObject:
    """One crop's SAM object in full-frame pixels, on the parent window."""

    def full(f: SamFrame) -> SamFrame:
        b = f.box
        return SamFrame(
            frame=round((f.t - window_t0) * fps),
            t=f.t,
            box=Box(
                x1=b.x1 / plan.scale + plan.x0,
                y1=b.y1 / plan.scale + plan.y0,
                x2=b.x2 / plan.scale + plan.x0,
                y2=b.y2 / plan.scale + plan.y0,
            ),
            confidence=f.confidence,
        )

    return found.model_copy(
        update={
            "window_id": window_id,
            "obj_id": (index + 1) * ID_STRIDE + found.obj_id,
            "width": frame_size[0],
            "height": frame_size[1],
            "frames": [full(f) for f in found.frames],
        }
    )


def cut_crop(src: Path | str, dst: Path, plan: CropPlan, window_t0: float) -> Path:
    """Write the crop of a masked window: silent, no metadata, enlarged."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = f"crop={plan.w}:{plan.h}:{plan.x0}:{plan.y0},scale={plan.out_w}:{plan.out_h}:flags=lanczos"
    subprocess.run(
        [
            ffmpeg_bin(),
            "-y",
            "-v",
            "error",
            "-ss",
            f"{plan.t0 - window_t0:.3f}",
            "-t",
            f"{plan.t1 - plan.t0:.3f}",
            "-i",
            str(src),
            "-an",
            "-map_metadata",
            "-1",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            "16",
            str(dst),
        ],
        check=True,
    )
    return dst
