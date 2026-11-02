"""Event builder: enter, exit, cross, touch, removed, dwell (FR-008).

All geometry is in the processed window's pixel frame (spec 9.4 config):

* **enter / exit** — the track's foot point (bottom centre of its box) moves into or out of
  a camera zone polygon. A track that first appears inside a zone enters it at its first
  frame; a track that ends inside a zone exits it at its last frame.
* **dwell** — one stay inside a zone lasting at least ``dwell_s`` (t0 = entry, t1 = exit).
* **cross** — the foot point changes side of a configured line, and the step between the
  last frame on the old side and the first on the new side intersects the finite segment.
* **touch** — a person's mask (or box when no mask is stored) overlaps a protected object's
  bbox with an overlap coefficient (intersection / smaller area) of at least
  ``touch_overlap``; one event per contiguous touching interval.
* **removed** — a watched object's track ends, before the camera's footage ends and
  without reappearing at the same place, while a person overlaps its last box.

Every state change is debounced: a new state must hold for ``min_frames`` consecutive
frames, and its time is the first of those frames. Event ids are content hashes, so they are
stable across runs and across incremental batches (NFR-011). Clip ranges pad the event by
``clip_pad_s`` on each side (clamped at 0).
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from vigil.models import (
    Box,
    CameraCfg,
    Config,
    Event,
    EventType,
    ProtectedObject,
    Track,
    TrackFrame,
    Watch,
)
from vigil.perception.rle import decode_rle
from vigil.perception.tracks import phrase_class

DWELL_S = 30.0
CLIP_PAD_S = 3.0
MIN_FRAMES = 2
TOUCH_OVERLAP = 0.1
TOUCH_MERGE_GAP_S = 1.0
REMOVE_BEFORE_S = 2.0
REMOVE_AFTER_S = 1.0
REMOVE_REAPPEAR_IOU = 0.3
END_TOLERANCE_S = 0.5

MOVING_CLASSES = ("person", "car")
TOUCH_CLASSES = ("person",)
ACTIVE_WATCH = ("watching",)

_TYPE_ORDER: dict[str, int] = {
    "exit": 0,
    "cross": 1,
    "enter": 2,
    "touch": 3,
    "removed": 4,
    "dwell": 5,
}


@dataclass(frozen=True)
class _Raw:
    camera_id: str
    track_id: str
    type: EventType
    t0: float
    t1: float
    target: str | None


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def foot_point(box: Box) -> tuple[float, float]:
    """Bottom centre of a box: where the subject meets the ground (best effort)."""
    return ((box.x1 + box.x2) / 2.0, box.y2)


def _debounce(states: Sequence, k: int) -> list[tuple[int, object]]:
    """[(index, state)] where a new state starts holding for at least ``k`` frames.

    The first entry is the initial state at index 0.
    """
    if not states:
        return []
    cur = states[0]
    out: list[tuple[int, object]] = [(0, cur)]
    run_start: int | None = None
    for i in range(1, len(states)):
        s = states[i]
        if s == cur:
            run_start = None
            continue
        if run_start is None or states[run_start] != s:
            run_start = i
        if i - run_start + 1 >= k:
            cur = s
            out.append((run_start, s))
            run_start = None
    return out


def _intervals(frames: list[TrackFrame], inside: list[bool], k: int) -> list[tuple[float, float]]:
    """Debounced [t_in, t_out] stays; a stay open at the end closes at the last frame."""
    out: list[tuple[float, float]] = []
    start: float | None = None
    for idx, state in _debounce(inside, k):
        if state and start is None:
            start = frames[idx].t
        elif not state and start is not None:
            out.append((start, frames[idx].t))
            start = None
    if start is not None:
        out.append((start, frames[-1].t))
    return out


def _side(p: tuple[float, float], line: list[tuple[float, float]]) -> int:
    """Side (+1/-1, 0 on the line) of a point relative to the nearest segment of a polyline."""
    best = None
    for a, b in itertools.pairwise(line):
        seg = LineString([a, b])
        d = seg.distance(Point(p))
        if best is None or d < best[0]:
            best = (d, a, b)
    assert best is not None
    _, (ax, ay), (bx, by) = best
    cross = (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)
    return (cross > 0) - (cross < 0)


def _overlap(frame: TrackFrame, bbox: Box, height: int, width: int) -> float:
    """Overlap coefficient between a track frame (mask if present, else box) and a bbox."""
    if frame.mask_rle:
        mask = decode_rle(frame.mask_rle, height, width)
        x0, y0 = max(int(bbox.x1), 0), max(int(bbox.y1), 0)
        x1, y1 = min(int(np.ceil(bbox.x2)), width), min(int(np.ceil(bbox.y2)), height)
        inter = float(mask[y0:y1, x0:x1].sum()) if x1 > x0 and y1 > y0 else 0.0
        area = float(mask.sum())
    else:
        ix = max(0.0, min(frame.box.x2, bbox.x2) - max(frame.box.x1, bbox.x1))
        iy = max(0.0, min(frame.box.y2, bbox.y2) - max(frame.box.y1, bbox.y1))
        inter = ix * iy
        area = frame.box.area
    denom = min(area, bbox.area)
    return inter / denom if denom > 0 else 0.0


# ---------------------------------------------------------------------------
# Per-type builders
# ---------------------------------------------------------------------------


def _zone_events(tr: Track, zones: dict[str, Polygon], k: int, dwell_s: float) -> list[_Raw]:
    out: list[_Raw] = []
    feet = [Point(foot_point(f.box)) for f in tr.frames]
    for zone_id, poly in zones.items():
        inside = [poly.covers(p) for p in feet]
        for t_in, t_out in _intervals(tr.frames, inside, k):
            out.append(_Raw(tr.camera_id, tr.id, "enter", t_in, t_in, zone_id))
            out.append(_Raw(tr.camera_id, tr.id, "exit", t_out, t_out, zone_id))
            if t_out - t_in >= dwell_s:
                out.append(_Raw(tr.camera_id, tr.id, "dwell", t_in, t_out, zone_id))
    return out


def _cross_events(tr: Track, lines: dict[str, list[tuple[float, float]]], k: int) -> list[_Raw]:
    out: list[_Raw] = []
    feet = [foot_point(f.box) for f in tr.frames]
    for line_id, pts in lines.items():
        if len(pts) < 2:
            continue
        geom = LineString(pts)
        sides: list[int] = []
        last = 0
        for p in feet:
            s = _side(p, pts)
            last = s if s != 0 else last
            sides.append(last)
        changes = _debounce(sides, k)
        for (_, old), (j, new) in itertools.pairwise(changes):
            if old == 0 or new == 0:
                continue
            step = LineString([feet[j - 1], feet[j]]) if feet[j - 1] != feet[j] else None
            if step is not None and step.intersects(geom):
                out.append(
                    _Raw(tr.camera_id, tr.id, "cross", tr.frames[j - 1].t, tr.frames[j].t, line_id)
                )
    return out


def _touch_events(
    tr: Track, objs: list[ProtectedObject], cam: CameraCfg, k: int, thresh: float, gap_s: float
) -> list[_Raw]:
    out: list[_Raw] = []
    for po in objs:
        touching = [_overlap(f, po.bbox, cam.height, cam.width) >= thresh for f in tr.frames]
        spans: list[list[float]] = []
        for t_in, t_out in _intervals(tr.frames, touching, k):
            # Close the span at the last touching frame, not the first non-touching one.
            last_touch = max(
                (
                    f.t
                    for f, on in zip(tr.frames, touching, strict=True)
                    if on and t_in <= f.t <= t_out
                ),
                default=t_in,
            )
            if spans and t_in - spans[-1][1] <= gap_s:
                spans[-1][1] = last_touch
            else:
                spans.append([t_in, last_touch])
        out += [_Raw(tr.camera_id, tr.id, "touch", a, b, po.id) for a, b in spans]
    return out


def _removed_events(
    tracks: list[Track],
    watches: list[Watch],
    cams: dict[str, CameraCfg],
    thresh: float,
    before_s: float,
    after_s: float,
) -> list[_Raw]:
    out: list[_Raw] = []
    footage_end: dict[str, float] = {}
    for tr in tracks:
        footage_end[tr.camera_id] = max(footage_end.get(tr.camera_id, tr.t_last), tr.t_last)
    for watch in sorted(watches, key=lambda w: w.id):
        if watch.status not in ACTIVE_WATCH or watch.camera_id not in cams:
            continue
        cam = cams[watch.camera_id]
        cls = phrase_class(watch.phrase)
        watched = [t for t in tracks if t.camera_id == watch.camera_id and t.cls == cls]
        people = [t for t in tracks if t.camera_id == watch.camera_id and t.cls in TOUCH_CLASSES]
        for obj in watched:
            if not obj.frames:
                continue
            end = obj.t_last
            last_box = obj.frames[-1].box
            if end >= footage_end[watch.camera_id] - END_TOLERANCE_S:
                continue  # the footage ended, not the object
            reappears = any(
                o is not obj
                and o.t_first >= end
                and o.frames
                and o.frames[0].box.iou(last_box) >= REMOVE_REAPPEAR_IOU
                for o in watched
            )
            if reappears:
                continue
            best: tuple[int, str, float, float] | None = None
            for person in people:
                hits = [
                    f.t
                    for f in person.frames
                    if end - before_s <= f.t <= end + after_s
                    and _overlap(f, last_box, cam.height, cam.width) >= thresh
                ]
                if not hits:
                    continue
                cand = (-len(hits), person.id, min(hits), max(hits))
                if best is None or cand < best:
                    best = cand
            if best is not None:
                _, pid, h0, h1 = best
                out.append(
                    _Raw(watch.camera_id, pid, "removed", min(h0, end), max(h1, end), watch.id)
                )
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def event_id(raw: _Raw) -> str:
    key = f"{raw.camera_id}|{raw.track_id}|{raw.type}|{raw.target}|{raw.t0:.3f}|{raw.t1:.3f}"
    return "e" + hashlib.blake2b(key.encode("utf-8"), digest_size=8).hexdigest()[:10]


def build_events(
    tracks: list[Track],
    cfg: Config,
    protected: list[ProtectedObject],
    watches: list[Watch],
    *,
    dwell_s: float = DWELL_S,
    clip_pad_s: float = CLIP_PAD_S,
    min_frames: int = MIN_FRAMES,
    touch_overlap: float = TOUCH_OVERLAP,
    touch_merge_gap_s: float = TOUCH_MERGE_GAP_S,
    exits_as_zones: bool = False,
) -> list[Event]:
    """Build the events of FR-008 from stitched tracks (spec 9.5 interface).

    Tracks on cameras missing from ``cfg`` are ignored. Events are returned sorted by
    (t0, camera, type, track, target) with ``visit_id`` unset (assigned by reasoning).
    """
    cams = {c.id: c for c in cfg.cameras}
    known = [t for t in tracks if t.camera_id in cams and t.frames]
    known.sort(key=lambda t: (t.camera_id, t.id))
    raws: list[_Raw] = []
    for tr in known:
        cam = cams[tr.camera_id]
        if tr.cls in MOVING_CLASSES:
            zones = {
                zid: Polygon(poly) for zid, poly in sorted(cam.zones.items()) if len(poly) >= 3
            }
            if exits_as_zones:
                zones.update(
                    {
                        zid: Polygon(poly)
                        for zid, poly in sorted(cam.exits.items())
                        if len(poly) >= 3
                    }
                )
            raws += _zone_events(tr, zones, min_frames, dwell_s)
            raws += _cross_events(tr, dict(sorted(cam.lines.items())), min_frames)
        if tr.cls in TOUCH_CLASSES:
            mine = sorted((p for p in protected if p.camera_id == tr.camera_id), key=lambda p: p.id)
            raws += _touch_events(tr, mine, cam, min_frames, touch_overlap, touch_merge_gap_s)
    raws += _removed_events(known, watches, cams, touch_overlap, REMOVE_BEFORE_S, REMOVE_AFTER_S)

    events = [
        Event(
            id=event_id(r),
            camera_id=r.camera_id,
            track_id=r.track_id,
            type=r.type,
            t0=r.t0,
            t1=r.t1,
            target=r.target,
            clip_t0=round(max(0.0, r.t0 - clip_pad_s), 3),
            clip_t1=round(r.t1 + clip_pad_s, 3),
        )
        for r in set(raws)
    ]
    events.sort(
        key=lambda e: (e.t0, e.camera_id, _TYPE_ORDER[e.type], e.track_id, e.target or "", e.t1)
    )
    return events
