"""Visit assembly and gaps (FR-010, FR-011, spec 5.9). Code links; models never do.

A *subject* track (person or car) that ends is linked to a later subject track only when

1. a topology route allows the time gap (``topology.candidate_routes``), and
2. the appearance notes agree (unknown colours never disagree: IR footage at night), and
3. the pairing is unique both ways: one candidate successor, and that successor has one
   candidate predecessor. Two or more candidates means no link and an ``ambiguous_link`` gap.

Only the *first arrival* on each camera is a candidate (plus anyone arriving while that first
arrival is still in view): a later sighting on the same camera is the chain's next step, not a
competing candidate.

Every interval where a visit's subject is out of view because of a blind region, an ambiguous
hand-off or a camera outage becomes a :class:`~vigil.models.Gap`. A hand-off between adjacent
views along a non-blind edge, or a same-camera re-acquisition within a few seconds, is not a
gap. Tracks overlapping in time on the same camera (a person getting into a car) share a
visit. A visit closes 60 s after its last observation, or once the maximum transit through
the blind region it entered is exceeded (spec 5.9 ``InGap -> Closed``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Point, Polygon

from vigil.models import Appearance, Config, Event, Gap, Position, Track, Visit
from vigil.reasoning.topology import (
    DEFAULT_TRANSIT_MAX_S,
    Route,
    candidate_routes,
    exit_leads_to_blind,
)

VISIT_CLOSE_S = 60.0
"""A visit closes after 60 s with no linked event (spec 5.9)."""
SUBJECT_CLASSES = frozenset({"person", "car"})
OUTAGE_EPS_S = 2.0
"""An outage starting this soon after a track ends caught the subject in view."""
EVENT_ATTACH_EPS_S = 1.0
POSITION_MARGIN_M = 0.5
"""Extra distance beyond r95 at which a last position counts as heading into a blind region."""

_NEAR_COLOURS = {
    frozenset(p)
    for p in [
        ("navy", "blue"),
        ("navy", "black"),
        ("grey", "white"),
        ("grey", "black"),
        ("beige", "brown"),
        ("beige", "white"),
        ("red", "orange"),
        ("red", "pink"),
        ("purple", "pink"),
    ]
}


class Outage(BaseModel):
    """A camera offline interval (UC-11), on the session clock."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    t0: float
    t1: float


class Link(BaseModel):
    """One accepted cross-track link (module-local; requested for vigil.models)."""

    model_config = ConfigDict(extra="forbid")

    from_track: str
    to_track: str
    from_camera: str
    to_camera: str
    t0: float
    """End of the earlier track."""
    t1: float
    """Start of the later track."""
    gap_s: float
    route_kind: str
    blind: bool
    region_id: str | None = None


class VisitAssembly(BaseModel):
    """Result of :func:`assemble_visits` (module-local; requested for vigil.models)."""

    model_config = ConfigDict(extra="forbid")

    visits: list[Visit] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    """Input events with ``visit_id`` set, sorted by time."""


# ---------------------------------------------------------------------------
# Appearance agreement
# ---------------------------------------------------------------------------


def _known(c: str | None) -> bool:
    return c is not None and c != "unknown"


def _colours_agree(a: str | None, b: str | None) -> bool:
    if not (_known(a) and _known(b)) or a == b:
        return True
    return frozenset((a, b)) in _NEAR_COLOURS


def appearance_agrees(a: Appearance | None, b: Appearance | None) -> bool:
    """Notes agree unless a known field clearly differs. Missing or unknown never disagrees."""
    if a is None or b is None:
        return True
    if a.class_ != b.class_:
        return False
    pairs = [
        (a.upper_color, b.upper_color),
        (a.lower_color, b.lower_color),
        (a.vehicle_color, b.vehicle_color),
    ]
    if not all(_colours_agree(x, y) for x, y in pairs):
        return False
    return not (a.vehicle_body and b.vehicle_body and a.vehicle_body != b.vehicle_body)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def _normalise_notes(notes: Mapping[str, Any] | None, tracks: Iterable[Track]) -> dict[str, Any]:
    out: dict[str, Appearance] = {}
    if not notes:
        return out
    by_tag = {t.tag: t.id for t in tracks if t.tag}
    for key, val in notes.items():
        app = val if isinstance(val, Appearance) else Appearance.model_validate(val)
        out[by_tag.get(key, key)] = app
    return out


def _synthesise_tracks(events: Sequence[Event], known: dict[str, Track]) -> dict[str, Track]:
    """Events may reference tracks the caller did not pass; give them minimal subject tracks."""
    spans: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        if e.track_id not in known:
            spans[e.track_id].append(e)
    return {
        tid: Track(
            id=tid,
            camera_id=evs[0].camera_id,
            cls="person",
            t_first=min(e.t0 for e in evs),
            t_last=max(e.t1 for e in evs),
        )
        for tid, evs in spans.items()
    }


def _exit_region(track: Track, events: Sequence[Event]) -> str | None:
    exits = [
        e for e in events if e.track_id == track.id and e.type == "exit" and e.target is not None
    ]
    return max(exits, key=lambda e: (e.t0, e.id)).target if exits else None


