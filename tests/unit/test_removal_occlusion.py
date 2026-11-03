"""FIXTURE: a missing or partly hidden package is not automatically removed (FR-008)."""

from vigil.models import Box, CameraCfg, Config, Track, TrackFrame, Watch, Window
from vigil.perception.events import Observation, build_events

FULL = Box(x1=200, y1=200, x2=300, y2=300)
PART = Box(x1=205, y1=205, x2=215, y2=215)
PERSON = Box(x1=180, y1=180, x2=320, y2=320)
CFG = Config(cameras=[CameraCfg(id="front", name="Front", width=1000, height=1000)])
WATCH = Watch(id="watch", camera_id="front", phrase="package", origin="owner", status="watching")


def track(tid, points, cls="package"):
    return Track(
        id=tid,
        camera_id="front",
        cls=cls,
        t_first=points[0][0],
        t_last=points[-1][0],
        frames=[TrackFrame(t=t, box=b) for t, b in points],
    )


def observation(*spans):
    return Observation.from_windows(
        [Window(id=f"w{i}", camera_id="front", t0=a, t1=b) for i, (a, b) in enumerate(spans)]
    )


def removed(tracks, obs):
    return [
        e for e in build_events(tracks, CFG, [], [WATCH], observation=obs) if e.type == "removed"
    ]


def test_partial_occlusion_does_not_remove():
    hidden = track("pkg", [(0, FULL), (4, FULL), (4.5, PART)])
    returned = track("return", [(6, FULL), (10, FULL)])
    person = track("person", [(0, PERSON), (4.5, PERSON), (10, PERSON)], "person")
    assert removed([hidden, returned, person], observation((0, 10))) == []


def test_reappearance_across_window_boundary():
    hidden = track("pkg", [(0, FULL), (8, FULL), (8.5, PART)])
    returned = track("new-id", [(12, FULL), (18, FULL)])
    person = track("person", [(8.5, PERSON), (18, PERSON)], "person")
    # The session processor retains prior tracks and joins overlapping observation spans.
    assert removed([hidden, returned, person], observation((0, 10), (8, 18))) == []


def test_delayed_reappearance():
    hidden = track("pkg", [(0, FULL), (4.8, FULL), (4.9, PART)])
    person = track("person", [(4.9, PERSON), (20, PERSON)], "person")
    assert removed([hidden, person], observation((0, 5.5))) == []  # only 0.6 s absent
    assert len(removed([hidden, person], observation((0, 7)))) == 1  # enough observed absence
    returned = track("later-id", [(12, FULL), (20, FULL)])
    assert removed([hidden, person, returned], observation((0, 10), (8, 20))) == []
