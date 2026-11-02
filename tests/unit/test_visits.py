"""Visit assembly and gaps (FR-010, FR-011, spec 5.9). Includes hypothesis properties."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vigil.models import Appearance, Config, Event, Position, Track
from vigil.reasoning.topology import candidate_routes, routes
from vigil.reasoning.visits import (
    VISIT_CLOSE_S,
    Outage,
    appearance_agrees,
    assemble_visits,
)

PROPS = settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


def trk(tid: str, cam: str, t0: float, t1: float, cls: str = "person") -> Track:
    return Track(id=tid, camera_id=cam, cls=cls, t_first=t0, t_last=t1)


def ev(eid: str, tid: str, cam: str, typ: str, t0: float, target: str | None = None) -> Event:
    return Event(
        id=eid,
        camera_id=cam,
        track_id=tid,
        type=typ,
        t0=t0,
        t1=t0 + 1.0,
        target=target,
        clip_t0=t0 - 2,
        clip_t1=t0 + 3,
    )


def note(tag: str, upper: str | None = "navy", lower: str | None = "grey") -> Appearance:
    return Appearance.model_validate(
        {"tag": tag, "class": "person", "upper_color": upper, "lower_color": lower}
    )


# ---------------------------------------------------------------------------
# Scenario C (UC-06): side_left -> behind the shed -> side_left after 41 s
# ---------------------------------------------------------------------------


def scenario_c() -> tuple[list[Event], list[Track], dict[str, Appearance]]:
    t_exit = 80070.0
    tracks = [trk("t1", "side_left", 80020.0, t_exit), trk("t2", "side_left", t_exit + 41, 80150)]
    events = [
        ev("e16", "t1", "side_left", "enter", 80020.0),
        ev("e17", "t1", "side_left", "touch", 80040.0, "po_side_gate"),
        ev("e18", "t1", "side_left", "exit", t_exit - 1, "to_shed_back"),
        ev("e19", "t2", "side_left", "enter", t_exit + 41),
        ev("e20", "t2", "side_left", "exit", 80149.0),
    ]
    notes = {"t1": note("T1", "unknown", "unknown"), "t2": note("T2", "unknown", "unknown")}
    return events, tracks, notes


def test_scenario_c_one_visit_with_41s_blind_gap(sample_config: Config) -> None:
    events, tracks, notes = scenario_c()
    out = assemble_visits(events, tracks, notes, [], sample_config)
    assert len(out.visits) == 1
    v = out.visits[0]
    assert v.track_ids == ["t1", "t2"]
    assert v.event_ids == ["e16", "e17", "e18", "e19", "e20"]
    assert v.state == "closed"
    assert len(out.gaps) == 1
    g = out.gaps[0]
    assert g.kind == "blind_spot"
    assert g.region_id == "shed_back"
    assert abs(g.duration_s - 41.0) <= 1.0
    assert (g.from_camera, g.to_camera, g.resolved) == ("side_left", "side_left", True)
    assert v.gap_ids == [g.id]
    assert g.visit_id == v.id
    assert all(e.visit_id == v.id for e in out.events)
    assert len(out.links) == 1
    assert out.links[0].blind


def test_blind_region_inferred_from_last_position(sample_config: Config) -> None:
    events, tracks, notes = scenario_c()
    events = [e for e in events if e.type != "exit"]
    pos = [
        Position(
            track_id="t1", t=80069.0, x=4.0, y=0, z=9.5, r95=0.4, method="footpoint", cameras=[]
        )
    ]
    out = assemble_visits(events, tracks, notes, pos, sample_config)
    assert len(out.visits) == 1
    assert out.gaps[0].region_id == "shed_back"


def test_unresolved_blind_gap_when_subject_never_returns(sample_config: Config) -> None:
    events, tracks, notes = scenario_c()
    tracks = tracks[:1]
    events = [e for e in events if e.track_id == "t1"]
    out = assemble_visits(events, tracks, notes, [], sample_config)
    assert len(out.visits) == 1
    (g,) = out.gaps
    assert g.kind == "blind_spot"
    assert not g.resolved
    assert g.t0 == 80070.0
    assert g.t1 == 80070.0 + 180.0  # max transit through the blind region (spec 5.9 InGap)
    assert g.to_camera is None


def test_visit_stays_in_gap_until_max_transit(sample_config: Config) -> None:
    events, tracks, notes = scenario_c()
    out = assemble_visits(events[:3], tracks[:1], notes, [], sample_config, now=80100.0)
    assert out.visits[0].state == "in_gap"
    out = assemble_visits(events[:3], tracks[:1], notes, [], sample_config, now=80300.0)
    assert out.visits[0].state == "closed"


def test_visit_open_until_60s_without_linked_event(sample_config: Config) -> None:
    tracks = [trk("t1", "front", 100, 110)]
    events = [ev("e1", "t1", "front", "enter", 100)]
    assert assemble_visits(events, tracks, {}, [], sample_config, now=150).visits[0].state == "open"
    out = assemble_visits(events, tracks, {}, [], sample_config, now=110 + VISIT_CLOSE_S)
    assert out.visits[0].state == "closed"


def test_two_sightings_on_same_camera_90s_apart_are_two_visits(sample_config: Config) -> None:
    tracks = [trk("t1", "front", 100, 110), trk("t2", "front", 200, 210)]
    events = [ev("e1", "t1", "front", "enter", 100), ev("e2", "t2", "front", "enter", 200)]
    out = assemble_visits(events, tracks, {}, [], sample_config)
    assert len(out.visits) == 2
    assert out.gaps == []
    assert out.links == []


def test_cross_camera_link_inside_window(sample_config: Config) -> None:
    tracks = [trk("t1", "front", 100, 110), trk("t2", "side_left", 115, 130)]
    events = [ev("e1", "t1", "front", "enter", 100), ev("e2", "t2", "side_left", "enter", 115)]
    notes = {"t1": note("T1"), "t2": note("T2")}
    out = assemble_visits(events, tracks, notes, [], sample_config)
    assert len(out.visits) == 1
    assert out.gaps == []  # a non-blind handoff between adjacent views is not a gap
    assert out.links[0].gap_s == 5.0


def test_no_link_outside_window(sample_config: Config) -> None:
    tracks = [trk("t1", "front", 100, 110), trk("t2", "side_left", 131, 140)]
    out = assemble_visits([], tracks, {}, [], sample_config)
    assert len(out.visits) == 2
    assert out.links == []


def test_appearance_disagreement_blocks_link(sample_config: Config) -> None:
    tracks = [trk("t1", "front", 100, 110), trk("t2", "side_left", 115, 130)]
    notes = {"t1": note("T1", "red", "grey"), "t2": note("T2", "green", "grey")}
    out = assemble_visits([], tracks, notes, [], sample_config)
    assert out.links == []
    assert len(out.visits) == 2


def test_unknown_colours_do_not_disagree() -> None:
    assert appearance_agrees(note("a", "unknown", "unknown"), note("b", "red", "blue"))
    assert appearance_agrees(note("a", None, None), note("b", "red", "blue"))
    assert appearance_agrees(None, note("b", "red", "blue"))
    assert appearance_agrees(note("a", "navy"), note("b", "blue"))  # near colours
    assert not appearance_agrees(note("a", "red"), note("b", "green"))
    car = Appearance.model_validate({"tag": "c", "class": "vehicle", "vehicle_color": "white"})
    assert not appearance_agrees(note("a"), car)


def test_two_candidates_mean_no_link_and_ambiguous_gap(sample_config: Config) -> None:
    tracks = [
        trk("t1", "front", 100, 110),
        trk("t2", "side_left", 115, 130),
        trk("t3", "side_right", 116, 130),
    ]
    events = [ev("e1", "t1", "front", "exit", 109)]
    out = assemble_visits(events, tracks, {}, [], sample_config)
    assert out.links == []
    amb = [g for g in out.gaps if g.kind == "ambiguous_link"]
    assert len(amb) == 1
    assert amb[0].t0 == 110
    assert amb[0].from_camera == "front"
    assert not amb[0].resolved


def test_two_origins_one_successor_is_ambiguous(sample_config: Config) -> None:
    tracks = [
        trk("t1", "side_left", 100, 110),
        trk("t2", "side_right", 101, 111),
        trk("t3", "front", 115, 130),
    ]
    out = assemble_visits([], tracks, {}, [], sample_config)
    assert out.links == []
    assert sorted(g.from_camera for g in out.gaps if g.kind == "ambiguous_link") == [
        "side_left",
        "side_right",
    ]


def test_later_chain_sighting_is_not_a_competing_candidate(sample_config: Config) -> None:
    # behind the shed twice: t1 -> (41 s) -> t2 -> (60 s) -> t3, all on side_left
    tracks = [
        trk("t1", "side_left", 0, 50),
        trk("t2", "side_left", 91, 100),
        trk("t3", "side_left", 160, 170),
    ]
    events = [
        ev("e1", "t1", "side_left", "exit", 49, "to_shed_back"),
        ev("e2", "t2", "side_left", "exit", 99, "to_shed_back"),
    ]
    out = assemble_visits(events, tracks, {}, [], sample_config)
    assert len(out.visits) == 1
    assert [(lk.from_track, lk.to_track) for lk in out.links] == [("t1", "t2"), ("t2", "t3")]
    assert [g.kind for g in out.gaps] == ["blind_spot", "blind_spot"]


def test_person_and_car_co_present_form_one_visit(sample_config: Config) -> None:
    tracks = [trk("t1", "front", 100, 130), trk("c1", "front", 90, 200, cls="car")]
    events = [ev("e1", "t1", "front", "enter", 100), ev("e2", "c1", "front", "exit", 199)]
    out = assemble_visits(events, tracks, {}, [], sample_config)
    assert len(out.visits) == 1
    assert set(out.visits[0].track_ids) == {"t1", "c1"}


def test_object_events_join_the_co_present_visit(sample_config: Config) -> None:
    tracks = [trk("t1", "front", 100, 130), trk("p1", "front", 0, 120, cls="package")]
    events = [ev("e1", "t1", "front", "enter", 100), ev("e2", "p1", "front", "removed", 118, "w2")]
    out = assemble_visits(events, tracks, {}, [], sample_config)
    assert len(out.visits) == 1
    assert out.visits[0].event_ids == ["e1", "e2"]
    assert "p1" not in out.visits[0].track_ids


def test_outage_becomes_gap(sample_config: Config) -> None:
    tracks = [trk("t1", "backyard", 100, 120)]
    events = [ev("e1", "t1", "backyard", "enter", 100)]
    out = assemble_visits(
        events,
        tracks,
        {},
        [],
        sample_config,
        outages=[Outage(camera_id="backyard", t0=120.5, t1=150)],
    )
    (g,) = out.gaps
    assert (g.kind, g.t0, g.t1, g.from_camera, g.resolved) == (
        "outage",
        120,
        150,
        "backyard",
        False,
    )


def test_events_for_unknown_tracks_still_form_visits(sample_config: Config) -> None:
    events = [ev("e1", "tx", "front", "enter", 100), ev("e2", "tx", "front", "exit", 110)]
    out = assemble_visits(events, [], {}, [], sample_config)
    assert len(out.visits) == 1
    assert out.visits[0].event_ids == ["e1", "e2"]


def test_assembly_is_deterministic(sample_config: Config) -> None:
    events, tracks, notes = scenario_c()
    a = assemble_visits(events, tracks, notes, [], sample_config).model_dump_json()
    b = assemble_visits(
        list(reversed(events)), list(reversed(tracks)), notes, [], sample_config
    ).model_dump_json()
    assert a == b


# ---------------------------------------------------------------------------
# Properties (hypothesis)
# ---------------------------------------------------------------------------

CAMS = ["front", "side_left", "side_right", "backyard"]
COLOURS = ["navy", "red", "green", "unknown"]


@st.composite
def random_scene(draw: st.DrawFn) -> tuple[list[Track], dict[str, Appearance], list[Event]]:
    n = draw(st.integers(min_value=1, max_value=7))
    tracks, notes, events = [], {}, []
    for i in range(n):
        cam = draw(st.sampled_from(CAMS))
        t0 = draw(st.floats(min_value=0, max_value=600, allow_nan=False)).__round__(1)
        dur = draw(st.floats(min_value=1, max_value=40, allow_nan=False)).__round__(1)
        tid = f"t{i}"
        tracks.append(trk(tid, cam, t0, t0 + dur))
        notes[tid] = note(tid, draw(st.sampled_from(COLOURS)), "unknown")
        if cam == "side_left" and draw(st.booleans()):
            events.append(ev(f"x{i}", tid, cam, "exit", t0 + dur - 0.5, "to_shed_back"))
    return tracks, notes, events


def _windows(cfg: Config, a: str, b: str) -> list[tuple[float, float, bool]]:
    return [
        (r.min_s, r.max_s, r.blind) for r in routes(cfg) if (r.from_camera, r.to_camera) == (a, b)
    ]


@PROPS
@given(scene=random_scene())
def test_prop_links_only_inside_transit_windows(sample_config: Config, scene) -> None:
    tracks, notes, events = scene
    out = assemble_visits(events, tracks, notes, [], sample_config)
    by_id = {t.id: t for t in tracks}
    for lk in out.links:
        a, b = by_id[lk.from_track], by_id[lk.to_track]
        gap = b.t_first - a.t_last
        assert gap >= 0
        wins = _windows(sample_config, a.camera_id, b.camera_id)
        assert any(lo <= gap <= hi for lo, hi, _ in wins), (lk, wins)
        assert appearance_agrees(notes[a.id], notes[b.id])


@PROPS
@given(scene=random_scene())
def test_prop_every_out_of_view_interval_is_a_gap(sample_config: Config, scene) -> None:
    tracks, notes, events = scene
    out = assemble_visits(events, tracks, notes, [], sample_config)
    spans = {(g.t0, g.t1, g.kind) for g in out.gaps}
    by_id = {t.id: t for t in tracks}
    for lk in out.links:
        if lk.blind:
            assert (by_id[lk.from_track].t_last, by_id[lk.to_track].t_first, "blind_spot") in spans
    # every track that left through the blind exit and was not re-linked has an open gap
    linked_from = {lk.from_track for lk in out.links}
    for e in events:
        if e.track_id not in linked_from:
            t = by_id[e.track_id]
            assert any(g.t0 == t.t_last and not g.resolved for g in out.gaps)
    # gaps always belong to a visit and are well formed
    vids = {v.id for v in out.visits}
    for g in out.gaps:
        assert g.visit_id in vids
        assert g.t1 >= g.t0


@PROPS
@given(
    gap=st.floats(min_value=0.0, max_value=400.0, allow_nan=False),
)
def test_prop_blind_return_links_iff_within_window(sample_config: Config, gap: float) -> None:
    tracks = [trk("t1", "side_left", 0, 50), trk("t2", "side_left", 50 + gap, 60 + gap)]
    events = [ev("e1", "t1", "side_left", "exit", 49.5, "to_shed_back")]
    out = assemble_visits(events, tracks, {}, [], sample_config)
    linked = len(out.links) == 1
    via = candidate_routes(sample_config, "side_left", "to_shed_back")
    assert linked == any(r.fits(gap) for r in via)
    # whatever happens, the subject going behind the shed is recorded as a gap
    blind = [g for g in out.gaps if g.kind == "blind_spot" and g.t0 == 50]
    assert len(blind) == 1
    assert blind[0].resolved == linked
    if linked:
        assert blind[0].t1 == 50 + gap
        assert blind[0].region_id == "shed_back"


@PROPS
@given(
    k=st.integers(min_value=2, max_value=3),
    gaps=st.lists(st.floats(min_value=2.0, max_value=20.0), min_size=3, max_size=3),
    cams=st.permutations(["side_left", "side_right", "front"]),
)
def test_prop_ambiguity_never_links(sample_config: Config, k: int, gaps, cams) -> None:
    # origin on front; k simultaneous candidates on cameras reachable from front
    reach = [c for c in cams if c != "front"] + ["side_left"]
    tracks = [trk("o", "front", 0, 10)]
    for i in range(k):
        t0 = 10 + gaps[i]
        tracks.append(trk(f"c{i}", reach[i % len(reach)], t0, 60))
    out = assemble_visits([], tracks, {}, [], sample_config)
    assert not any(lk.from_track == "o" for lk in out.links)
    assert any(g.kind == "ambiguous_link" and g.t0 == 10 for g in out.gaps)
