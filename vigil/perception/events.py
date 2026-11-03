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
* **removed** — a watched object's track ends without reappearing at the same place while
  a person overlaps its last full box, and either (a) at least 2 s of continuously observed
  absence follow, or
  (b) the object was **carried out of frame**: it moved from where it was first seen, its
  last box touches a frame edge (within 2% of the frame size), and an overlapping person
  track ends within 1 s of it. The footage end is the end of the :class:`Observation` span
  containing the object's last frame; without an observation (or when no span contains
  that frame) it is the latest track end on the camera. Rule (b) matters because a person
  carrying the package away ends together with it, and the latest track end then sits
  right after the package's (F3). An object still in view (not at an edge, or never moved)
  when its observed span ends is not removed: the footage ended, not the object.
  Reappearance uses containment against the latest untruncated box with at least 90% of
  the largest observed area; a shrunken partial box cannot create a false removal. The
  session's accumulated stitched tracks retain that reference across window boundaries.

When several people overlap the protected object (or the removed object's last box), one
``touch`` (or ``removed``) event is emitted **per overlapping person track**; each later
carries its own subject's ``actor_role`` (filled in by visit assembly, FR-044).

**Origin tagging** (FR-008, spec 9.4 zone kinds). :func:`build_events` also sets each
track's ``origin_zone`` in place (see :func:`assign_origins`):

1. Each of the track's first frames (the first ``first_s`` = 1 s, at most 10 frames) is
   labelled with the zone containing its foot point; where zones overlap the most specific
   wins: ``egress`` before ``perimeter`` before ``interior_yard``, then the smaller polygon,
   then the name. The origin is the label held by a **strict majority** of those frames;
   no zone, or a tie, gives ``None``.
2. The origin is ``None`` unless the camera was observed without interruption for the
   2 s before the track's first frame (:class:`Observation`: no outage, no skipped
   (``idle``) or unprocessed (``failed``) window, which also covers the first frame of a
   window whose predecessor was skipped). Without an :class:`Observation` every camera
   counts as observed.
3. An ``egress`` origin is voided (``None``) when any person track on that camera whose own
   origin is not that egress zone overlapped the zone's polygon, scaled by 1.5 about its
   centroid (dilated by 50%), at any frame in the 10 min up to the track's first frame.

Every state change is debounced: a new state must hold for ``min_frames`` consecutive
frames, and its time is the first of those frames. Event ids are content hashes, so they are
stable across runs and across incremental batches (NFR-011). Clip ranges pad the event by
``clip_pad_s`` on each side (clamped at 0).
"""

from __future__ import annotations

import hashlib
import itertools
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry import box as shapely_box

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
    Window,
    ZoneKind,
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
REMOVE_ABSENCE_S = 2.0
REMOVE_CONTAINMENT = 0.8
END_TOLERANCE_S = 0.5
CARRY_END_S = 1.0
"""A person ending within this long of the object's last frame carried it out (rule b)."""
EDGE_MARGIN_FRAC = 0.02
"""A last box within this fraction of the frame width/height of a border is at the edge."""

ORIGIN_FIRST_S = 1.0
"""Origin vote window: the track's first second ..."""
ORIGIN_FRAMES = 10
"""... capped at its first 10 frames (10 fps processing rate)."""
ORIGIN_LOOKBACK_S = 2.0
"""The camera must have been observed without interruption this long before a track's
first frame for the track to get an origin."""
EGRESS_VOID_S = 600.0
"""A non-egress person near an egress zone voids egress origins there for 10 min."""
EGRESS_DILATE = 1.5
"""Egress polygon scale factor (about its centroid) for the voiding check: dilated by 50%."""
OBSERVE_JOIN_S = 0.25
"""Observed windows closer than this are one continuous observed span (frame seams)."""
UNOBSERVED_STATUSES: tuple[str, ...] = ("idle", "failed")
"""Window statuses that interrupt observation: skipped by the motion gate, or not processed."""
_EPS = 1e-6
_KIND_RANK: dict[str, int] = {"egress": 0, "perimeter": 1, "interior_yard": 2}

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


