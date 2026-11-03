"""Event builder on synthetic tracks (FR-008): enter, exit, cross, touch, removed, dwell.

Geometry comes from the sample config (front: front_door_egress, porch, driveway and
driveway_entry zones; side_left: side_gate line, side_alley and side_yard zones; backyard:
back_door_egress) and the po_side_gate fixture (bbox 800..880 x 400..660). Origin tagging
(``origin_zone``) follows FR-008 as revised on Nov 2.
"""

from __future__ import annotations

import itertools
from typing import NamedTuple

import numpy as np
import pytest

from vigil.models import (
    Box,
    Config,
    Event,
    ProtectedObject,
    Track,
    TrackFrame,
    Watch,
    Window,
)
from vigil.perception.events import Observation, assign_origins, build_events, origin_zone
from vigil.perception.rle import encode_rle

FPS = 10.0


def _box_at(cx: float, foot_y: float, w: float = 40, h: float = 100) -> Box:
    return Box(x1=cx - w / 2, y1=foot_y - h, x2=cx + w / 2, y2=foot_y)


def path_track(
    tid: str,
    cam: str,
    waypoints: list[tuple[float, float, float]],
    *,
    cls: str = "person",
    w: float = 40,
    h: float = 100,
) -> Track:
    """Linear path through (t, cx, foot_y) waypoints, sampled at 10 fps."""
    frames: list[TrackFrame] = []
    for (ta, xa, ya), (tb, xb, yb) in itertools.pairwise(waypoints):
        n = round((tb - ta) * FPS)
        for i in range(n):
            a = i / n
            frames.append(
                TrackFrame(
                    t=round(ta + i / FPS, 6),
                    box=_box_at(xa + a * (xb - xa), ya + a * (yb - ya), w, h),
                )
            )
    tl, xl, yl = waypoints[-1]
    frames.append(TrackFrame(t=round(tl, 6), box=_box_at(xl, yl, w, h)))
    return Track(
        id=tid, camera_id=cam, cls=cls, t_first=frames[0].t, t_last=frames[-1].t, frames=frames
    )


def static_track(tid: str, cam: str, box: Box, t0: float, t1: float, cls: str) -> Track:
    n = round((t1 - t0) * FPS)
    frames = [TrackFrame(t=round(t0 + i / FPS, 6), box=box) for i in range(n + 1)]
    return Track(id=tid, camera_id=cam, cls=cls, t_first=t0, t_last=frames[-1].t, frames=frames)


def of_type(events: list[Event], kind: str) -> list[Event]:
    return [e for e in events if e.type == kind]


# ---------------------------------------------------------------------------
# enter / exit / dwell
# ---------------------------------------------------------------------------


def test_enter_and_exit_zone(sample_config: Config) -> None:
    # Front camera: from x=1000 (no zone) into the porch (420..860) and back out.
    tr = path_track(
        "front-person-1", "front", [(0, 1000, 600), (4, 600, 600), (10, 600, 600), (14, 1000, 600)]
    )
    events = build_events([tr], sample_config, [], [])
    porch = [e for e in events if e.target == "porch"]
    assert [e.type for e in porch] == ["enter", "exit"]
    enter, exit_ = porch
    # Foot x reaches 860 at t = 4 * 140/400 = 1.4 s and leaves at 10 + 4 * 260/400 = 12.6 s.
    assert enter.t0 == pytest.approx(1.4, abs=0.11)
    assert enter.t1 == enter.t0
    assert exit_.t0 == pytest.approx(12.6, abs=0.11)
    assert all(e.camera_id == "front" and e.track_id == tr.id for e in porch)
    assert of_type(events, "dwell") == []  # 10 s is below the default threshold


def test_enter_at_start_and_exit_at_end_inside_zone(sample_config: Config) -> None:
    tr = path_track("backyard-person-1", "backyard", [(100, 300, 600), (106, 900, 600)])
    events = build_events([tr], sample_config, [], [])
    assert [(e.type, e.target, e.t0) for e in events] == [
        ("enter", "backyard", 100.0),
        ("exit", "backyard", 106.0),
    ]


def test_zone_jitter_is_debounced(sample_config: Config) -> None:
    # Foot hovers on the porch edge (x = 860 +/- 3) every other frame: no flapping events.
    frames = [TrackFrame(t=i / FPS, box=_box_at(857 if i % 2 else 863, 600)) for i in range(0, 40)]
    frames += [TrackFrame(t=i / FPS, box=_box_at(700, 600)) for i in range(40, 60)]
    tr = Track(
        id="front-person-1", camera_id="front", cls="person", t_first=0.0, t_last=5.9, frames=frames
    )
    porch = [e for e in build_events([tr], sample_config, [], []) if e.target == "porch"]
    assert [e.type for e in porch] == ["enter", "exit"]
    assert porch[0].t0 == pytest.approx(3.9)  # frame 39 (x = 857) starts the stable run


