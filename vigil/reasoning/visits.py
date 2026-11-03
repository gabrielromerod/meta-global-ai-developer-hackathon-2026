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

Spatial origin roles (FR-044, :func:`assign_roles`). Every *subject chain* (tracks joined by
links) gets an ``actor_role`` and a ``role_basis`` from evidence only, never from identity:

1. first track born in an ``egress`` zone -> ``household_insider`` (``egress:<zone>``);
2. an explicit owner check-in binds it -> ``household_insider`` (``checkin:<id>``). Single
   use, never retroactive: when the 120 s after the tap close, it binds the one person chain
   whose first track started in that interval with origin ``null``, ``interior_yard`` or
   ``perimeter``, if exactly one started and every other subject (person or car) in view on
   any camera at that chain's first frame is ``household_insider``; otherwise nothing;
3. first track born in a ``perimeter`` zone in the scope of an Expected Window active at that
   frame -> ``expected_visitor`` (``window:<id>``). Never retroactive: the frame must be at
   or after both the window's start and its ``created_at``;
4. born in a ``perimeter`` zone -> ``external_visitor`` (``perimeter:<zone>``);
5. otherwise ``unknown``: ``ambiguous_link:<track>`` when the first track followed an
   ambiguous link, else ``origin_null:<track>``. The FR-010 group rule (``group:<role>``) is
   the only exception: on a non-blind edge, when 2+ chains of one non-unknown role entered the
   edge together and the same number of tracks emerged, each emerging chain takes that role.

Roles carry along unambiguous links. Across a blind-spot link ``external_visitor`` (and
``unknown``) always carries; ``household_insider`` and ``expected_visitor`` carry only when the
two tracks' notes agree exactly on a known upper colour, lower colour or carried item.
Otherwise the chain is split at the gap: what was seen before keeps its backed role, and the
re-linked part becomes ``unknown`` (``gap_unresolved:<gap_id>``), so a role is never
retroactively erased and never carried on transit time alone.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Point, Polygon

from vigil.models import (
    Appearance,
    CheckIn,
    Config,
    Event,
    ExpectedWindow,
    Gap,
    Position,
    Subject,
    Track,
    Visit,
)
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
    gap_id: str | None = None
    """The resolved gap this link closes (blind spot or outage), if any."""


class Candidate(BaseModel):
    """An unlinked candidate pairing behind an ``ambiguous_link`` gap (module-local)."""

    model_config = ConfigDict(extra="forbid")

    from_track: str
    to_track: str
    blind: bool
    """The pairing would pass through a blind region."""