def _at_edge(box: Box, cam: CameraCfg, frac: float = EDGE_MARGIN_FRAC) -> bool:
    """True when ``box`` reaches within ``frac`` of the frame size of any frame border."""
    mx, my = frac * cam.width, frac * cam.height
    return box.x1 <= mx or box.y1 <= my or box.x2 >= cam.width - mx or box.y2 >= cam.height - my


def _footage_end(
    obj: Track, observation: Observation | None, track_end: Mapping[str, float]
) -> float:
    """End of the observed span holding ``obj``'s last frame (else the camera's last track)."""
    if observation is not None:
        for a, b in observation.spans.get(obj.camera_id, ()):
            if a - _EPS <= obj.t_last <= b + _EPS:
                return b
    return track_end[obj.camera_id]


def _last_full_box(track: Track) -> Box | None:
    """Latest untruncated box near the largest observed area, before an occlusion shrank it."""
    full = [f for f in track.frames if not f.clipped and f.box.area > 0]
    if not full:
        return None
    area = max(f.box.area for f in full)
    return next(f.box for f in reversed(full) if f.box.area >= 0.9 * area)


def _contained(a: Box, b: Box) -> bool:
    intersection = max(0, min(a.x2, b.x2) - max(a.x1, b.x1)) * max(
        0, min(a.y2, b.y2) - max(a.y1, b.y1)
    )
    smaller = min(a.area, b.area)
    return smaller > 0 and intersection / smaller >= REMOVE_CONTAINMENT


def _removed_events(
    tracks: list[Track],
    watches: list[Watch],
    cams: dict[str, CameraCfg],
    thresh: float,
    before_s: float,
    after_s: float,
    observation: Observation | None = None,
    absence_s: float = REMOVE_ABSENCE_S,
) -> list[_Raw]:
    out: list[_Raw] = []
    track_end: dict[str, float] = {}
    for tr in tracks:
        track_end[tr.camera_id] = max(track_end.get(tr.camera_id, tr.t_last), tr.t_last)
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
            last_box = _last_full_box(obj)
            if last_box is None:
                continue
            reappears = any(
                o is not obj and any(f.t >= end and _contained(f.box, last_box) for f in o.frames)
                for o in watched
            )
            if reappears:
                continue
            # Person tracks overlapping the object as it disappears.
            hits: dict[str, tuple[Track, list[float]]] = {}
            for person in people:
                ts = [
                    f.t
                    for f in person.frames
                    if end - before_s <= f.t <= end + after_s
                    and _overlap(f, last_box, cam.height, cam.width) >= thresh
                ]
                if ts:
                    hits[person.id] = (person, ts)
            if not hits:
                continue
            observed_until = _footage_end(obj, observation, track_end)
            footage_ended = end >= observed_until - END_TOLERANCE_S
            if footage_ended:
                moved = obj.frames[0].box.iou(last_box) < REMOVE_REAPPEAR_IOU
                carried = (
                    moved
                    and _at_edge(last_box, cam)
                    and any(abs(p.t_last - end) <= CARRY_END_S for p, _ in hits.values())
                )
                if not carried:
                    continue  # the footage ended, not the object
            elif observed_until - end < absence_s:
                continue  # not enough continuous observed absence to distinguish occlusion
            # One removed event per person track overlapping the object as it disappears.
            for person, ts in hits.values():
                t0, t1 = min(min(ts), end), max(max(ts), end)
                out.append(_Raw(watch.camera_id, person.id, "removed", t0, t1, watch.id))
    return out


# ---------------------------------------------------------------------------
# Origin tagging (FR-008)
# ---------------------------------------------------------------------------


class _Span(Protocol):
    """Anything with a camera and a session-clock interval, e.g. ``visits.Outage``."""

    camera_id: str
    t0: float
    t1: float