def test_dwell(sample_config: Config) -> None:
    tr = path_track(
        "front-person-1", "front", [(0, 1000, 600), (2, 600, 600), (42, 600, 600), (44, 1000, 600)]
    )
    (dwell,) = of_type(build_events([tr], sample_config, [], []), "dwell")
    assert dwell.target == "porch"
    assert dwell.t1 - dwell.t0 >= 40.0
    assert of_type(build_events([tr], sample_config, [], [], dwell_s=60.0), "dwell") == []
    short = path_track("front-person-2", "front", [(0, 600, 600), (12, 600, 600)])
    assert len(of_type(build_events([short], sample_config, [], [], dwell_s=10.0), "dwell")) == 1


def test_car_enters_driveway_but_packages_do_not_move(sample_config: Config) -> None:
    car = path_track(
        "front-car-1", "front", [(0, 1000, 650), (5, 200, 650)], cls="car", w=200, h=120
    )
    pkg = static_track(
        "front-package-1", "front", Box(x1=600, y1=600, x2=640, y2=640), 0, 5, "package"
    )
    events = build_events([car, pkg], sample_config, [], [])
    assert ("enter", "driveway", "front-car-1") in {(e.type, e.target, e.track_id) for e in events}
    assert all(e.track_id != "front-package-1" for e in events)


# ---------------------------------------------------------------------------
# cross
# ---------------------------------------------------------------------------


def test_cross_side_gate_line(sample_config: Config) -> None:
    # side_gate runs (812, 410) -> (870, 655); at foot y = 600 it sits at x ~ 857.
    tr = path_track("side_left-person-1", "side_left", [(0, 600, 600), (8, 1000, 600)])
    (cross,) = of_type(build_events([tr], sample_config, [], []), "cross")
    assert cross.target == "side_gate"
    assert cross.camera_id == "side_left"
    t_cross = 8 * (857 - 600) / 400
    assert cross.t0 <= t_cross + 0.11
    assert cross.t1 >= t_cross - 0.11
    assert cross.t1 - cross.t0 <= 0.2


def test_cross_back_and_forth_counts_twice(sample_config: Config) -> None:
    tr = path_track(
        "side_left-person-1", "side_left", [(0, 700, 600), (4, 1000, 600), (8, 700, 600)]
    )
    assert len(of_type(build_events([tr], sample_config, [], []), "cross")) == 2


def test_cross_jitter_is_debounced(sample_config: Config) -> None:
    frames = [TrackFrame(t=i / FPS, box=_box_at(854 if i % 2 else 861, 600)) for i in range(50)]
    tr = Track(
        id="side_left-person-1",
        camera_id="side_left",
        cls="person",
        t_first=0.0,
        t_last=4.9,
        frames=frames,
    )
    assert of_type(build_events([tr], sample_config, [], []), "cross") == []


def test_cross_needs_the_finite_segment(sample_config: Config) -> None:
    # At foot y = 350 the walker passes above the gate segment's end (y 410): no crossing.
    tr = path_track("side_left-person-1", "side_left", [(0, 600, 350), (8, 1000, 350)])
    assert of_type(build_events([tr], sample_config, [], []), "cross") == []


# ---------------------------------------------------------------------------
# touch
# ---------------------------------------------------------------------------


def test_touch_protected_object(sample_config: Config, po_side_gate: ProtectedObject) -> None:
    # Walk to the gate, stand at it for 3 s, walk away left.
    tr = path_track(
        "side_left-person-1",
        "side_left",
        [(0, 400, 650), (4, 840, 650), (7, 840, 650), (11, 400, 650)],
    )
    touches = of_type(build_events([tr], sample_config, [po_side_gate], []), "touch")
    assert len(touches) == 1
    t = touches[0]
    assert t.target == "po_side_gate"
    assert t.track_id == tr.id
    assert t.t0 < 4.0 < 7.0 < t.t1
    assert t.clip_t0 == pytest.approx(max(0.0, t.t0 - 3.0))
    assert t.clip_t1 == pytest.approx(t.t1 + 3.0)


