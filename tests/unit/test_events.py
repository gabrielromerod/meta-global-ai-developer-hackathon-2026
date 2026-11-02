"""Event builder on synthetic tracks (FR-008): enter, exit, cross, touch, removed, dwell.

Geometry comes from the sample config (front: porch and driveway zones; side_left: side_gate
line and side_yard zone) and the po_side_gate fixture (bbox 800..880 x 400..660).
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from vigil.models import Box, Config, Event, ProtectedObject, Track, TrackFrame, Watch
from vigil.perception.events import build_events
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
