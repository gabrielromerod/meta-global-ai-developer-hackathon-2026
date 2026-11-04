"""One moment seen by several cameras becomes one session on one clock (FR-010, FR-031).

Each event capture is its own single-camera session with its own `session_start`; a person
who walks from the driveway camera to the walkway camera can only be linked when both
captures share a timeline. Generated JSON only; no footage.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from vigil.reolink.moments import group_moments, merge_captures, moment_name

T0 = datetime(2026, 11, 4, 1, 7, 14, tzinfo=UTC)


def _capture(root, name: str, camera: str, start: datetime, windows, kind="person", t=(10.0, 15.0)):
    folder = root / "windows" / name
    folder.mkdir(parents=True)
    (folder / "capture.json").write_text("{}", encoding="utf-8")
    rows = [
        {"id": f"{camera}_{i}", "camera_id": camera, "t0": a, "t1": b,
         "path": str(folder / f"part-{i:03d}.mp4"), "status": "pending", "fps": 10.0,
         "width": 1920, "height": 720}
        for i, (a, b) in enumerate(windows)
    ]  # fmt: skip
    (folder / "windows.json").write_text(json.dumps(rows), encoding="utf-8")
    session = {
        "session_start": start.isoformat(),
        "camera_ai_events": [
            {"id": f"cai_{camera}", "camera_id": camera, "kind": kind, "t0": t[0], "t1": t[1]}
        ],
        "camera_ai_events_measured": True,
        "source_label": "Event clips",
        "truncated_after": {camera: windows[-1][1]},
        "capture_gaps": [{"camera_id": camera, "t0": 40.0, "t1": 41.0}],
        "illumination_basis": "observed chroma heuristic",
    }
    (folder / "session.json").write_text(json.dumps(session), encoding="utf-8")
    return folder


def test_merge_puts_two_cameras_on_one_clock(tmp_path):
    left = _capture(tmp_path, "left-a", "front_left_duo", T0, [(0.0, 5.8), (5.7, 13.1)])
    right = _capture(tmp_path, "right-b", "front_right_duo", T0 + timedelta(seconds=4.08),
                     [(0.0, 3.8), (17.98, 45.43)])  # fmt: skip
    out = merge_captures([right, left], tmp_path / "windows")
    assert out.name == moment_name([left.name, right.name])
    windows = json.loads((out / "windows.json").read_text(encoding="utf-8"))
    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert datetime.fromisoformat(session["session_start"]) == T0
    by_id = {w["id"]: w for w in windows}
    assert by_id["front_right_duo_1"]["t0"] == pytest.approx(22.06)
    assert by_id["front_left_duo_0"]["t0"] == 0.0
    assert [w["t0"] for w in windows] == sorted(w["t0"] for w in windows)
    assert by_id["front_right_duo_1"]["path"].endswith("right-b/part-001.mp4")
    events = {e["camera_id"]: e for e in session["camera_ai_events"]}
    assert events["front_right_duo"]["t0"] == pytest.approx(14.08)
    assert session["truncated_after"]["front_right_duo"] == pytest.approx(49.51)
    gap = next(g for g in session["capture_gaps"] if g["camera_id"] == "front_right_duo")
    assert gap["t0"] == pytest.approx(44.08)
    assert session["merged_from"] == sorted([left.name, right.name])
    assert not (out / "capture.json").exists()  # a moment is not a capture row


def test_merge_refuses_one_camera_twice_and_overlapping_window_ids(tmp_path):
    a = _capture(tmp_path, "a", "porch", T0, [(0.0, 5.0)])
    b = _capture(tmp_path, "b", "porch", T0 + timedelta(seconds=30), [(0.0, 5.0)])
    with pytest.raises(ValueError, match="window id"):
        merge_captures([a, b], tmp_path / "windows")


def test_group_moments_joins_cameras_that_saw_someone_within_a_minute():
    rows = [
        {"id": "l", "camera_id": "front_left_duo", "kind": "person",
         "started_at": "2026-11-04T01:07:24+00:00", "ended_at": "2026-11-04T01:07:29+00:00"},
        {"id": "r", "camera_id": "front_right_duo", "kind": "person",
         "started_at": "2026-11-04T01:07:28+00:00", "ended_at": "2026-11-04T01:08:06+00:00"},
        {"id": "car", "camera_id": "front_right_duo", "kind": "vehicle",
         "started_at": "2026-11-04T01:20:00+00:00", "ended_at": "2026-11-04T01:20:10+00:00"},
        {"id": "late", "camera_id": "porch", "kind": "person",
         "started_at": "2026-11-04T01:30:00+00:00", "ended_at": "2026-11-04T01:30:10+00:00"},
    ]  # fmt: skip
    assert group_moments(rows) == [["l", "r"]]  # one camera alone is not a multi-camera moment