def test_no_touch_when_far_or_other_camera(
    sample_config: Config, po_side_gate: ProtectedObject
) -> None:
    far = path_track("side_left-person-1", "side_left", [(0, 300, 650), (5, 500, 650)])
    other = path_track("front-person-1", "front", [(0, 840, 650), (5, 840, 650)])
    events = build_events([far, other], sample_config, [po_side_gate], [])
    assert of_type(events, "touch") == []


def test_touch_uses_mask_when_present(sample_config: Config, po_side_gate: ProtectedObject) -> None:
    # The person's box overlaps the gate, but their mask sits in the box's far-left strip.
    box = Box(x1=700, y1=500, x2=820, y2=700)
    mask = np.zeros((720, 1280), dtype=bool)
    mask[500:700, 700:760] = True
    rle = encode_rle(mask)
    frames = [TrackFrame(t=i / FPS, box=box, mask_rle=rle) for i in range(30)]
    tr = Track(
        id="side_left-person-1",
        camera_id="side_left",
        cls="person",
        t_first=0,
        t_last=2.9,
        frames=frames,
    )
    assert of_type(build_events([tr], sample_config, [po_side_gate], []), "touch") == []
    boxed = tr.model_copy(
        update={"frames": [f.model_copy(update={"mask_rle": None}) for f in frames]}
    )
    assert len(of_type(build_events([boxed], sample_config, [po_side_gate], []), "touch")) == 1


# ---------------------------------------------------------------------------
# removed
# ---------------------------------------------------------------------------

PKG_BOX = Box(x1=600, y1=600, x2=660, y2=650)


def _watch(status: str = "watching") -> Watch:
    return Watch(id="w2", camera_id="front", phrase="package", origin="wonder", status=status)


def _scene_removed() -> tuple[Track, Track]:
    pkg = static_track("front-package-1", "front", PKG_BOX, 0, 20, "package")
    person = path_track(
        "front-person-1",
        "front",
        [(15, 1000, 660), (18, 630, 660), (21, 630, 660), (25, 1000, 660)],
    )
    return pkg, person


def test_removed_watched_object(sample_config: Config) -> None:
    pkg, person = _scene_removed()
    events = build_events([pkg, person], sample_config, [], [_watch()])
    (removed,) = of_type(events, "removed")
    assert removed.target == "w2"
    assert removed.track_id == "front-person-1"
    assert removed.t0 <= 20.0 <= removed.t1
    assert removed.camera_id == "front"


def test_not_removed_without_person_or_inactive_watch(sample_config: Config) -> None:
    pkg, person = _scene_removed()
    alone = build_events([pkg], sample_config, [], [_watch()])
    assert of_type(alone, "removed") == []
    far = path_track("front-person-1", "front", [(15, 1000, 660), (25, 1100, 660)])
    assert of_type(build_events([pkg, far], sample_config, [], [_watch()]), "removed") == []
    revoked = build_events([pkg, person], sample_config, [], [_watch("revoked")])
    assert of_type(revoked, "removed") == []


def test_not_removed_when_object_reappears(sample_config: Config) -> None:
    pkg, person = _scene_removed()
    again = static_track("front-package-2", "front", PKG_BOX, 23, 40, "package")
    events = build_events([pkg, person, again], sample_config, [], [_watch()])
    assert of_type(events, "removed") == []


# ---------------------------------------------------------------------------
# ids, ordering, clip ranges
# ---------------------------------------------------------------------------


def test_event_ids_deterministic_unique_and_sorted(
    sample_config: Config, po_side_gate: ProtectedObject
) -> None:
    a = path_track(
        "side_left-person-1",
        "side_left",
        [(0, 400, 650), (4, 840, 650), (7, 840, 650), (11, 1000, 650)],
    )
    pkg, person = _scene_removed()
    tracks = [a, pkg, person]
    e1 = build_events(tracks, sample_config, [po_side_gate], [_watch()])
    e2 = build_events(list(reversed(tracks)), sample_config, [po_side_gate], [_watch()])
    assert e1 == e2
    assert len({e.id for e in e1}) == len(e1)
    assert [e.t0 for e in e1] == sorted(e.t0 for e in e1)
    assert {"enter", "exit", "cross", "touch", "removed"} <= {e.type for e in e1}
    for e in e1:
        assert e.id.startswith("e")
        assert e.t0 <= e.t1
        assert e.clip_t0 == pytest.approx(max(0.0, e.t0 - 3.0))
        assert e.clip_t1 == pytest.approx(e.t1 + 3.0)
        assert e.visit_id is None