class VisitAssembly(BaseModel):
    """Result of :func:`assemble_visits` (module-local; requested for vigil.models)."""

    model_config = ConfigDict(extra="forbid")

    visits: list[Visit] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    """Input events with ``visit_id``, ``subject_id`` and ``actor_role`` set, sorted by time."""
    subjects: list[Subject] = Field(default_factory=list)
    """Subject chains with their spatial-origin roles (FR-044)."""
    candidates: list[Candidate] = Field(default_factory=list)
    """Ambiguous (unlinked) candidate pairings, for the role rules and the trace."""
    checkins: list[CheckIn] = Field(default_factory=list)
    """The check-ins passed in, with ``bound_subject`` set where one bound a chain."""


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
    changing_light = a.illumination in {"mixed", "infrared"} or b.illumination in {
        "mixed",
        "infrared",
    }
    if not changing_light and not all(_colours_agree(x, y) for x, y in pairs):
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
    subject_prefix: str = "s",
    start_index: int = 1,
    windows: Sequence[ExpectedWindow] = (),
    checkins: Sequence[CheckIn] = (),
    session_start: datetime | None = None,
    replay_bindings: Mapping[str, tuple[str, float, str]] | None = None,
    truncated_after: Mapping[str, float] | None = None,
) -> VisitAssembly:
    """Link tracks into visits, record every out-of-view interval as a gap, assign roles.

    `notes` maps track id (or burned-in tag) to :class:`Appearance` or its dict form.
    `now` (session seconds) leaves visits ``open``/``in_gap`` when they could still continue;
    without it every visit is ``closed`` (offline processing). `windows` and `checkins`
    (FR-029) are wall-clock inputs to the role rules and need the tz-aware `session_start`;
    without them FR-044 steps 2 and 3 never match.
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
    blocked_handoffs: dict[str, tuple[Track, str]] = {}
    for t in subjects:
        exit_region = _exit_region(t, events)
        toward = _toward_region(t, positions, cfg) if exit_region is None else None
        headed[t.id] = toward or exit_leads_to_blind(cfg, t.camera_id, exit_region)
        rs = candidate_routes(cfg, t.camera_id, exit_region, toward)
        truncated = (truncated_after or {}).get(t.camera_id)
        if truncated is not None and t.t_first <= truncated <= t.t_last + OUTAGE_EPS_S:
            rs = []
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
                if t.camera_id != s.camera_id:
                    cameras = [cfg.camera(t.camera_id), cfg.camera(s.camera_id)]
                    reason = None
                    if any(
                        c.clock_offset_s is not None and abs(c.clock_offset_s) > 2 for c in cameras
                    ):
                        reason = "clock_drift"
                    elif gap > 0 and any(
                        c.power_profile in {"battery_wifi", "import"} for c in cameras
                    ):
                        reason = "battery_wake"
                    if reason:
                        previous = blocked_handoffs.get(t.id)
                        if previous is None or s.t_first < previous[0].t_first:
                            blocked_handoffs[t.id] = (s, reason)
                        continue
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
    unlinked: list[Candidate] = []
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
            unlinked += [
                Candidate(from_track=t.id, to_track=sid, blind=r.blind or region is not None)
                for sid, r in sorted(cs.items())
            ]
            succ = [known[sid] for sid in cs]
            cams = {s.camera_id for s in succ}
            to_cam = next(iter(cams)) if len(cams) == 1 else None
            t1 = max(s.t_first for s in succ)
            raw_gaps.append((t.id, _gap("ambiguous_link", t, t1, to_cam, region, resolved=False)))
        elif t.id in blocked_handoffs:
            successor, reason = blocked_handoffs[t.id]
            raw_gaps.append((t.id, _gap(reason, t, successor.t_first, None, None, resolved=False)))
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

    for t in subjects:
        truncated = (truncated_after or {}).get(t.camera_id)
        if truncated is not None and t.t_first <= truncated <= t.t_last + OUTAGE_EPS_S:
            raw_gaps.append(
                (
                    t.id,
                    Gap(
                        id="",
                        visit_id="",
                        kind="clip_truncated",
                        t0=truncated,
                        t1=truncated,
                        from_camera=t.camera_id,
                        resolved=False,
                    ),
                )
            )

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

    subject_track: dict[str, str] = {}  # event id -> the subject track it is about

    def owner(e: Event) -> str:
        tr = known[e.track_id]
        if tr.cls in SUBJECT_CLASSES:
            subject_track[e.id] = tr.id
            return uf.find(tr.id)
        near = [
            s
            for s in subjects
            if s.camera_id == e.camera_id
            and s.t_first - EVENT_ATTACH_EPS_S <= e.t0 <= s.t_last + EVENT_ATTACH_EPS_S
        ]
        if near:
            best = min(near, key=lambda s: (max(0.0, s.t_first - e.t0, e.t0 - s.t_last), s.id))
            subject_track[e.id] = best.id
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

    keyed = sorted(
        ((tid, g.model_copy(update={"visit_id": visit_id[uf.find(tid)]})) for tid, g in raw_gaps),
        key=lambda x: (x[1].t0, x[1].t1, x[1].from_camera or "", x[1].kind, x[1].visit_id),
    )
    gaps = []
    resolved_gap_of: dict[str, str] = {}  # from-track id -> id of the gap its link closes
    for i, (tid, g) in enumerate(keyed):
        g = g.model_copy(update={"id": f"{gap_prefix}{start_index + i}"})
        gaps.append(g)
        if g.resolved:
            resolved_gap_of.setdefault(tid, g.id)
    links = [lk.model_copy(update={"gap_id": resolved_gap_of.get(lk.from_track)}) for lk in links]
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
    unlinked.sort(key=lambda c: (c.from_track, c.to_track))
    asm = VisitAssembly(
        visits=visits, gaps=gaps, links=links, events=out_events, candidates=unlinked
    )

    # --- 4. roles (FR-044) ----------------------------------------------------
    subjects_out = assign_roles(
        asm,
        all_tracks,
        cfg,
        notes=app,
        windows=windows,
        checkins=checkins,
        session_start=session_start,
        subject_prefix=subject_prefix,
        start_index=start_index,
        replay_bindings=replay_bindings,
    )
    of_track = {tid: s for s in subjects_out for tid in s.track_ids}
    roled: list[Event] = []
    for e in out_events:
        s = of_track.get(subject_track.get(e.id, ""))
        roled.append(
            e.model_copy(update={"subject_id": s.id, "actor_role": s.actor_role}) if s else e
        )
    bound = {
        s.role_basis.removeprefix("checkin:"): s.id
        for s in subjects_out
        if s.role_basis.startswith("checkin:")
    }
    used = [
        c.model_copy(update={"bound_subject": bound[c.id]}) if c.id in bound else c
        for c in checkins
    ]
    return asm.model_copy(update={"events": roled, "subjects": subjects_out, "checkins": used})


# ---------------------------------------------------------------------------
# Spatial origin roles (FR-044)
# ---------------------------------------------------------------------------

CHECKIN_BIND_S = 120.0
"""A check-in binds a chain whose first track starts within this many seconds of the tap."""
CARRY_GUARDED = frozenset({"household_insider", "expected_visitor"})
"""Roles that need a matching known appearance attribute to carry across a blind spot."""


@dataclass
class _Segment:
    """One role-holding part of a subject chain (a chain splits where its role breaks)."""

    tracks: list[Track]
    role: str
    basis: str
    chain_head: bool
    """True when this segment starts a chain (FR-044 'first track'), not a split at a gap."""
    origin_kind: str | None = None
    checkin_ids: list[str] = field(default_factory=list)


def attribute_match(a: Appearance | None, b: Appearance | None) -> bool:
    """Both notes agree exactly on at least one known attribute (FR-044 blind-spot carry)."""
    if a is None or b is None:
        return False
    if _known(a.upper_color) and a.upper_color == b.upper_color:
        return True
    if _known(a.lower_color) and a.lower_color == b.lower_color:
        return True
    items = {c for c in a.carrying if c and c != "unknown"}
    return bool(items & set(b.carrying))


def _session_s(dt: datetime, session_start: datetime) -> float:
    return (dt - session_start).total_seconds()


def _origin_kind(track: Track, cfg: Config) -> str | None:
    if track.origin_zone is None:
        return None
    try:
        cam = cfg.camera(track.camera_id)
    except KeyError:
        return "interior_yard"
    return cam.zone_kind(track.origin_zone)


def _window_for(
    track: Track,
    windows: Sequence[ExpectedWindow],
    session_start: datetime | None,
) -> ExpectedWindow | None:
    if session_start is None:
        return None
    for w in sorted(windows, key=lambda w: (w.start, w.id)):
        if w.state == "cancelled":
            continue
        # never retroactive (FR-029): a track seen before the owner set the window is not in it
        opens = w.start if w.created_at is None else max(w.start, w.created_at)
        if not _session_s(opens, session_start) <= track.t_first < _session_s(w.end, session_start):
            continue
        if (w.cameras or w.zones) and not (
            track.camera_id in w.cameras or track.origin_zone in w.zones
        ):
            continue
        return w
    return None


def _group_roles(
    preds: Mapping[str, set[str]],
    succs: Mapping[str, set[str]],
    blind_pairs: set[tuple[str, str]],
    known: Mapping[str, Track],
    role_of: Mapping[str, str],
    sid: str,
) -> str | None:
    """FR-010 group rule for successor `sid`, or None when it does not apply."""
    p_set = preds.get(sid, set())
    if len(p_set) < 2:
        return None
    s_set = succs[next(iter(p_set))]
    if len(s_set) != len(p_set):
        return None
    if any(succs.get(p) != s_set for p in p_set) or any(preds.get(s) != p_set for s in s_set):
        return None
    if any((p, s) in blind_pairs for p in p_set for s in s_set):
        return None  # never across a blind-spot edge
    if (
        len({known[p].camera_id for p in p_set}) != 1
        or len({known[s].camera_id for s in s_set}) != 1
    ):
        return None
    roles = {role_of.get(p) for p in p_set}
    if len(roles) != 1:
        return None
    (role,) = roles
    return role if role not in (None, "unknown") else None


def _segments(
    order: Sequence[Track],
    known: Mapping[str, Track],
    pred_link: Mapping[str, Link],
    preds: Mapping[str, set[str]],
    succs: Mapping[str, set[str]],
    blind_pairs: set[tuple[str, str]],
    cfg: Config,
    notes: Mapping[str, Appearance],
    windows: Sequence[ExpectedWindow],
    session_start: datetime | None,
    bound: Mapping[str, str],
) -> tuple[list[_Segment], dict[str, int]]:
    segs: list[_Segment] = []
    seg_of: dict[str, int] = {}
    for t in order:
        lk = pred_link.get(t.id)
        if lk is not None and lk.from_track in seg_of:
            prev = segs[seg_of[lk.from_track]]
            breaks = (
                lk.blind
                and prev.role in CARRY_GUARDED
                and not attribute_match(notes.get(lk.from_track), notes.get(t.id))
            )
            if not breaks:
                prev.tracks.append(t)
                seg_of[t.id] = seg_of[lk.from_track]
                continue
            segs.append(_Segment([t], "unknown", f"gap_unresolved:{lk.gap_id}", False))
            seg_of[t.id] = len(segs) - 1
            continue
        kind = _origin_kind(t, cfg)
        if kind == "egress":
            role, basis = "household_insider", f"egress:{t.origin_zone}"
        elif t.id in bound:
            role, basis = "household_insider", f"checkin:{bound[t.id]}"
        elif kind == "perimeter" and (w := _window_for(t, windows, session_start)) is not None:
            role, basis = "expected_visitor", f"window:{w.id}"
        elif kind == "perimeter":
            role, basis = "external_visitor", f"perimeter:{t.origin_zone}"
        else:
            role_of = {tid: segs[i].role for tid, i in seg_of.items()}
            group = _group_roles(preds, succs, blind_pairs, known, role_of, t.id)
            if group is not None:
                role, basis = group, f"group:{group}"
            elif t.id in preds:
                role, basis = "unknown", f"ambiguous_link:{t.id}"
            else:
                role, basis = "unknown", f"origin_null:{t.id}"
        segs.append(_Segment([t], role, basis, True, kind))
        seg_of[t.id] = len(segs) - 1
    return segs, seg_of


def assign_roles(
    assembly: VisitAssembly,
    tracks: Sequence[Track],
    cfg: Config,
    *,
    notes: Mapping[str, Any] | None = None,
    windows: Sequence[ExpectedWindow] = (),
    checkins: Sequence[CheckIn] = (),
    session_start: datetime | None = None,
    subject_prefix: str = "s",
    start_index: int = 1,
    replay_bindings: Mapping[str, tuple[str, float, str]] | None = None,
) -> list[Subject]:
    """Subject chains of an assembly with their spatial-origin roles (FR-044, module docs).

    Deterministic and pure: check-ins are processed in tap order, each against the roles that
    hold before it binds. A check-in that binds shows as a subject with basis
    ``checkin:<id>``. `windows` and `checkins` are wall-clock and need `session_start`.
    """
    if (windows or checkins) and (session_start is None or session_start.utcoffset() is None):
        raise ValueError("expected windows and check-ins need a timezone-aware session_start")
    known = {t.id: t for t in tracks}
    known.update(_synthesise_tracks(assembly.events, known))
    in_visit = {tid for v in assembly.visits for tid in v.track_ids}
    order = sorted(
        (t for t in known.values() if t.cls in SUBJECT_CLASSES and t.id in in_visit),
        key=lambda t: (t.t_first, t.id),
    )
    app = _normalise_notes(notes, known.values())
    pred_link = {lk.to_track: lk for lk in assembly.links}
    preds: dict[str, set[str]] = defaultdict(set)
    succs: dict[str, set[str]] = defaultdict(set)
    blind_pairs: set[tuple[str, str]] = set()
    for c in assembly.candidates:
        preds[c.to_track].add(c.from_track)
        succs[c.from_track].add(c.to_track)
        if c.blind:
            blind_pairs.add((c.from_track, c.to_track))

    def compute(bound: Mapping[str, str]) -> tuple[list[_Segment], dict[str, int]]:
        return _segments(
            order, known, pred_link, preds, succs, blind_pairs, cfg, app, windows,
            session_start, bound,
        )  # fmt: skip

    bound: dict[str, str] = {}
    if checkins:
        assert session_start is not None
        for c in sorted(checkins, key=lambda c: (c.start, c.id)):
            if c.revoked:
                continue
            segs, _ = compute(bound)
            head = _checkin_target(c, segs, session_start)
            if c.bound_subject is not None:
                prior = (replay_bindings or {}).get(c.id)
                if (
                    prior
                    and head is not None
                    and c.bound_subject == prior[2]
                    and head.id == prior[0]
                    and abs(head.t_first - prior[1]) < 1e-6
                ):
                    bound[head.id] = c.id
                continue
            if head is not None and head.id not in bound:
                bound[head.id] = c.id
    segs, _ = compute(bound)

    visit_of = {tid: v.id for v in assembly.visits for tid in v.track_ids}
    segs.sort(key=lambda s: (s.tracks[0].t_first, s.tracks[0].id))
    return [
        Subject(
            id=f"{subject_prefix}{start_index + i}",
            visit_id=visit_of.get(s.tracks[0].id),
            track_ids=[t.id for t in s.tracks],
            actor_role=s.role,
            role_basis=s.basis,
        )
        for i, s in enumerate(segs)
    ]


def _checkin_target(c: CheckIn, segs: Sequence[_Segment], session_start: datetime) -> Track | None:
    """The one chain head a check-in binds when its 120 s interval closes, else None."""
    t0 = _session_s(c.start, session_start)
    t1 = min(t0 + CHECKIN_BIND_S, _session_s(c.expires, session_start))
    heads = [
        s
        for s in segs
        if s.chain_head
        and s.tracks[0].cls == "person"
        and s.origin_kind != "egress"
        and t0 <= s.tracks[0].t_first <= t1
    ]
    if len(heads) != 1:
        return None
    (seg,) = heads
    first = seg.tracks[0].t_first
    for other in segs:
        if other is seg or other.role == "household_insider":
            continue
        if other.tracks[0].cls == "car" and other.basis.startswith("origin_null:"):
            continue  # a car parked in view since observation began is scenery, not a tapper
        if any(t.cls in SUBJECT_CLASSES and t.t_first <= first <= t.t_last for t in other.tracks):
            return None  # a non-household subject (person or car) is in view: ambiguous tap
    return seg.tracks[0]


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