@dataclass(frozen=True)
class Observation:
    """When each camera was actually watched, on the session clock (FR-008 origin rule).

    ``spans[camera_id]`` holds sorted, disjoint ``(t0, t1)`` intervals in which the camera
    was observed without interruption. A track keeps its origin only when
    ``[t_first - 2 s, t_first]`` lies inside one span. A camera missing from ``spans`` was
    never observed, so its tracks get no origin (fails closed: ``None`` becomes the
    ``unknown`` role, FR-044). Build it with :meth:`from_windows`; pass
    ``observation=None`` (the default everywhere) when no window bookkeeping exists, which
    treats every camera as observed. The same spans also set the footage end used by
    ``removed`` (the end of the span holding the object's last frame).
    """

    spans: Mapping[str, tuple[tuple[float, float], ...]]

    @classmethod
    def from_windows(
        cls,
        windows: Iterable[Window],
        outages: Iterable[_Span] = (),
        *,
        unobserved: Sequence[str] = UNOBSERVED_STATUSES,
        join_s: float = OBSERVE_JOIN_S,
    ) -> Observation:
        """Observed spans from the session's windows, minus camera outages.

        A window counts as observed unless its status is in ``unobserved`` (default:
        ``idle``, skipped by the motion gate, and ``failed``, not processed); mark any other
        unprocessed window ``failed`` before calling. Observed windows closer than
        ``join_s`` merge into one span; skipped, unprocessed or missing windows leave a hole,
        so the first frames of a window whose predecessor was skipped are not covered.
        Outages (objects with ``camera_id``, ``t0``, ``t1``) are cut out of the spans.
        """
        per_cam: dict[str, list[tuple[float, float]]] = {}
        for w in windows:
            if w.status in unobserved or w.t1 <= w.t0:
                continue
            per_cam.setdefault(w.camera_id, []).append((float(w.t0), float(w.t1)))
        cuts: dict[str, list[tuple[float, float]]] = {}
        for o in outages:
            cuts.setdefault(o.camera_id, []).append((float(o.t0), float(o.t1)))
        spans: dict[str, tuple[tuple[float, float], ...]] = {}
        for cam_id, ivs in per_cam.items():
            merged: list[tuple[float, float]] = []
            for a, b in sorted(ivs):
                if merged and a <= merged[-1][1] + join_s:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], b))
                else:
                    merged.append((a, b))
            for o0, o1 in sorted(cuts.get(cam_id, [])):
                cut: list[tuple[float, float]] = []
                for a, b in merged:
                    if o1 <= a or o0 >= b:
                        cut.append((a, b))
                        continue
                    if a < o0:
                        cut.append((a, o0))
                    if o1 < b:
                        cut.append((o1, b))
                merged = cut
            spans[cam_id] = tuple(merged)
        return cls(spans=spans)

    def covers(self, camera_id: str, t0: float, t1: float) -> bool:
        """True when ``[t0, t1]`` lies inside one observed span of ``camera_id``."""
        return any(a <= t0 + _EPS and t1 <= b + _EPS for a, b in self.spans.get(camera_id, ()))


@dataclass(frozen=True)
class _Zone:
    id: str
    kind: ZoneKind
    poly: Polygon


def _zone_table(cam: CameraCfg) -> list[_Zone]:
    """Camera zones, most specific first: egress, perimeter, interior_yard; smaller first."""
    zones = [
        _Zone(zid, cam.zone_kind(zid), Polygon(pts))
        for zid, pts in cam.zones.items()
        if len(pts) >= 3
    ]
    zones.sort(key=lambda z: (_KIND_RANK.get(z.kind, 9), z.poly.area, z.id))
    return zones


def _frame_zone(frame: TrackFrame, table: list[_Zone]) -> str | None:
    p = Point(foot_point(frame.box))
    return next((z.id for z in table if z.poly.covers(p)), None)


def _raw_origin(track: Track, table: list[_Zone], first_s: float) -> str | None:
    """Strict-majority zone of the track's first ``first_s`` (at most 10 frames)."""
    if not track.frames:
        return None
    t_first = track.frames[0].t
    head = [f for f in track.frames if f.t < t_first + first_s - _EPS][:ORIGIN_FRAMES]
    head = head or track.frames[:1]
    votes = Counter(_frame_zone(f, table) for f in head)
    zone, n = max(votes.items(), key=lambda kv: (kv[1], kv[0] or ""))
    return zone if 2 * n > len(head) else None


def _near_egress(other: Track, dilated: Polygon, t0: float, t1: float) -> bool:
    """True when ``other``'s box overlaps ``dilated`` (more than an edge) in ``[t0, t1]``."""
    for f in other.frames:
        if not t0 - _EPS <= f.t <= t1 + _EPS:
            continue
        b = shapely_box(f.box.x1, f.box.y1, f.box.x2, f.box.y2)
        if dilated.intersects(b) and not dilated.touches(b):
            return True
    return False