def test_clip_pad_is_parameterised(sample_config: Config) -> None:
    tr = path_track("backyard-person-1", "backyard", [(100, 300, 600), (106, 900, 600)])
    events = build_events([tr], sample_config, [], [], clip_pad_s=5.0)
    assert events[0].clip_t0 == pytest.approx(95.0)
    assert events[-1].clip_t1 == pytest.approx(111.0)


def test_unknown_camera_tracks_are_skipped(sample_config: Config) -> None:
    tr = path_track("garage-person-1", "garage", [(0, 300, 600), (5, 900, 600)])
    assert build_events([tr], sample_config, [], []) == []


# ---------------------------------------------------------------------------
# one touch / removed event per overlapping person track (FR-008, Nov 2)
# ---------------------------------------------------------------------------


def test_two_people_touching_gate_give_two_touch_events(
    sample_config: Config, po_side_gate: ProtectedObject
) -> None:
    a = path_track(
        "side_left-person-1",
        "side_left",
        [(0, 400, 650), (4, 830, 650), (7, 830, 650), (11, 400, 650)],
    )
    b = path_track(
        "side_left-person-2",
        "side_left",
        [(0, 1200, 650), (4, 850, 650), (7, 850, 650), (11, 1200, 650)],
    )
    touches = of_type(build_events([a, b], sample_config, [po_side_gate], []), "touch")
    assert len(touches) == 2
    assert {t.track_id for t in touches} == {a.id, b.id}
    assert {t.target for t in touches} == {"po_side_gate"}
    assert len({t.id for t in touches}) == 2
    assert all(t.actor_role is None and t.subject_id is None for t in touches)


def test_two_people_at_removal_give_two_removed_events(sample_config: Config) -> None:
    # Behaviour change (Nov 2 spec): removed used to name only the best-overlapping person.
    pkg, person = _scene_removed()
    other = path_track(
        "front-person-2",
        "front",
        [(16, 300, 660), (18, 640, 660), (21, 640, 660), (24, 300, 660)],
    )
    removed = of_type(build_events([pkg, person, other], sample_config, [], [_watch()]), "removed")
    assert sorted(e.track_id for e in removed) == ["front-person-1", "front-person-2"]
    assert {e.target for e in removed} == {"w2"}
    assert all(e.t0 <= 20.0 <= e.t1 for e in removed)


# ---------------------------------------------------------------------------
# origin tagging (FR-008 origin_zone, spec 9.4 zone kinds)
# ---------------------------------------------------------------------------

# Sample config, front camera: front_door_egress 560..700 x 300..560 (inside the porch),
# porch 420..860 x 380..720, driveway 0..400 x 300..720, driveway_entry 0..180 x 300..720.
DOOR = (630, 540)


def door_track(tid: str, t0: float, cam: str = "front") -> Track:
    """A person standing in front_door_egress for 1 s, then walking off to the right."""
    x, y = DOOR
    return path_track(tid, cam, [(t0, x, y), (t0 + 1, x, y), (t0 + 5, 1000, 650)])


def courier_track(tid: str, t_end: float, stop: tuple[float, float] = DOOR) -> Track:
    """A person walking up from the driveway entry and ending (track lost) at ``stop``."""
    return path_track(
        tid,
        "front",
        [(t_end - 10, 100, 650), (t_end - 5, stop[0], stop[1]), (t_end, stop[0], stop[1])],
    )


def frames_at(points: list[tuple[float, float]], t0: float = 0.0) -> list[TrackFrame]:
    return [
        TrackFrame(t=round(t0 + i / FPS, 6), box=_box_at(x, y)) for i, (x, y) in enumerate(points)
    ]


def track_of(tid: str, cam: str, frames: list[TrackFrame], cls: str = "person") -> Track:
    return Track(
        id=tid, camera_id=cam, cls=cls, t_first=frames[0].t, t_last=frames[-1].t, frames=frames
    )


def test_origin_front_door_egress(sample_config: Config) -> None:
    tr = door_track("front-person-1", 0.0)
    assert origin_zone(tr, sample_config) == "front_door_egress"
    build_events([tr], sample_config, [], [])
    assert tr.origin_zone == "front_door_egress"


def test_origin_mid_yard_is_null(sample_config: Config) -> None:
    tr = path_track("front-person-1", "front", [(0, 1000, 650), (5, 1100, 650)])
    assert origin_zone(tr, sample_config) is None
    build_events([tr], sample_config, [], [])
    assert tr.origin_zone is None


