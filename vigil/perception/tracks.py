"""Stitch SAM object ids across overlapping windows by IoU (FR-007).

SAM ids are only stable inside one response, so a person who walks through three
overlapping windows comes back as three ids. Objects of the same camera and noun phrase in
different windows are joined when their boxes agree (mean IoU) on the frames both windows
cover. Matching is one-to-one between any two windows, a track never holds two ids of the
same window, and the result does not depend on input order.

Track ids are ``f"{camera}-{cls}-{n}"`` numbered by first appearance per camera and class;
tags ``T1..Tn`` (burned into clips for Spark, FR-009) are numbered by first appearance over
all cameras.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vigil.models import Box, SamObject, Track, TrackClass, TrackFrame

IOU_THRESHOLD = 0.5
MIN_SHARED_FRAMES = 1
EDGE_PX = 1.0
"""A box whose bottom is within this many pixels of the image's bottom edge is clipped."""

_CLASS_WORDS: dict[str, TrackClass] = {
    "person": "person",
    "people": "person",
    "pedestrian": "person",
    "human": "person",
    "car": "car",
    "cars": "car",
    "vehicle": "car",
    "package": "package",
    "packages": "package",
    "parcel": "package",
    "delivery box": "package",
}

TrackLink = tuple[str, str, int]
"""(track id, window id, SAM object id): one row of the track_windows table (spec 9.3)."""


def phrase_class(phrase: str) -> TrackClass:
    """Map a SAM noun phrase to the contract's track class (anything else is "object")."""
    return _CLASS_WORDS.get(" ".join(phrase.lower().split()), "object")


def _key(t: float) -> int:
    """Millisecond key so frames of overlapping windows line up despite float error."""
    return round(t * 1000)


def _frame_map(obj: SamObject) -> dict[int, Box]:
    return {_key(f.t): f.box for f in obj.frames}


def _match_score(a: dict[int, Box], b: dict[int, Box], min_shared: int) -> float | None:
    shared = sorted(a.keys() & b.keys())
    if len(shared) < max(1, min_shared):
        return None
    return sum(a[k].iou(b[k]) for k in shared) / len(shared)


class _Union:
    def __init__(self, objs: Sequence[SamObject]) -> None:
        self.parent = list(range(len(objs)))
        self.windows = [{o.window_id} for o in objs]

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> bool:
        ri, rj = self.find(i), self.find(j)
        if ri == rj or self.windows[ri] & self.windows[rj]:
            return False
        lo, hi = min(ri, rj), max(ri, rj)
        self.parent[hi] = lo
        self.windows[lo] |= self.windows[hi]
        return True


def _obj_sort_key(o: SamObject) -> tuple:
    first = min((f.t for f in o.frames), default=0.0)
    return (o.camera_id, o.phrase, first, o.window_id, o.obj_id)


def _height_for(camera_id: str, frame_height: int | Mapping[str, int]) -> int:
    if isinstance(frame_height, Mapping):
        return int(frame_height.get(camera_id, 720))
    return int(frame_height)


def _merge_frames(members: list[SamObject], height: int, edge_px: float) -> list[TrackFrame]:
    best: dict[int, tuple[tuple, TrackFrame]] = {}
    for rank, obj in enumerate(members):
        for f in obj.frames:
            conf = f.confidence if f.confidence is not None else -1.0
            # Higher confidence wins; ties go to the earlier window.
            score = (conf, -rank)
            k = _key(f.t)
            if k in best and best[k][0] >= score:
                continue
            best[k] = (
                score,
                TrackFrame(
                    t=f.t,
                    box=f.box,
                    mask_rle=f.mask_rle,
                    confidence=f.confidence,
                    clipped=f.box.y2 >= height - edge_px,
                ),
            )
    return [best[k][1] for k in sorted(best)]


