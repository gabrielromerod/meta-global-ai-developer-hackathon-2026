"""FR-005: frame differencing outside masked areas; windows below a per-camera threshold
are idle and make no model calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.video.synth import blob_clip
from vigil.ingest.motion import (
    DEFAULT_MOTION_THRESHOLD,
    gate_window,
    motion_score,
    select_active,
    threshold_for,
)
from vigil.models import CameraCfg, Window

SIZE = (640, 360)
# Privacy polygon over the right half of the frame (pixels of the 640x360 clip).
RIGHT_HALF = [[(320, 0), (640, 0), (640, 360), (320, 360)]]


@pytest.fixture(scope="module")
def clips(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("motion")
    return {
        "static": blob_clip(d / "static.mp4", 3.0, size=SIZE, blob=None),
        # A bright square walks across the left half.
        "moving": blob_clip(d / "moving.mp4", 3.0, size=SIZE, blob=(20, 100, 260, 220)),
        # A bright square moves only inside the right-half privacy polygon.
        "masked": blob_clip(d / "masked.mp4", 3.0, size=SIZE, blob=(380, 60, 560, 260)),
    }


def window(path: Path, cam: str = "front") -> Window:
    return Window(id=f"{cam}_000000000", camera_id=cam, t0=0.0, t1=3.0, path=str(path))


def test_static_clip_scores_below_threshold(clips: dict[str, Path]) -> None:
    score = motion_score(clips["static"], [])
    assert 0.0 <= score < DEFAULT_MOTION_THRESHOLD / 4


def test_moving_blob_scores_above_threshold(clips: dict[str, Path]) -> None:
    score = motion_score(clips["moving"], [])
    assert score > DEFAULT_MOTION_THRESHOLD * 2


def test_motion_inside_privacy_polygon_is_ignored(clips: dict[str, Path]) -> None:
    assert motion_score(clips["masked"], []) > DEFAULT_MOTION_THRESHOLD  # visible without mask
    assert motion_score(clips["masked"], RIGHT_HALF) < DEFAULT_MOTION_THRESHOLD / 4
    # The mask does not hide motion elsewhere.
    assert motion_score(clips["moving"], RIGHT_HALF) > DEFAULT_MOTION_THRESHOLD * 2


def test_polygons_in_reference_frame_are_rescaled(clips: dict[str, Path]) -> None:
    right_half_720p = [[(640, 0), (1280, 0), (1280, 720), (640, 720)]]
    score = motion_score(clips["masked"], right_half_720p, ref_size=(1280, 720))
    assert score < DEFAULT_MOTION_THRESHOLD / 4


def test_gate_marks_static_window_idle(clips: dict[str, Path]) -> None:
    cam = CameraCfg(id="front", name="Front", width=640, height=360)
    w = gate_window(window(clips["static"]), cam)
    assert w.status == "idle"
    assert w.motion is not None
    assert w.motion < DEFAULT_MOTION_THRESHOLD
    assert w.trigger is None


def test_gate_marks_moving_window_active(clips: dict[str, Path]) -> None:
    cam = CameraCfg(id="front", name="Front", width=640, height=360)
    w = gate_window(window(clips["moving"]), cam)
    assert w.status == "pending"
    assert w.trigger == "motion"
    assert w.motion is not None
    assert w.motion > DEFAULT_MOTION_THRESHOLD


def test_gate_uses_camera_privacy_polygons(clips: dict[str, Path]) -> None:
    cam = CameraCfg(id="side_right", name="Right", width=640, height=360, privacy=RIGHT_HALF)
    assert gate_window(window(clips["masked"], "side_right"), cam).status == "idle"


def test_per_camera_threshold(clips: dict[str, Path]) -> None:
    lenient = CameraCfg(id="backyard", name="Backyard", width=640, height=360)
    strict = lenient.model_copy(update={"motion_threshold": 0.5})
    assert threshold_for(lenient) == DEFAULT_MOTION_THRESHOLD
    assert threshold_for(strict) == 0.5
    assert gate_window(window(clips["moving"], "backyard"), lenient).status == "pending"
    assert gate_window(window(clips["moving"], "backyard"), strict).status == "idle"


def test_camera_ai_event_forces_processing(clips: dict[str, Path]) -> None:
    """FR-033: a window overlapping a Reolink AI event is processed even without motion."""
    cam = CameraCfg(id="front", name="Front", width=640, height=360)
    w = gate_window(window(clips["static"]), cam, camera_ai=True)
    assert w.status == "pending"
    assert w.trigger == "camera_ai"


def test_idle_windows_make_no_model_calls(clips: dict[str, Path]) -> None:
    cam = CameraCfg(id="front", name="Front", width=640, height=360)
    wins = [
        gate_window(window(clips["static"]).model_copy(update={"id": "a"}), cam),
        gate_window(window(clips["moving"]).model_copy(update={"id": "b"}), cam),
    ]
    calls: list[str] = []
    for w in select_active(wins):
        calls.append(w.id)  # stands in for the SAM upload (FR-006)
    assert calls == ["b"]


def test_gate_requires_a_path() -> None:
    cam = CameraCfg(id="front", name="Front")
    with pytest.raises(ValueError):
        gate_window(Window(id="x", camera_id="front", t0=0, t1=1), cam)