def test_origin_interior_yard_and_perimeter_zones(sample_config: Config) -> None:
    porch = path_track("front-person-1", "front", [(0, 800, 700), (1, 800, 700), (5, 1000, 700)])
    entry = path_track("front-person-2", "front", [(0, 100, 650), (1, 100, 650), (6, 600, 650)])
    alley = path_track(
        "side_left-person-1", "side_left", [(0, 300, 650), (1, 300, 650), (6, 800, 650)]
    )
    back = path_track(
        "backyard-person-1", "backyard", [(0, 680, 500), (1, 680, 500), (6, 300, 700)]
    )
    assert origin_zone(porch, sample_config) == "porch"
    # driveway_entry (perimeter) lies inside driveway (interior_yard): the perimeter wins.
    assert origin_zone(entry, sample_config) == "driveway_entry"
    assert origin_zone(alley, sample_config) == "side_alley"
    assert origin_zone(back, sample_config) == "back_door_egress"


def test_origin_needs_a_strict_majority_of_first_10_frames(sample_config: Config) -> None:
    out = (1000, 650)
    tie = frames_at([DOOR] * 5 + [out] * 5 + [out] * 20)
    assert origin_zone(track_of("front-person-1", "front", tie), sample_config) is None
    six = frames_at([DOOR] * 6 + [out] * 4 + [out] * 20)
    assert origin_zone(track_of("front-person-2", "front", six), sample_config) == (
        "front_door_egress"
    )
    # Only the first 1 s counts: later frames in the door do not change the origin.
    late = frames_at([out] * 10 + [DOOR] * 30)
    assert origin_zone(track_of("front-person-3", "front", late), sample_config) is None
    # A tie between two zones (porch 5, front_door_egress 5) is also null.
    porch_pt = (800, 700)
    split = frames_at([porch_pt] * 5 + [DOOR] * 5 + [out] * 20)
    assert origin_zone(track_of("front-person-4", "front", split), sample_config) is None


def test_origin_voided_when_track_reborn_at_door_after_courier(sample_config: Config) -> None:
    courier = courier_track("front-person-1", t_end=20.0)
    reborn = door_track("front-person-2", 25.0)
    build_events([courier, reborn], sample_config, [], [])
    assert courier.origin_zone == "driveway_entry"
    assert reborn.origin_zone is None
    assert origin_zone(reborn, sample_config, others=[courier]) is None
    # Without the courier the same track is an egress origin.
    assert origin_zone(door_track("front-person-2", 25.0), sample_config) == "front_door_egress"


def test_egress_voiding_lasts_ten_minutes(sample_config: Config) -> None:
    courier = courier_track("front-person-1", t_end=20.0)
    inside = door_track("front-person-2", 20.0 + 590.0)
    after = door_track("front-person-3", 20.0 + 610.0)
    assert origin_zone(inside, sample_config, others=[courier]) is None
    assert origin_zone(after, sample_config, others=[courier]) == "front_door_egress"


def test_egress_voiding_uses_door_dilated_by_half(sample_config: Config) -> None:
    # Door 560..700 x 300..560 scaled 1.5x about its centre: 525..735 x 235..625.
    near = courier_track("front-person-1", t_end=10.0, stop=(520, 600))  # box 500..540
    far = courier_track("front-person-3", t_end=10.0, stop=(480, 600))  # box 460..500
    reborn = door_track("front-person-2", 15.0)
    assert origin_zone(reborn, sample_config, others=[near]) is None
    assert origin_zone(reborn, sample_config, others=[far]) == "front_door_egress"


def test_egress_not_voided_by_household_car_or_other_camera(sample_config: Config) -> None:
    household = door_track("front-person-1", 0.0)  # itself born in the door, walks off
    lingering = path_track("front-person-3", "front", [(0, *DOOR), (1, *DOOR), (10, *DOOR)])
    car = courier_track("front-car-1", t_end=10.0).model_copy(update={"cls": "car"})
    elsewhere = courier_track("front-person-4", t_end=10.0).model_copy(
        update={"camera_id": "side_right", "id": "side_right-person-4"}
    )
    reborn = door_track("front-person-2", 15.0)
    others = [household, lingering, car, elsewhere]
    assert origin_zone(reborn, sample_config, others=others) == "front_door_egress"