def stitch_with_links(
    objs: Sequence[SamObject],
    *,
    iou_threshold: float = IOU_THRESHOLD,
    min_shared: int = MIN_SHARED_FRAMES,
    frame_height: int | Mapping[str, int] = 720,
    edge_px: float = EDGE_PX,
) -> tuple[list[Track], list[TrackLink]]:
    """Stitch objects into tracks and return the (track, window, SAM id) links too."""
    ordered = sorted((o for o in objs if o.frames), key=_obj_sort_key)
    uf = _Union(ordered)
    maps = [_frame_map(o) for o in ordered]

    groups: dict[tuple[str, str], list[int]] = {}
    for i, o in enumerate(ordered):
        groups.setdefault((o.camera_id, o.phrase), []).append(i)

    for idx in groups.values():
        candidates: list[tuple[float, int, int]] = []
        for a_pos, i in enumerate(idx):
            for j in idx[a_pos + 1 :]:
                if ordered[i].window_id == ordered[j].window_id:
                    continue
                score = _match_score(maps[i], maps[j], min_shared)
                if score is not None and score >= iou_threshold:
                    candidates.append((-score, i, j))
        used: set[tuple[int, str]] = set()
        for _, i, j in sorted(candidates):
            wi, wj = ordered[i].window_id, ordered[j].window_id
            if (i, wj) in used or (j, wi) in used:
                continue
            if uf.union(i, j):
                used.add((i, wj))
                used.add((j, wi))

    components: dict[int, list[int]] = {}
    for i in range(len(ordered)):
        components.setdefault(uf.find(i), []).append(i)

    drafts: list[tuple[tuple, list[SamObject], list[TrackFrame]]] = []
    for members_idx in components.values():
        members = [ordered[i] for i in sorted(members_idx, key=lambda i: _obj_sort_key(ordered[i]))]
        cam = members[0].camera_id
        frames = _merge_frames(members, _height_for(cam, frame_height), edge_px)
        first = frames[0]
        sort_key = (
            cam,
            phrase_class(members[0].phrase),
            first.t,
            first.box.x1,
            first.box.y1,
            members[0].phrase,
            members[0].window_id,
            members[0].obj_id,
        )
        drafts.append((sort_key, members, frames))
    drafts.sort(key=lambda d: d[0])

    counters: dict[tuple[str, str], int] = {}
    tracks: list[Track] = []
    links: list[TrackLink] = []
    for _, members, frames in drafts:
        cam = members[0].camera_id
        cls = phrase_class(members[0].phrase)
        n = counters.get((cam, cls), 0) + 1
        counters[(cam, cls)] = n
        track_id = f"{cam}-{cls}-{n}"
        window_order: dict[str, float] = {}
        for m in members:
            t0 = min(f.t for f in m.frames)
            window_order[m.window_id] = min(window_order.get(m.window_id, t0), t0)
        tracks.append(
            Track(
                id=track_id,
                camera_id=cam,
                cls=cls,
                t_first=frames[0].t,
                t_last=frames[-1].t,
                frames=frames,
                window_ids=sorted(window_order, key=lambda w: (window_order[w], w)),
                phrase=members[0].phrase,
            )
        )
        links += [(track_id, m.window_id, m.obj_id) for m in members]

    for n, tr in enumerate(sorted(tracks, key=lambda t: (t.t_first, t.camera_id, t.id)), 1):
        tr.tag = f"T{n}"
    return tracks, sorted(links)


def stitch(
    objs: Sequence[SamObject],
    *,
    iou_threshold: float = IOU_THRESHOLD,
    min_shared: int = MIN_SHARED_FRAMES,
    frame_height: int | Mapping[str, int] = 720,
    edge_px: float = EDGE_PX,
) -> list[Track]:
    """Join SAM ids across overlapping windows into tracks (FR-007). Spec 9.5 interface."""
    tracks, _ = stitch_with_links(
        objs,
        iou_threshold=iou_threshold,
        min_shared=min_shared,
        frame_height=frame_height,
        edge_px=edge_px,
    )
    return tracks
