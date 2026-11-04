"""Enrolling faces from a processed capture (spec change 2026-11-04, face templates).

Only person tracks, only frames whose foot point lies in a property zone (never a
`perimeter`/street zone), and only the local detector: synthetic frames, fake models.
"""

import json
from datetime import UTC, datetime

import numpy as np

from vigil.faces import FaceBox, FaceStore
from vigil.faces.enroll import enroll_capture, foot_zone_kind
from vigil.models import CameraCfg

START = "2026-11-04T17:07:00+00:00"


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


def _write(tmp_path, frames, capture="cap-1"):
    results = tmp_path / "results" / capture
    windows = tmp_path / "windows" / capture
    results.mkdir(parents=True)
    windows.mkdir(parents=True)
    (results / "visits.json").write_text(
        json.dumps(
            {
                "session_start": START,
                "tracks": [
                    {"id": "cam-person-1", "camera_id": "cam", "phrase": "person", "t_first": 0.0},
                    {"id": "cam-car-1", "camera_id": "cam", "phrase": "car", "t_first": 0.0},
                ],
                "overlays": {"cameras": {"cam": {"width": 1536, "height": 576, "frames": frames}}},
            }
        )
    )
    (windows / "windows.json").write_text(
        json.dumps(
            [{"id": "w1", "camera_id": "cam", "t0": 0.0, "t1": 10.0, "path": "part-000.mp4"}]
        )
    )
    return results, windows


def _frame(t, foot_y_overlay, track="cam-person-1", cls="person"):
    # Box in overlay pixels (1536x576); config is 1920x720, so ×1.25 to compare with zones.
    return {"t": t, "objects": [{"box": [700, foot_y_overlay - 200, 760, foot_y_overlay],
                                 "cls": cls, "track_id": track}]}  # fmt: skip


class FakeVideo:
    """Frames of the video size (3072x1152, twice the overlay) and a log of reads."""

    def __init__(self):
        self.reads: list[float] = []

    def __call__(self, path, offset):
        self.reads.append(round(offset, 2))
        return np.zeros((1152, 3072, 3), np.uint8)


def _detect(seen):
    def detect(frame, *, roi=None):
        seen.append(roi)
        x0, y0, x1, y1 = roi
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        return [FaceBox(box=(cx - 15, cy - 15, 30, 30), landmarks=((cx, cy),) * 5, score=0.95)]

    return detect


def _embed(frame, face):
    v = np.zeros(128, np.float32)
    v[0] = 1.0
    return v


def test_foot_zone_kind_uses_config_pixels():
    cam = _camera()
    assert foot_zone_kind(cam, (100, 0, 200, 400), scale=(1.0, 1.0)) == "perimeter"
    assert foot_zone_kind(cam, (100, 0, 200, 600), scale=(1.0, 1.0)) == "interior_yard"
    assert foot_zone_kind(cam, (100, 0, 200, 100), scale=(1.0, 1.0)) is None


def test_enroll_only_samples_frames_inside_the_property(tmp_path):
    # Overlay foot y 320 → config 400 (street); 480 → 600 (garden).
    frames = [_frame(1.0, 320), _frame(2.0, 320), _frame(3.0, 480), _frame(4.0, 480)]
    results, windows = _write(tmp_path, frames)
    video, seen = FakeVideo(), []
    store = FaceStore(tmp_path / "faces.db")
    report = enroll_capture("cap-1", results, windows, [_camera()], store,
                            detect=_detect(seen), embed=_embed, crop=lambda f, b: b"jpg",
                            read_frame=video)  # fmt: skip
    assert video.reads == [3.0, 4.0]
    assert report["tracks_inside"] == 1
    assert report["faces_kept"] == 2
    profiles = store.profile_for_capture("cap-1")
    assert len(profiles) == 1
    assert profiles[0]["sightings"][0]["seen_at"].startswith("2026-11-04T17:07")


def test_enroll_ignores_vehicles_and_street_only_people(tmp_path):
    frames = [_frame(1.0, 480, track="cam-car-1", cls="car"), _frame(2.0, 320)]
    results, windows = _write(tmp_path, frames)
    video = FakeVideo()
    store = FaceStore(tmp_path / "faces.db")
    report = enroll_capture("cap-1", results, windows, [_camera()], store,
                            detect=_detect([]), embed=_embed, crop=lambda f, b: b"jpg",
                            read_frame=video)  # fmt: skip
    assert video.reads == []
    assert report["tracks_inside"] == 0
    assert store.profiles() == []


def test_enroll_scales_overlay_boxes_to_the_video_frame(tmp_path):
    results, windows = _write(tmp_path, [_frame(3.0, 480)])
    seen: list = []
    enroll_capture("cap-1", results, windows, [_camera()], FaceStore(tmp_path / "f.db"),
                   detect=_detect(seen), embed=_embed, crop=lambda f, b: b"jpg",
                   read_frame=FakeVideo())  # fmt: skip
    x0, y0, x1, _ = seen[0]
    # Person box x 700..760 in overlay pixels is 1400..1520 in the 3072-wide video frame.
    assert x0 >= 1390
    assert x1 <= 1530
    assert y0 >= 2 * (480 - 200) - 1


def test_same_face_in_a_later_capture_is_a_second_sighting(tmp_path):
    store = FaceStore(tmp_path / "faces.db")
    for capture in ("cap-1", "cap-2"):
        results, windows = _write(tmp_path, [_frame(3.0, 480)], capture=capture)
        enroll_capture(capture, results, windows, [_camera()], store,
                       detect=_detect([]), embed=_embed, crop=lambda f, b: b"jpg",
                       read_frame=FakeVideo())  # fmt: skip
    (profile,) = store.profiles()
    assert profile["count"] == 2
    assert {s["capture_id"] for s in profile["sightings"]} == {"cap-1", "cap-2"}


def test_enroll_reports_faces_too_small_to_keep(tmp_path):
    results, windows = _write(tmp_path, [_frame(3.0, 480)])

    def tiny(frame, *, roi=None):
        x0, y0, _, _ = roi
        return [FaceBox(box=(x0, y0, 10, 10), landmarks=((x0, y0),) * 5, score=0.9)]

    report = enroll_capture("cap-1", results, windows, [_camera()], FaceStore(tmp_path / "f.db"),
                            detect=tiny, embed=_embed, crop=lambda f, b: b"jpg",
                            read_frame=FakeVideo())  # fmt: skip
    assert report["faces_kept"] == 0
    assert report["faces_too_small"] == 1
    assert datetime.fromisoformat(START).tzinfo == UTC