def test_egress_voided_by_a_track_whose_own_origin_was_voided(sample_config: Config) -> None:
    # The courier leaves view 11 min before the third track; the track re-born 5 s after them
    # is voided and lingers at the door, so a third track born there later is voided too.
    courier = courier_track("front-person-1", t_end=20.0)
    reborn = path_track("front-person-2", "front", [(25, *DOOR), (26, *DOOR), (300, *DOOR)])
    third = door_track("front-person-3", 20.0 + 660.0)
    build_events([third, reborn, courier], sample_config, [], [])
    assert reborn.origin_zone is None
    assert third.origin_zone is None


def test_two_people_born_in_door_together_keep_egress(sample_config: Config) -> None:
    a = door_track("front-person-1", 0.0)
    b = path_track("front-person-2", "front", [(0, 600, 550), (1, 600, 550), (5, 1000, 650)])
    build_events([a, b], sample_config, [], [])
    assert (a.origin_zone, b.origin_zone) == ("front_door_egress", "front_door_egress")


class _Outage(NamedTuple):
    camera_id: str
    t0: float
    t1: float


def _win(wid: str, cam: str, t0: float, t1: float, status: str = "processed") -> Window:
    return Window(id=wid, camera_id=cam, t0=t0, t1=t1, status=status)


def test_origin_null_on_first_frame_after_skipped_window(sample_config: Config) -> None:
    windows = [_win("w0", "front", 0, 10, "idle"), _win("w1", "front", 10, 20)]
    obs = Observation.from_windows(windows)
    first = door_track("front-person-1", 10.0)
    build_events([first], sample_config, [], [], observation=obs)
    assert first.origin_zone is None
    later = door_track("front-person-2", 13.0)
    build_events([later], sample_config, [], [], observation=obs)
    assert later.origin_zone == "front_door_egress"
    # Seen together, the unobserved-origin track at the door also voids the later one:
    # it did not itself originate (as far as Vigil knows) in front_door_egress.
    build_events([first, later], sample_config, [], [], observation=obs)
    assert (first.origin_zone, later.origin_zone) == (None, None)


@pytest.mark.parametrize(
    ("windows", "outages", "t0", "expected"),
    [
        # fully observed for the 2 s before (contiguous windows; a 0.1 s seam is fine)
        ([("w0", 0, 9.9, "processed"), ("w1", 10, 20, "pending")], [], 11.0, "front_door_egress"),
        # unprocessed predecessor
        ([("w0", 0, 10, "failed"), ("w1", 10, 20, "processed")], [], 11.0, None),
        # no predecessor at all: the camera was not observed before 10 s
        ([("w1", 10, 20, "processed")], [], 11.0, None),
        # outage inside the 2 s look-back
        ([("w0", 0, 10, "processed"), ("w1", 10, 20, "processed")], [(11, 12)], 13.0, None),
        # outage ended more than 2 s before
        (
            [("w0", 0, 10, "processed"), ("w1", 10, 20, "processed")],
            [(11, 12)],
            14.5,
            "front_door_egress",
        ),
    ],
)
def test_origin_requires_two_seconds_of_observation(
    sample_config: Config,
    windows: list[tuple[str, float, float, str]],
    outages: list[tuple[float, float]],
    t0: float,
    expected: str | None,
) -> None:
    wins = [_win(w, "front", a, b, s) for w, a, b, s in windows]
    wins.append(_win("x0", "side_left", 0, 20, "idle"))  # another camera does not matter
    outs = [_Outage("front", a, b) for a, b in outages] + [_Outage("side_left", 0, 20)]
    obs = Observation.from_windows(wins, outages=outs)
    tr = door_track("front-person-1", t0)
    assert origin_zone(tr, sample_config, observation=obs) == expected


def test_origin_null_for_camera_missing_from_observation(sample_config: Config) -> None:
    obs = Observation.from_windows([_win("w0", "side_left", 0, 20)])
    assert origin_zone(door_track("front-person-1", 5.0), sample_config, observation=obs) is None
    # No observation info at all: treated as observed (documented default).
    assert origin_zone(door_track("front-person-1", 5.0), sample_config) == "front_door_egress"


def test_origin_tagging_is_deterministic_and_skips_unknown_cameras(sample_config: Config) -> None:
    courier = courier_track("front-person-1", t_end=20.0)
    reborn = door_track("front-person-2", 25.0)
    ghost = path_track("garage-person-1", "garage", [(0, 300, 600), (5, 900, 600)])
    tags1 = assign_origins([courier, reborn, ghost], sample_config)
    tags2 = assign_origins([ghost, reborn, courier], sample_config)
    assert tags1 == tags2 == {"front-person-1": "driveway_entry", "front-person-2": None}
    assert ghost.origin_zone is None
