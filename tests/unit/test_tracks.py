"""Track stitching across overlapping windows (FR-007) and overlay JSON (FR-018 data)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from vigil.meta.sam import parse_video_output
from vigil.models import Box, SamFrame, SamObject, Track, TrackFrame, Window
from vigil.perception.overlays import overlay_json
from vigil.perception.tracks import phrase_class, stitch, stitch_with_links

META = Path(__file__).resolve().parents[1] / "fixtures" / "meta"


def _obj(win: str, t0: float, obj_id: int, boxes: list[tuple[int, Box]], **kw) -> SamObject:
    fps = kw.pop("fps", 10.0)
    return SamObject(
        window_id=win,
        camera_id=kw.pop("camera_id", "side_left"),
        phrase=kw.pop("phrase", "person"),
        obj_id=obj_id,
        frames=[
            SamFrame(frame=f, t=round(t0 + f / fps, 6), box=b, confidence=kw.get("conf"))
            for f, b in boxes
        ],
    )


def _static(win: str, t0: float, obj_id: int, box: Box, frames: range, **kw) -> SamObject:
    return _obj(win, t0, obj_id, [(f, box) for f in frames], **kw)


B = Box(x1=100, y1=200, x2=140, y2=300)
B_FAR = Box(x1=700, y1=200, x2=740, y2=300)


@pytest.fixture(scope="module")
def fixture_objs() -> list[SamObject]:
    objs: list[SamObject] = []
    for name, t0 in (("w0", 0.0), ("w1", 8.0), ("w2", 16.0)):
        w = Window(id=name, camera_id="side_left", t0=t0, t1=t0 + 10.0)
        text = (META / f"sam_person_{name}.txt").read_text(encoding="utf-8")
        objs += parse_video_output(text, w, "person")
    return objs


def test_stitch_person_across_three_windows_is_one_track(fixture_objs) -> None:
    tracks = stitch(fixture_objs)
    assert len(tracks) == 2  # the walker, plus the static person seen only in w1
    walker = next(t for t in tracks if len(t.window_ids) == 3)
    assert walker.window_ids == ["w0", "w1", "w2"]
    assert walker.cls == "person"
    assert walker.camera_id == "side_left"
    assert walker.t_first == 0.0
    assert walker.t_last == pytest.approx(25.8)
    times = [f.t for f in walker.frames]
    assert times == sorted(times)
    assert len(times) == len(set(times)) == 130
    assert walker.id == "side_left-person-1"
    assert walker.tag == "T1"
    other = next(t for t in tracks if t is not walker)
    assert other.id == "side_left-person-2"
    assert other.tag == "T2"
    assert other.window_ids == ["w1"]
    assert all(f.mask_rle for f in walker.frames)


def test_stitch_links_record_sam_ids(fixture_objs) -> None:
    tracks, links = stitch_with_links(fixture_objs)
    walker = next(t for t in tracks if len(t.window_ids) == 3)
    mine = sorted((w, o) for tid, w, o in links if tid == walker.id)
    assert mine == [("w0", 0), ("w1", 3), ("w2", 1)]
    assert len(links) == 4


def test_stitch_is_deterministic_under_input_order(fixture_objs) -> None:
    shuffled = list(fixture_objs)
    random.Random(3).shuffle(shuffled)
    assert stitch(shuffled) == stitch(fixture_objs)


def test_stitch_empty() -> None:
    assert stitch([]) == []


def test_stitch_low_iou_stays_separate() -> None:
    a = _static("wa", 0.0, 0, B, range(0, 100))
    b = _static("wb", 8.0, 0, B_FAR, range(0, 100))
    tracks = stitch([a, b])
    assert len(tracks) == 2


def test_stitch_requires_shared_frames() -> None:
    a = _static("wa", 0.0, 0, B, range(0, 50))  # 0.0 .. 4.9 s
    b = _static("wb", 8.0, 0, B, range(0, 100))  # 8.0 .. 17.9 s
    assert len(stitch([a, b])) == 2


def test_stitch_is_one_to_one_between_windows() -> None:
    a = _static("wa", 0.0, 0, B, range(80, 100))
    near = Box(x1=104, y1=200, x2=144, y2=300)
    b1 = _static("wb", 8.0, 0, B, range(0, 20))
    b2 = _static("wb", 8.0, 1, near, range(0, 20))
    tracks, links = stitch_with_links([a, b1, b2])
    assert len(tracks) == 2
    joined = next(t for t in tracks if len(t.window_ids) == 2)
    assert sorted((w, o) for tid, w, o in links if tid == joined.id) == [("wa", 0), ("wb", 0)]


def test_stitch_separates_cameras_and_phrases() -> None:
    a = _static("wa", 0.0, 0, B, range(80, 100))
    b_cam = _static("wb", 8.0, 0, B, range(0, 20), camera_id="front")
    b_phrase = _static("wb", 8.0, 1, B, range(0, 20), phrase="car")
    tracks = stitch([a, b_cam, b_phrase])
    assert len(tracks) == 3
    assert {t.id for t in tracks} == {"side_left-person-1", "front-person-1", "side_left-car-1"}
    assert sorted(t.tag for t in tracks) == ["T1", "T2", "T3"]


def test_stitch_prefers_higher_confidence_on_shared_frames() -> None:
    hi = Box(x1=100, y1=200, x2=140, y2=300)
    lo = Box(x1=102, y1=200, x2=142, y2=300)
    a = _static("wa", 0.0, 0, lo, range(80, 100), conf=0.5)
    b = _static("wb", 8.0, 0, hi, range(0, 20), conf=0.9)
    (track,) = stitch([a, b])
    shared = [f for f in track.frames if 8.0 <= f.t <= 9.9]
    assert len(shared) == 20
    assert all(f.box == hi and f.confidence == 0.9 for f in shared)


def test_track_clipped_at_bottom_edge() -> None:
    bottom = Box(x1=500, y1=600, x2=560, y2=720)
    above = Box(x1=500, y1=500, x2=560, y2=700)
    obj = _obj("wa", 0.0, 0, [(0, above), (1, bottom)])
    (track,) = stitch([obj])
    assert [f.clipped for f in track.frames] == [False, True]
    (tall,) = stitch([obj], frame_height={"side_left": 1080})
    assert [f.clipped for f in tall.frames] == [False, False]


def test_track_class_from_phrase() -> None:
    assert phrase_class("person") == "person"
    assert phrase_class("People") == "person"
    assert phrase_class("car") == "car"
    assert phrase_class("package") == "package"
    assert phrase_class("parcel") == "package"
    assert phrase_class("red bicycle") == "object"


def test_overlay_json_groups_by_camera_and_time() -> None:
    t1 = Track(
        id="front-person-1",
        camera_id="front",
        cls="person",
        t_first=0.0,
        t_last=0.1,
        tag="T1",
        frames=[
            TrackFrame(t=0.0, box=B, mask_rle="abc", confidence=0.9),
            TrackFrame(t=0.1, box=B_FAR, clipped=True),
        ],
    )
    t2 = Track(
        id="front-car-1",
        camera_id="front",
        cls="car",
        t_first=0.1,
        t_last=0.1,
        tag="T2",
        frames=[TrackFrame(t=0.1, box=B)],
    )
    t3 = Track(
        id="backyard-person-1",
        camera_id="backyard",
        cls="person",
        t_first=5.0,
        t_last=5.0,
        tag="T3",
        frames=[TrackFrame(t=5.0, box=B)],
    )
    ov = overlay_json([t2, t3, t1], sizes={"front": (1280, 720)})
    assert ov["version"] == 1
    assert sorted(ov["cameras"]) == ["backyard", "front"]
    front = ov["cameras"]["front"]
    assert front["width"] == 1280
    assert front["height"] == 720
    assert front["tracks"]["front-person-1"] == {"tag": "T1", "cls": "person"}
    assert [fr["t"] for fr in front["frames"]] == [0.0, 0.1]
    first = front["frames"][0]["objects"]
    assert first == [
        {
            "track_id": "front-person-1",
            "tag": "T1",
            "cls": "person",
            "box": [100.0, 200.0, 140.0, 300.0],
            "mask_rle": "abc",
            "confidence": 0.9,
        }
    ]
    second = front["frames"][1]["objects"]
    assert [o["track_id"] for o in second] == ["front-car-1", "front-person-1"]
    assert "mask_rle" not in second[0]
    assert second[1]["clipped"] is True
    assert overlay_json([]) == {"version": 1, "cameras": {}}