def _toward_region(track: Track, positions: Sequence[Position], cfg: Config) -> str | None:
    mine = [p for p in positions if p.track_id == track.id]
    if not mine or not cfg.blind_regions:
        return None
    last = max(mine, key=lambda p: p.t)
    pt = Point(last.x, last.z)
    best: tuple[float, str] | None = None
    for region in cfg.blind_regions:
        if len(region.polygon_m) < 3:
            continue
        d = Polygon(region.polygon_m).distance(pt)
        if d <= last.r95 + POSITION_MARGIN_M and (best is None or (d, region.id) < best):
            best = (d, region.id)
    return best[1] if best else None


def _route_rank(r: Route) -> tuple[int, int]:
    # Prefer the conservative explanation: through a blind region before a plain hand-off.
    return (0 if r.blind else 1, {"via_region": 0, "direct": 1, "reacquire": 2}[r.kind])


def assemble_visits(
    events: Sequence[Event],
    tracks: Sequence[Track],
    notes: Mapping[str, Any] | None,
    positions: Sequence[Position],
    cfg: Config,
    *,
    outages: Sequence[Outage] = (),
    now: float | None = None,
    visit_prefix: str = "v",
    gap_prefix: str = "g",
    start_index: int = 1,
) -> VisitAssembly:
    """Link tracks into visits and record every out-of-view interval as a gap.

    `notes` maps track id (or burned-in tag) to :class:`Appearance` or its dict form.
    `now` (session seconds) leaves visits ``open``/``in_gap`` when they could still continue;
    without it every visit is ``closed`` (offline processing).
    """
    events = sorted(events, key=lambda e: (e.t0, e.id))
    known = {t.id: t for t in tracks}
    known.update(_synthesise_tracks(events, known))
    all_tracks = sorted(known.values(), key=lambda t: (t.t_first, t.id))
    subjects = [t for t in all_tracks if t.cls in SUBJECT_CLASSES]
    app = _normalise_notes(notes, all_tracks)

    # --- 1. candidates ------------------------------------------------------
    headed: dict[str, str | None] = {}
    route_max: dict[str, float] = {}
    cands: dict[str, dict[str, Route]] = {}
    for t in subjects:
        exit_region = _exit_region(t, events)
        toward = _toward_region(t, positions, cfg) if exit_region is None else None
        headed[t.id] = toward or exit_leads_to_blind(cfg, t.camera_id, exit_region)
        rs = candidate_routes(cfg, t.camera_id, exit_region, toward)
        via = [r.max_s for r in rs if r.via_region is not None and r.via_region == headed[t.id]]
        route_max[t.id] = max(via, default=DEFAULT_TRANSIT_MAX_S)

        fitting: dict[str, Route] = {}
        for s in subjects:
            if s.id == t.id or s.cls != t.cls:
                continue
            gap = s.t_first - t.t_last
            if gap < 0 or not appearance_agrees(app.get(t.id), app.get(s.id)):
                continue
            ok = sorted(
                (r for r in rs if r.to_camera == s.camera_id and r.fits(gap)), key=_route_rank
            )
            if ok:
                fitting[s.id] = ok[0]
        # first arrival per camera, plus anyone arriving while it is still in view
        first: dict[str, Track] = {}
        for sid in fitting:
            s = known[sid]
            f = first.get(s.camera_id)
            if f is None or (s.t_first, s.id) < (f.t_first, f.id):
                first[s.camera_id] = s
        cands[t.id] = {
            sid: r
            for sid, r in fitting.items()
            if known[sid].t_first <= first[known[sid].camera_id].t_last
        }

    preds: dict[str, set[str]] = defaultdict(set)
    for tid, cs in cands.items():
        for sid in cs:
            preds[sid].add(tid)

    # --- 2. links and gaps --------------------------------------------------
    links: list[Link] = []
    raw_gaps: list[tuple[str, Gap]] = []  # (origin track id, gap without id/visit)
    linked_to: dict[str, Track] = {}
    for t in subjects:
        cs = cands[t.id]
        region = headed[t.id]
        if len(cs) == 1:
            ((sid, route),) = cs.items()
            if preds[sid] == {t.id}:
                s = known[sid]
                blind = route.blind or region is not None
                links.append(
                    Link(
                        from_track=t.id,
                        to_track=s.id,
                        from_camera=t.camera_id,
                        to_camera=s.camera_id,
                        t0=t.t_last,
                        t1=s.t_first,
                        gap_s=s.t_first - t.t_last,
                        route_kind=route.kind,
                        blind=blind,
                        region_id=route.via_region or region,
                    )
                )
                linked_to[t.id] = s
                if blind:
                    raw_gaps.append(
                        (t.id, _gap("blind_spot", t, s.t_first, s.camera_id,
                                    route.via_region or region, resolved=True))
                    )  # fmt: skip
                continue
        if cs:
            succ = [known[sid] for sid in cs]
            cams = {s.camera_id for s in succ}
            to_cam = next(iter(cams)) if len(cams) == 1 else None
            t1 = max(s.t_first for s in succ)
            raw_gaps.append((t.id, _gap("ambiguous_link", t, t1, to_cam, region, resolved=False)))
        elif region is not None:
            t1 = t.t_last + route_max[t.id]
            raw_gaps.append((t.id, _gap("blind_spot", t, t1, None, region, resolved=False)))

    gapped = {tid for tid, _ in raw_gaps}
    for t in subjects:
        if t.id in gapped:
            continue
        for o in sorted(outages, key=lambda o: (o.t0, o.camera_id)):
            if o.camera_id != t.camera_id:
                continue
            if not (t.t_first <= o.t0 <= t.t_last + OUTAGE_EPS_S):
                continue
            s = linked_to.get(t.id)
            g = Gap(
                id="",
                visit_id="",
                kind="outage",
                t0=min(o.t0, t.t_last),
                t1=min(o.t1, s.t_first) if s else o.t1,
                from_camera=t.camera_id,
                to_camera=s.camera_id if s else None,
                resolved=s is not None,
            )
            raw_gaps.append((t.id, g))
            break

    # --- 3. visits ------------------------------------------------------------
    uf = _UnionFind()
    for t in subjects:
        uf.find(t.id)
    for lk in links:
        uf.union(lk.from_track, lk.to_track)
    for i, a in enumerate(subjects):
        for b in subjects[i + 1 :]:
            if b.t_first > a.t_last:
                break  # sorted by t_first: nothing later overlaps `a`
            if a.camera_id == b.camera_id:
                uf.union(a.id, b.id)

    def owner(e: Event) -> str:
        tr = known[e.track_id]
        if tr.cls in SUBJECT_CLASSES:
            return uf.find(tr.id)
        near = [
            s
            for s in subjects
            if s.camera_id == e.camera_id
            and s.t_first - EVENT_ATTACH_EPS_S <= e.t0 <= s.t_last + EVENT_ATTACH_EPS_S
        ]
        if near:
            best = min(near, key=lambda s: (max(0.0, s.t_first - e.t0, e.t0 - s.t_last), s.id))
            return uf.find(best.id)
        return uf.find(tr.id)  # object event with nobody around: its own visit

    members: dict[str, list[Track]] = defaultdict(list)
    for t in subjects:
        members[uf.find(t.id)].append(t)
    ev_by_root: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        root = owner(e)
        ev_by_root[root].append(e)
        if root not in members:
            members[root].append(known[root])

    def span(root: str) -> tuple[float, float]:
        ts = members[root]
        es = ev_by_root.get(root, [])
        t0 = min([t.t_first for t in ts] + [e.t0 for e in es])
        t1 = max([t.t_last for t in ts] + [e.t1 for e in es])
        return t0, t1

    roots = sorted(members, key=lambda r: (span(r)[0], r))
    visit_id = {r: f"{visit_prefix}{start_index + i}" for i, r in enumerate(roots)}

    gaps = sorted(
        (g.model_copy(update={"visit_id": visit_id[uf.find(tid)]}) for tid, g in raw_gaps),
        key=lambda g: (g.t0, g.t1, g.from_camera or "", g.kind, g.visit_id),
    )
    gaps = [
        g.model_copy(update={"id": f"{gap_prefix}{start_index + i}"}) for i, g in enumerate(gaps)
    ]
    gaps_by_visit: dict[str, list[Gap]] = defaultdict(list)
    for g in gaps:
        gaps_by_visit[g.visit_id].append(g)

    visits: list[Visit] = []
    for r in roots:
        vid = visit_id[r]
        t0, t1 = span(r)
        vg = gaps_by_visit.get(vid, [])
        visits.append(
            Visit(
                id=vid,
                t0=t0,
                t1=t1,
                state=_state(t1, vg, now),
                track_ids=[t.id for t in sorted(members[r], key=lambda t: (t.t_first, t.id))],
                event_ids=[e.id for e in ev_by_root.get(r, [])],
                gap_ids=[g.id for g in vg],
            )
        )

    vid_of_event = {e.id: visit_id[r] for r, es in ev_by_root.items() for e in es}
    out_events = [e.model_copy(update={"visit_id": vid_of_event[e.id]}) for e in events]
    links.sort(key=lambda lk: (lk.t0, lk.from_track))
    return VisitAssembly(visits=visits, gaps=gaps, links=links, events=out_events)


def _gap(
    kind: str,
    t: Track,
    t1: float,
    to_camera: str | None,
    region: str | None,
    *,
    resolved: bool,
) -> Gap:
    return Gap(
        id="",
        visit_id="",
        kind=kind,
        t0=t.t_last,
        t1=t1,
        from_camera=t.camera_id,
        to_camera=to_camera,
        region_id=region,
        resolved=resolved,
    )


def _state(last_seen: float, gaps: Sequence[Gap], now: float | None) -> str:
    if now is None:
        return "closed"
    if any(g.kind == "blind_spot" and not g.resolved and now < g.t1 for g in gaps):
        return "in_gap"
    if now < last_seen + VISIT_CLOSE_S:
        return "open"
    return "closed"
