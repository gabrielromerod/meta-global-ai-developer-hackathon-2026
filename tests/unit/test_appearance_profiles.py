"""Clothing-signature profiles when no face is large enough (change 2026-11-04, fallback).

Grouped by Spark's FR-009 allowlist notes only (upper/lower colour, carried items), people
inside the property only, and one sighting per arrival (clips within 2 minutes collapse).
"""

import json

from vigil.faces.appearance import appearance_profiles, signature
from vigil.models import CameraCfg


def _camera() -> CameraCfg:
    return CameraCfg(
        id="cam",
        name="Cam",
        width=1920,
        height=720,
        zones={
            "street": [(0, 380), (1920, 380), (1920, 420), (0, 420)],
            "garden": [(0, 420), (1920, 420), (1920, 720), (0, 720)],
        },
        zone_kinds={"street": "perimeter", "garden": "interior_yard"},
    )


def _capture(root, capture, start, notes, foot_y=600, camera="cam"):
    folder = root / capture
    folder.mkdir(parents=True)
    tracks, frames, appearance = [], [], {}
    for n, note in enumerate(notes):
        tid = f"{camera}-person-{n}"
        tracks.append({"id": tid, "camera_id": camera, "phrase": "person", "t_first": 1.0})
        frames.append({"t": 1.0, "objects": [{"box": [100, foot_y - 200, 160, foot_y],
                                              "cls": "person", "track_id": tid}]})  # fmt: skip
        appearance[tid] = {"class": "person", **note}
    (folder / "visits.json").write_text(json.dumps({
        "session_start": start, "tracks": tracks, "appearance": appearance,
        "overlays": {"cameras": {camera: {"width": 1920, "height": 720, "frames": frames}}},
    }))  # fmt: skip


WHITE_BLACK = {"upper_color": "white", "lower_color": "black", "carrying": []}


def test_signature_needs_two_known_traits():
    assert signature({"upper_color": "white", "lower_color": "black"}) == ("white", "black", ())
    assert signature({"upper_color": "white", "lower_color": "unknown", "carrying": []}) is None
    assert signature({"upper_color": "red", "lower_color": "unknown", "carrying": ["bag"]}) == (
        "red",
        "unknown",
        ("bag",),
    )


def test_four_arrivals_in_the_same_clothes_make_one_profile(tmp_path):
    for n, hour in enumerate(("17", "18", "19", "20")):
        _capture(tmp_path, f"cap-{n}", f"2026-11-03T{hour}:00:00+00:00", [WHITE_BLACK])
    (profile,) = appearance_profiles(tmp_path, [_camera()])
    assert profile["count"] == 4
    assert profile["basis"] == "clothing"
    assert profile["label"] == "white top, black bottoms"
    assert [s["capture_id"] for s in profile["sightings"]] == ["cap-3", "cap-2", "cap-1", "cap-0"]


def test_two_cameras_on_one_arrival_count_once(tmp_path):
    _capture(tmp_path, "left", "2026-11-03T17:07:00+00:00", [WHITE_BLACK])
    _capture(tmp_path, "right", "2026-11-03T17:07:40+00:00", [WHITE_BLACK])
    (profile,) = appearance_profiles(tmp_path, [_camera()])
    assert profile["count"] == 1
    assert {s["capture_id"] for s in profile["sightings"]} == {"left", "right"}


def test_street_only_people_and_moments_are_ignored(tmp_path):
    _capture(tmp_path, "street", "2026-11-03T17:00:00+00:00", [WHITE_BLACK], foot_y=400)
    _capture(tmp_path, "moment-abc", "2026-11-03T18:00:00+00:00", [WHITE_BLACK])
    assert appearance_profiles(tmp_path, [_camera()]) == []


def test_unknown_clothing_never_groups(tmp_path):
    vague = {"upper_color": "unknown", "lower_color": "unknown", "carrying": []}
    for n in range(3):
        _capture(tmp_path, f"cap-{n}", f"2026-11-03T1{n}:00:00+00:00", [vague])
    assert appearance_profiles(tmp_path, [_camera()]) == []
