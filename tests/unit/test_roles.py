"""Spatial origin roles (FR-044, FR-010 group rule, FR-029 inputs): truth tables and scenarios.

Roles come from evidence only: where a subject chain's first track was born (origin zone kind),
an explicit owner check-in, an owner-set Expected Window, and how the chain was linked. The
expected values below are written out by hand from the FR-044 steps, not computed from the code.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vigil.models import Appearance, CheckIn, Config, Event, ExpectedWindow, Track
from vigil.reasoning.visits import assemble_visits, assign_roles

PST = timezone(timedelta(hours=-8))
START = datetime(2026, 11, 2, 17, 0, tzinfo=PST)  # session t=0


def wall(t: float) -> datetime:
    return START + timedelta(seconds=t)


def _rect(x0: int, y0: int, x1: int, y1: int) -> list[list[int]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


@pytest.fixture
def cfg() -> Config:
    """Spec 9.4 zones with kinds, plus a garage door (interior_yard, never egress)."""
    return Config.model_validate(
        {
            "cameras": [
                {
                    "id": "front",
                    "name": "Front entrance",
                    "zones": {
                        "front_door_egress": {
                            "kind": "egress",
                            "polygon": _rect(560, 300, 700, 560),
                        },
                        "porch": {"kind": "interior_yard", "polygon": _rect(420, 380, 860, 720)},
                        "driveway_entry": {"kind": "perimeter", "polygon": _rect(0, 300, 180, 720)},
                        "garage_door": {
                            "kind": "interior_yard",
                            "polygon": _rect(900, 200, 1100, 500),
                        },
                    },
                },
                {
                    "id": "side_left",
                    "name": "Left side",
                    "zones": {
                        "side_alley": {"kind": "perimeter", "polygon": _rect(200, 300, 420, 720)},
                        "side_door_egress": {
                            "kind": "egress",
                            "polygon": _rect(500, 300, 600, 500),
                        },
                        "side_yard": _rect(420, 300, 1100, 720),
                    },
                    "exits": {"to_shed_back": _rect(1100, 380, 1280, 720)},
                },
                {"id": "side_right", "name": "Right side"},
                {
                    "id": "backyard",
                    "name": "Backyard",
                    "zones": {
                        "back_door_egress": {"kind": "egress", "polygon": _rect(600, 260, 760, 520)}
                    },
                },
            ],
            "blind_regions": [
                {
                    "id": "shed_back",
                    "name": "behind the shed",
                    "polygon_m": [[4.1, 9.0], [7.3, 9.0], [7.3, 11.2], [4.1, 11.2]],
                }
            ],
            "topology": [
                {"from": "side_left", "exit": "to_shed_back", "to": "shed_back", "blind": True},
                {"from": "shed_back", "to": "side_left", "min_s": 5, "max_s": 180, "blind": True},
                {"from": "front", "to": "side_left", "min_s": 2, "max_s": 20},
                {"from": "side_left", "to": "front", "min_s": 2, "max_s": 20},
                {"from": "side_left", "to": "backyard", "min_s": 3, "max_s": 30},
                {"from": "front", "to": "side_right", "min_s": 2, "max_s": 20},
            ],
        }
    )


def trk(tid: str, cam: str, t0: float, t1: float, origin: str | None = None) -> Track:
    return Track(id=tid, camera_id=cam, cls="person", t_first=t0, t_last=t1, origin_zone=origin)


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


def note(tag: str, upper: str = "unknown", lower: str = "unknown", carrying=()) -> Appearance:
    return Appearance.model_validate(
        {
            "tag": tag,
            "class": "person",
            "upper_color": upper,
            "lower_color": lower,
            "carrying": list(carrying),
        }
    )


def roles(out) -> dict[str, tuple[str, str]]:
    """track id -> (actor_role, role_basis) of the subject holding it."""
    return {tid: (s.actor_role, s.role_basis) for s in out.subjects for tid in s.track_ids}


def window(wid="w1", t0=0.0, t1=3600.0, cameras=(), zones=(), state="active") -> ExpectedWindow:
    return ExpectedWindow(
        id=wid,
        start=wall(t0),
        end=wall(t1),
        cameras=list(cameras),
        zones=list(zones),
        state=state,
    )


def checkin(cid="c1", t=0.0, revoked=False) -> CheckIn:
    return CheckIn(id=cid, start=wall(t), expires=wall(t + 1800), revoked=revoked)


def run(cfg, tracks, events=(), notes=None, windows=(), checkins=()):
    return assemble_visits(
        list(events),
        tracks,
        notes or {},
        [],
        cfg,
        windows=windows,
        checkins=checkins,
        session_start=START,
    )


# ---------------------------------------------------------------------------
# Demo scenarios (section 4)
# ---------------------------------------------------------------------------


def test_scenario_a_egress_is_household(cfg: Config) -> None:
    tracks = [trk("a1", "front", 100, 130, "front_door_egress")]
    events = [ev("e1", "a1", "front", "enter", 100), ev("e2", "a1", "front", "exit", 129)]
    out = run(cfg, tracks, events)
    (s,) = out.subjects
    assert (s.actor_role, s.role_basis) == ("household_insider", "egress:front_door_egress")
    assert s.track_ids == ["a1"]
    assert s.visit_id == out.visits[0].id
    assert {(e.subject_id, e.actor_role) for e in out.events} == {(s.id, "household_insider")}


def test_scenario_a_prime_household_carries_to_side_gate(cfg: Config) -> None:
    # front door -> side_left within 2-20 s (non-blind, unambiguous): the role carries
    tracks = [
        trk("a1", "front", 100, 110, "front_door_egress"),
        trk("a2", "side_left", 115, 140, None),
    ]
    events = [ev("e1", "a1", "front", "enter", 100), ev("e2", "a2", "side_left", "touch", 120,
                                                        "po_side_gate")]  # fmt: skip
    out = run(cfg, tracks, events)
    (s,) = out.subjects
    assert s.track_ids == ["a1", "a2"]
    assert (s.actor_role, s.role_basis) == ("household_insider", "egress:front_door_egress")
    touch = next(e for e in out.events if e.type == "touch")
    assert touch.actor_role == "household_insider"
    assert touch.subject_id == s.id


def test_scenario_c_side_alley_is_external_and_carries_across_the_shed(cfg: Config) -> None:
    tracks = [
        trk("c1", "side_left", 80020, 80070, "side_alley"),
        trk("c2", "side_left", 80111, 80150, None),
    ]
    events = [
        ev("e16", "c1", "side_left", "enter", 80020),
        ev("e17", "c1", "side_left", "touch", 80040, "po_side_gate"),
        ev("e18", "c1", "side_left", "exit", 80069, "to_shed_back"),
        ev("e19", "c2", "side_left", "enter", 80111),
    ]
    # night, IR: colours unknown; external_visitor carries on any unambiguous re-link
    notes = {"c1": note("T1"), "c2": note("T2")}
    out = run(cfg, tracks, events, notes)
    (s,) = out.subjects
    assert s.track_ids == ["c1", "c2"]
    assert (s.actor_role, s.role_basis) == ("external_visitor", "perimeter:side_alley")
    assert all(e.actor_role == "external_visitor" for e in out.events)
    assert out.gaps[0].kind == "blind_spot"


# ---------------------------------------------------------------------------
# Head of chain: origin x check-in x window (steps 1 to 5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("front_door_egress", ("household_insider", "egress:front_door_egress")),
        ("driveway_entry", ("external_visitor", "perimeter:driveway_entry")),
        ("porch", ("unknown", "origin_null:h")),
        ("garage_door", ("unknown", "origin_null:h")),  # a garage door is never egress
        (None, ("unknown", "origin_null:h")),
    ],
)
def test_origin_kinds(cfg: Config, origin: str | None, expected) -> None:
    out = run(cfg, [trk("h", "front", 100, 130, origin)])
    assert roles(out)["h"] == expected


# (origin kind, check-in binds?, active window in scope?) -> (role, basis), by hand.
HH, EXP, EXT, UNK = "household_insider", "expected_visitor", "external_visitor", "unknown"
HEAD: dict[tuple[str | None, bool, bool], tuple[str, str]] = {
    ("side_door_egress", False, False): (HH, "egress:side_door_egress"),
    ("side_door_egress", False, True): (HH, "egress:side_door_egress"),
    ("side_door_egress", True, False): (HH, "egress:side_door_egress"),  # egress first
    ("side_door_egress", True, True): (HH, "egress:side_door_egress"),
    ("side_alley", False, False): (EXT, "perimeter:side_alley"),
    ("side_alley", False, True): (EXP, "window:w1"),
    ("side_alley", True, False): (HH, "checkin:c1"),
    ("side_alley", True, True): (HH, "checkin:c1"),  # check-in (2) before window (3)
    ("side_yard", False, False): (UNK, "origin_null:h"),
    ("side_yard", False, True): (UNK, "origin_null:h"),  # windows need a perimeter origin
    ("side_yard", True, False): (HH, "checkin:c1"),
    ("side_yard", True, True): (HH, "checkin:c1"),
    (None, False, False): (UNK, "origin_null:h"),
    (None, False, True): (UNK, "origin_null:h"),  # a null origin is never expected
    (None, True, False): (HH, "checkin:c1"),
    (None, True, True): (HH, "checkin:c1"),
}

# role of the chain head -> role and basis of the successor track after each link outcome
LINKS = ["none", "direct", "blind_match", "blind_transit_only", "ambiguous"]


def _after_link(head: tuple[str, str], link: str) -> tuple[str, str]:
    role, _basis = head
    if link in ("none", "direct", "blind_match"):
        return head
    if link == "blind_transit_only":
        if role in (HH, EXP):
            return (UNK, "gap_unresolved:g1")
        return head  # external carries on any unambiguous re-link; unknown stays unknown
    return (UNK, "ambiguous_link:s1")  # the successor's first track followed an ambiguous link


def _truth_scene(origin, link):
    """Head h on side_left (100-230 s); the check-in is tapped at 95 s (interval 95-215 s)."""
    tracks = [trk("h", "side_left", 100, 230, origin)]
    events = [ev("eh", "h", "side_left", "enter", 100)]
    notes = {"h": note("H", "navy", "unknown")}
    if link == "direct":
        tracks.append(trk("s", "front", 235, 260))
    elif link in ("blind_match", "blind_transit_only"):
        events.append(ev("ex", "h", "side_left", "exit", 229, "to_shed_back"))
        tracks.append(trk("s", "side_left", 271, 300))
        notes["s"] = note("S", "navy" if link == "blind_match" else "unknown", "unknown")
    elif link == "ambiguous":
        tracks += [trk("s1", "front", 235, 260), trk("s2", "backyard", 236, 260)]
    return tracks, events, notes


@pytest.mark.parametrize("link", LINKS)
@pytest.mark.parametrize(("origin", "ci", "win"), list(HEAD))
def test_role_truth_table(cfg: Config, origin, ci: bool, win: bool, link: str) -> None:
    tracks, events, notes = _truth_scene(origin, link)
    out = run(
        cfg,
        tracks,
        events,
        notes,
        windows=[window()] if win else [],
        checkins=[checkin(t=95.0)] if ci else [],
    )
    got = roles(out)
    head = HEAD[(origin, ci, win)]
    assert got["h"] == head
    succ = {"none": None, "ambiguous": "s1"}.get(link, "s")
    if succ is not None:
        assert got[succ] == _after_link(head, link)
    for e in out.events:
        assert e.actor_role == got[e.track_id][0]


def test_without_windows_or_checkins_fr044_still_passes(cfg: Config) -> None:
    tracks = [trk("h", "side_left", 100, 130, "side_alley"), trk("n", "front", 200, 230)]
    out = assemble_visits([], tracks, {}, [], cfg)  # no FR-029 inputs, no session start
    assert roles(out) == {
        "h": (EXT, "perimeter:side_alley"),
        "n": (UNK, "origin_null:n"),
    }


# ---------------------------------------------------------------------------
# Expected windows (FR-029 inputs to step 3)
# ---------------------------------------------------------------------------


def test_window_scope_and_timing(cfg: Config) -> None:
    def role_for(w, origin="driveway_entry", cam="front", t0=100.0):
        return roles(run(cfg, [trk("h", cam, t0, t0 + 20, origin)], windows=[w]))["h"]

    assert role_for(window(cameras=["front"])) == (EXP, "window:w1")
    assert role_for(window(zones=["driveway_entry"])) == (EXP, "window:w1")
    assert role_for(window()) == (EXP, "window:w1")  # no scope: every perimeter zone
    # a camera outside the scope
    assert role_for(window(cameras=["front"]), "side_alley", "side_left") == (
        EXT,
        "perimeter:side_alley",
    )
    # 1 s after the window ends; and before it starts
    assert role_for(window(t0=0, t1=99)) == (EXT, "perimeter:driveway_entry")
    assert role_for(window(t0=101, t1=500)) == (EXT, "perimeter:driveway_entry")
    assert role_for(window(state="cancelled")) == (EXT, "perimeter:driveway_entry")
    assert role_for(window(), origin=None) == (UNK, "origin_null:h")


def test_window_is_never_retroactive(cfg: Config) -> None:
    # The owner sets the window at 12:00:59 with a start of 12:00:00; a perimeter track at
    # 12:00:30 was seen before the window existed, so it stays an external visitor.
    noon = START.replace(hour=12)
    w = ExpectedWindow(
        id="w1",
        start=noon,
        end=noon + timedelta(hours=1),
        created_at=noon + timedelta(seconds=59),
        state="active",
    )
    start = noon - timedelta(hours=1)  # session t=0 at 11:00
    t = (noon - start).total_seconds() + 30
    out = assemble_visits(
        [], [trk("h", "front", t, t + 20, "driveway_entry")], {}, [], cfg,
        windows=[w], session_start=start,
    )  # fmt: skip
    assert roles(out)["h"] == (EXT, "perimeter:driveway_entry")
    # a track after created_at is covered
    t2 = (noon - start).total_seconds() + 60
    out = assemble_visits(
        [], [trk("h", "front", t2, t2 + 20, "driveway_entry")], {}, [], cfg,
        windows=[w], session_start=start,
    )  # fmt: skip
    assert roles(out)["h"] == (EXP, "window:w1")
    # created_at before start: start still rules
    early = w.model_copy(update={"created_at": noon - timedelta(hours=2)})
    out = assemble_visits(
        [], [trk("h", "front", t, t + 20, "driveway_entry")], {}, [], cfg,
        windows=[early], session_start=start,
    )  # fmt: skip
    assert roles(out)["h"] == (EXP, "window:w1")


def test_windows_need_a_session_start(cfg: Config) -> None:
    with pytest.raises(ValueError, match="session_start"):
        assemble_visits([], [trk("h", "front", 1, 2)], {}, [], cfg, windows=[window()])


# ---------------------------------------------------------------------------
# Check-in abuse cases (step 2)
# ---------------------------------------------------------------------------


def test_checkin_binds_the_one_chain_and_records_it(cfg: Config) -> None:
    out = run(cfg, [trk("h", "side_left", 150, 200, "side_alley")], checkins=[checkin(t=100)])
    (s,) = out.subjects
    assert (s.actor_role, s.role_basis) == (HH, "checkin:c1")
    assert [(c.id, c.bound_subject) for c in out.checkins] == [("c1", s.id)]


def test_two_chains_in_one_interval_bind_neither(cfg: Config) -> None:
    tracks = [trk("h1", "side_left", 150, 200, "side_alley"), trk("h2", "front", 190, 240)]
    out = run(cfg, tracks, checkins=[checkin(t=100)])
    assert roles(out) == {"h1": (EXT, "perimeter:side_alley"), "h2": (UNK, "origin_null:h2")}
    assert out.checkins[0].bound_subject is None


@pytest.mark.parametrize("t0", [99.0, 221.0])
def test_checkin_is_never_retroactive_and_closes_after_120s(cfg: Config, t0: float) -> None:
    out = run(cfg, [trk("h", "side_left", t0, t0 + 30, None)], checkins=[checkin(t=100)])
    assert roles(out)["h"] == (UNK, "origin_null:h")
    assert out.checkins[0].bound_subject is None


def test_checkin_interval_edges_are_inclusive(cfg: Config) -> None:
    for t0 in (100.0, 220.0):
        out = run(cfg, [trk("h", "side_left", t0, t0 + 30, None)], checkins=[checkin(t=100)])
        assert roles(out)["h"] == (HH, "checkin:c1")


def test_egress_chain_is_not_a_checkin_candidate(cfg: Config) -> None:
    tracks = [trk("e", "front", 110, 300, "front_door_egress"), trk("h", "side_left", 150, 200)]
    out = run(cfg, tracks, checkins=[checkin(t=100)])
    assert roles(out)["e"] == (HH, "egress:front_door_egress")
    assert roles(out)["h"] == (HH, "checkin:c1")  # household in view does not block


def test_non_household_in_view_blocks_the_checkin(cfg: Config) -> None:
    # an external visitor on the front camera when the candidate appears on side_left
    tracks = [trk("x", "front", 50, 400, "driveway_entry"), trk("h", "side_left", 150, 200)]
    out = run(cfg, tracks, checkins=[checkin(t=100)])
    assert roles(out)["h"] == (UNK, "origin_null:h")
    assert out.checkins[0].bound_subject is None


def test_unknown_in_view_blocks_the_checkin(cfg: Config) -> None:
    tracks = [trk("x", "backyard", 50, 400, None), trk("h", "side_left", 150, 200)]
    out = run(cfg, tracks, checkins=[checkin(t=100)])
    assert roles(out)["h"] == (UNK, "origin_null:h")


def test_external_car_in_view_blocks_the_checkin(cfg: Config) -> None:
    # Cars are subjects too: an external car on the drive when the person appears means the
    # tap cannot tell who tapped. ("driveway" is not a configured zone: interior_yard.)
    car = Track(
        id="front-car-1",
        camera_id="front",
        cls="car",
        t_first=10,
        t_last=200,
        origin_zone="driveway_entry",
    )
    person = trk("front-person-1", "front", 30, 90, "driveway")
    out = run(cfg, [car, person], checkins=[checkin(t=0)])
    got = roles(out)
    assert got["front-car-1"] == (EXT, "perimeter:driveway_entry")
    assert got["front-person-1"] == (UNK, "origin_null:front-person-1")
    assert out.checkins[0].bound_subject is None


def test_parked_car_in_view_since_session_start_does_not_block_the_checkin(cfg: Config) -> None:
    # A car in view from the first frame (origin null: parked, never seen arriving) is scenery,
    # not someone who could have tapped; it must not stop every check-in while it stays parked.
    parked = Track(id="front-car-1", camera_id="front", cls="car", t_first=0, t_last=3000)
    person = trk("front-person-1", "front", 30, 90, "driveway")
    out = run(cfg, [parked, person], checkins=[checkin(t=0)])
    assert roles(out)["front-person-1"] == (HH, "checkin:c1")


def test_unknown_person_in_view_still_blocks_the_checkin(cfg: Config) -> None:
    other = trk("front-person-9", "front", 0, 3000, None)
    person = trk("front-person-1", "front", 30, 90, "driveway")
    out = run(cfg, [other, person], checkins=[checkin(t=0)])
    assert roles(out)["front-person-1"] == (UNK, "origin_null:front-person-1")


def test_checkin_is_single_use(cfg: Config) -> None:
    tracks = [trk("h1", "side_left", 150, 160, None), trk("h2", "front", 400, 420, None)]
    out = run(cfg, tracks, checkins=[checkin(t=100)])
    assert roles(out)["h1"] == (HH, "checkin:c1")
    assert roles(out)["h2"] == (UNK, "origin_null:h2")


def test_revoked_or_used_checkins_bind_nothing(cfg: Config) -> None:
    out = run(cfg, [trk("h", "side_left", 150, 200)], checkins=[checkin(t=100, revoked=True)])
    assert roles(out)["h"] == (UNK, "origin_null:h")
    used = checkin(t=100).model_copy(update={"bound_subject": "s9"})
    out = run(cfg, [trk("h", "side_left", 150, 200)], checkins=[used])
    assert roles(out)["h"] == (UNK, "origin_null:h")


def test_two_checkins_two_chains(cfg: Config) -> None:
    tracks = [trk("h1", "side_left", 110, 130), trk("h2", "front", 400, 420)]
    out = run(cfg, tracks, checkins=[checkin("c1", t=100), checkin("c2", t=390)])
    assert roles(out) == {"h1": (HH, "checkin:c1"), "h2": (HH, "checkin:c2")}


def test_checkins_need_a_session_start(cfg: Config) -> None:
    with pytest.raises(ValueError, match="session_start"):
        assemble_visits([], [trk("h", "front", 1, 2)], {}, [], cfg, checkins=[checkin()])


# ---------------------------------------------------------------------------
# Carrying roles across links and blind spots
# ---------------------------------------------------------------------------


def _shed(origin: str, n1: Appearance, n2: Appearance):
    tracks = [trk("h", "side_left", 0, 50, origin), trk("x", "side_left", 91, 120)]
    events = [
        ev("e1", "h", "side_left", "touch", 10, "po_side_gate"),
        ev("e2", "h", "side_left", "exit", 49, "to_shed_back"),
        ev("e3", "x", "side_left", "touch", 100, "po_side_gate"),
    ]
    return tracks, events, {"h": n1, "x": n2}


def test_household_into_shed_unknown_person_out_is_unknown(cfg: Config) -> None:
    """Spec FR-044: a never-seen person with unknown colours emerges inside 5-180 s."""
    tracks, events, notes = _shed("side_door_egress", note("H", "navy"), note("X"))
    out = run(cfg, tracks, events, notes)
    (gap,) = out.gaps
    assert roles(out) == {
        "h": (HH, "egress:side_door_egress"),  # what was seen before the gap stays backed
        "x": (UNK, f"gap_unresolved:{gap.id}"),
    }
    by_id = {e.id: e for e in out.events}
    assert by_id["e1"].actor_role == HH
    assert by_id["e3"].actor_role == UNK
    assert by_id["e1"].subject_id != by_id["e3"].subject_id
    assert len(out.visits) == 1  # still one visit; only the role chain breaks


@pytest.mark.parametrize(
    ("n1", "n2", "carries"),
    [
        (note("H", "navy"), note("X", "navy"), True),  # upper colour agrees
        (note("H", "unknown", "grey"), note("X", "red", "grey"), True),  # lower colour
        (note("H", carrying=["backpack"]), note("X", carrying=["backpack"]), True),
        (note("H", "navy"), note("X", "blue"), False),  # near colours are not agreement
        (note("H", "unknown"), note("X", "unknown"), False),  # transit time alone (IR)
        (None, None, False),
    ],
)
def test_household_carries_only_on_a_known_matching_attribute(cfg, n1, n2, carries) -> None:
    notes = {k: v for k, v in (("h", n1), ("x", n2)) if v is not None}
    tracks, events, _ = _shed("side_door_egress", note("H"), note("X"))
    out = run(cfg, tracks, events, notes)
    got = roles(out)["x"]
    assert got[0] == (HH if carries else UNK)


def test_expected_visitor_across_the_shed(cfg: Config) -> None:
    tracks, events, notes = _shed("side_alley", note("H", "red"), note("X", "red"))
    out = run(cfg, tracks, events, notes, windows=[window()])
    assert roles(out)["x"] == (EXP, "window:w1")
    tracks, events, notes = _shed("side_alley", note("H"), note("X"))
    out = run(cfg, tracks, events, notes, windows=[window()])
    assert roles(out)["x"][0] == UNK
    assert roles(out)["x"][1].startswith("gap_unresolved:")


def test_ambiguous_relink_is_unknown(cfg: Config) -> None:
    # household behind the shed; two people come out: no link, both unknown
    tracks = [
        trk("h", "side_left", 0, 50, "side_door_egress"),
        trk("x1", "side_left", 91, 120),
        trk("x2", "side_left", 92, 120),
    ]
    events = [ev("e1", "h", "side_left", "exit", 49, "to_shed_back")]
    notes = {"h": note("H", "navy"), "x1": note("X1", "navy"), "x2": note("X2", "navy")}
    out = run(cfg, tracks, events, notes)
    assert out.links == []
    got = roles(out)
    assert got["x1"] == (UNK, "ambiguous_link:x1")
    assert got["x2"] == (UNK, "ambiguous_link:x2")


# ---------------------------------------------------------------------------
# Group rule (FR-010)
# ---------------------------------------------------------------------------


def _group(o1: str | None, o2: str | None, n_out: int = 2):
    tracks = [trk("f1", "front", 0, 10, o1), trk("f2", "front", 0, 10.5, o2)]
    tracks += [trk(f"s{i + 1}", "side_left", 14 + i, 40) for i in range(n_out)]
    return tracks


def test_two_household_members_leave_together(cfg: Config) -> None:
    out = run(cfg, _group("front_door_egress", "front_door_egress"))
    assert out.links == []  # the tracks stay unlinked
    got = roles(out)
    assert got["s1"] == (HH, "group:household_insider")
    assert got["s2"] == (HH, "group:household_insider")


def test_group_rule_needs_the_same_role(cfg: Config) -> None:
    got = roles(run(cfg, _group("front_door_egress", "driveway_entry")))
    assert got["s1"] == (UNK, "ambiguous_link:s1")
    assert got["s2"] == (UNK, "ambiguous_link:s2")


def test_group_rule_for_external_visitors(cfg: Config) -> None:
    got = roles(run(cfg, _group("driveway_entry", "driveway_entry")))
    assert got["s1"] == (EXT, "group:external_visitor")


@pytest.mark.parametrize("n_out", [1, 3])
def test_group_rule_needs_the_same_number_of_tracks(cfg: Config, n_out: int) -> None:
    got = roles(run(cfg, _group("front_door_egress", "front_door_egress", n_out)))
    for i in range(n_out):
        assert got[f"s{i + 1}"][0] == UNK


def test_group_rule_never_applies_across_a_blind_spot(cfg: Config) -> None:
    tracks = [
        trk("h1", "side_left", 0, 50, "side_door_egress"),
        trk("h2", "side_left", 0, 50.5, "side_door_egress"),
        trk("x1", "side_left", 91, 120),
        trk("x2", "side_left", 92, 120),
    ]
    events = [
        ev("e1", "h1", "side_left", "exit", 49, "to_shed_back"),
        ev("e2", "h2", "side_left", "exit", 49.5, "to_shed_back"),
    ]
    got = roles(run(cfg, tracks, events))
    assert got["x1"] == (UNK, "ambiguous_link:x1")
    assert got["x2"] == (UNK, "ambiguous_link:x2")


# ---------------------------------------------------------------------------
# Events, subjects and the standalone entry point
# ---------------------------------------------------------------------------


def test_object_event_takes_the_nearby_subjects_role(cfg: Config) -> None:
    tracks = [
        trk("a1", "front", 100, 130, "front_door_egress"),
        Track(id="p1", camera_id="front", cls="package", t_first=0, t_last=120),
    ]
    events = [ev("e1", "a1", "front", "enter", 100), ev("e2", "p1", "front", "removed", 118, "w2")]
    out = run(cfg, tracks, events)
    (s,) = out.subjects
    assert all((e.subject_id, e.actor_role) == (s.id, HH) for e in out.events)


def test_assign_roles_matches_assembly(cfg: Config) -> None:
    tracks = [trk("c1", "side_left", 0, 10, "side_alley"), trk("c2", "front", 15, 30)]
    out = run(cfg, tracks)
    subjects = assign_roles(out, tracks, cfg)
    assert subjects == out.subjects
    assert subjects[0].id == "s1"


def test_roles_are_deterministic(cfg: Config) -> None:
    tracks, events, notes = _truth_scene("side_alley", "blind_transit_only")
    a = run(cfg, tracks, events, notes).model_dump_json()
    b = run(cfg, list(reversed(tracks)), list(reversed(events)), notes).model_dump_json()
    assert a == b


def test_subject_schema_has_no_identity_fields() -> None:
    from vigil.models import Subject

    banned = {"name", "face", "age", "gender", "skin", "ethnicity", "height", "gait", "voice"}
    assert not banned & set(Subject.model_fields)