def _tag_origins(
    tracks: Iterable[Track],
    cfg: Config,
    observation: Observation | None,
    first_s: float,
) -> dict[str, str | None]:
    """Final origins of tracks on configured cameras (pure; see the module docstring)."""
    cams = {c.id: c for c in cfg.cameras}
    known = {t.id: t for t in tracks if t.camera_id in cams}
    order = sorted(known.values(), key=lambda t: (t.frames[0].t if t.frames else t.t_first, t.id))
    tables = {cid: _zone_table(cam) for cid, cam in cams.items()}
    raw = {t.id: _raw_origin(t, tables[t.camera_id], first_s) for t in order}
    final: dict[str, str | None] = {}
    for tr in order:
        zone = raw[tr.id]
        if zone is not None and observation is not None:
            t_first = tr.frames[0].t
            if not observation.covers(tr.camera_id, t_first - ORIGIN_LOOKBACK_S, t_first):
                zone = None
        if zone is not None and cams[tr.camera_id].zone_kind(zone) == "egress":
            poly = next(z.poly for z in tables[tr.camera_id] if z.id == zone)
            dilated = affinity.scale(poly, EGRESS_DILATE, EGRESS_DILATE, origin="centroid")
            t_first = tr.frames[0].t
            for other in order:
                if other.id == tr.id or other.camera_id != tr.camera_id:
                    continue
                if other.cls not in TOUCH_CLASSES:
                    continue
                # Tracks already tagged use their final origin (a voided one counts as not
                # born in the door); tracks born in the same instant use their raw origin.
                theirs = final[other.id] if other.id in final else raw[other.id]
                if theirs == zone:
                    continue
                if _near_egress(other, dilated, t_first - EGRESS_VOID_S, t_first):
                    zone = None
                    break
        final[tr.id] = zone
    return final


def assign_origins(
    tracks: Sequence[Track],
    cfg: Config,
    *,
    observation: Observation | None = None,
    first_s: float = ORIGIN_FIRST_S,
) -> dict[str, str | None]:
    """Set ``origin_zone`` on every track of a configured camera, in place (FR-008).

    Returns ``{track_id: origin_zone}``. Tracks on unknown cameras are left untouched and
    omitted. The result does not depend on input order. ``observation`` gives the
    observed spans per camera (:meth:`Observation.from_windows`); ``None`` treats every
    camera as observed.
    """
    tags = _tag_origins(tracks, cfg, observation, first_s)
    for tr in tracks:
        if tr.id in tags:
            tr.origin_zone = tags[tr.id]
    return tags


def origin_zone(
    track: Track,
    cfg: Config,
    first_s: float = ORIGIN_FIRST_S,
    *,
    others: Iterable[Track] = (),
    observation: Observation | None = None,
) -> str | None:
    """The FR-008 origin of one track (spec 9.5 interface), without mutating anything.

    ``others`` are the session's other tracks (needed for egress voiding; tracks on other
    cameras are ignored). ``observation`` as in :func:`assign_origins`.
    """
    pool = [track, *(o for o in others if o.id != track.id)]
    return _tag_origins(pool, cfg, observation, first_s).get(track.id)


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
    observation: Observation | None = None,
    absence_s: float = REMOVE_ABSENCE_S,
) -> list[Event]:
    """Build the events of FR-008 from stitched tracks (spec 9.5 interface).

    Tracks on cameras missing from ``cfg`` are ignored. Events are returned sorted by
    (t0, camera, type, track, target) with ``visit_id``, ``subject_id`` and ``actor_role``
    unset (assigned by reasoning, FR-044). As a side effect every track on a configured
    camera gets its ``origin_zone`` (:func:`assign_origins`, using ``observation``; ``None``
    treats every camera as observed).
    """
    if absence_s < 0:
        raise ValueError("absence_s must be nonnegative")
    assign_origins(tracks, cfg, observation=observation)
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
    raws += _removed_events(
        known, watches, cams, touch_overlap, REMOVE_BEFORE_S, REMOVE_AFTER_S, observation, absence_s
    )

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
