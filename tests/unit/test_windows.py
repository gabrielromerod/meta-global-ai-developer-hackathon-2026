"""FR-004: 10 s windows with 2 s overlap; H.264 MP4, 10 fps, <=1280 px wide, faststart;
window edges match the plan to one frame."""

from __future__ import annotations

import itertools
from pathlib import Path

import cv2
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.fixtures.video.synth import frame_index_clip, read_index, write_video
from vigil.ingest.media import has_audio, mp4_faststart, probe
from vigil.ingest.privacy import verify_clean
from vigil.ingest.windows import WindowError, cut_window, cut_windows, plan_windows, window_id
from vigil.models import Window

SRC_FPS = 30.0


@pytest.fixture(scope="module")
def src_1080p(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """20 s, 1920x1080, 30 fps, every frame carries its index, with an audio track."""
    d = tmp_path_factory.mktemp("windows")
    return frame_index_clip(d / "src.mp4", 20.0, fps=SRC_FPS, size=(1920, 1080), audio=True)


@pytest.fixture(scope="module")
def window_8_18(src_1080p: Path) -> tuple[Path, Window]:
    dst = src_1080p.with_name("w_8_18.mp4")
    w = cut_window(src_1080p, dst, 8.0, 18.0, camera_id="side_left")
    return dst, w


# ---------------------------------------------------------------------------
# plan_windows
# ---------------------------------------------------------------------------


def test_plan_windows_exact_edges() -> None:
    assert plan_windows(0, 30, 10, 2) == [(0, 10), (8, 18), (16, 26), (24, 30)]
    assert plan_windows(0, 26, 10, 2) == [(0, 10), (8, 18), (16, 26)]
    assert plan_windows(0, 10, 10, 2) == [(0, 10)]
    assert plan_windows(0, 4.5, 10, 2) == [(0, 4.5)]
    assert plan_windows(100.5, 120.5) == [(100.5, 110.5), (108.5, 118.5), (116.5, 120.5)]


def test_plan_windows_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError):
        plan_windows(10, 10)
    with pytest.raises(ValueError):
        plan_windows(0, 30, 10, 10)
    with pytest.raises(ValueError):
        plan_windows(0, 30, 10, -1)
    with pytest.raises(ValueError):
        plan_windows(0, 30, 0, 0)


@settings(max_examples=200, deadline=None)
@given(
    t0=st.floats(0, 10_000, allow_nan=False),
    dur=st.floats(0.1, 600, allow_nan=False),
    length=st.sampled_from([10.0, 12.0, 5.0]),
    overlap=st.sampled_from([0.0, 2.0, 1.0]),
)
def test_plan_windows_properties(t0: float, dur: float, length: float, overlap: float) -> None:
    t1 = t0 + dur
    wins = plan_windows(t0, t1, length, overlap)
    step = length - overlap
    assert wins[0][0] == pytest.approx(t0)
    assert wins[-1][1] == pytest.approx(t1)
    for k, (a, b) in enumerate(wins):
        assert t0 - 1e-9 <= a < b <= t1 + 1e-9
        assert b - a <= length + 1e-9
        assert a == pytest.approx(t0 + k * step, abs=1e-6)  # no accumulated drift
        if k + 1 < len(wins):
            assert b - a == pytest.approx(length)
            assert b - wins[k + 1][0] == pytest.approx(overlap)  # exact 2 s overlap
    # No window is redundant: each one reaches past the end of the previous one.
    for (_, b0), (_, b1) in itertools.pairwise(wins):
        assert b1 > b0


# ---------------------------------------------------------------------------
# cut_window
# ---------------------------------------------------------------------------


def test_window_is_h264_10fps_1280_faststart_no_audio(window_8_18: tuple[Path, Window]) -> None:
    dst, _ = window_8_18
    info = probe(dst)
    assert info.video_codec == "h264"
    assert info.fps == pytest.approx(10.0)
    assert info.width == 1280
    assert info.height == 720
    assert info.pix_fmt == "yuv420p"
    assert info.audio_streams == 0
    assert not has_audio(dst)
    assert mp4_faststart(dst)


def test_window_edges_match_plan_within_one_frame(window_8_18: tuple[Path, Window]) -> None:
    dst, _ = window_8_18
    cap = cv2.VideoCapture(str(dst))
    indices = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        indices.append(read_index(frame, scale=1280 / 1920))
    cap.release()
    assert len(indices) == 100  # 10 s at 10 fps
    first_t = indices[0] / SRC_FPS
    last_t = indices[-1] / SRC_FPS
    assert abs(first_t - 8.0) <= 1 / SRC_FPS + 1e-9
    # The last frame starts one output frame (0.1 s) before the window end.
    assert abs(last_t - (18.0 - 0.1)) <= 1 / SRC_FPS + 1e-9
    # Every output frame is 0.1 s after the previous one (3 source frames), within 1 frame.
    for k, idx in enumerate(indices):
        assert abs(idx - (240 + 3 * k)) <= 1, (k, idx)


def test_cut_window_returns_window_model(window_8_18: tuple[Path, Window]) -> None:
    dst, w = window_8_18
    assert isinstance(w, Window)
    assert w.camera_id == "side_left"
    assert (w.t0, w.t1) == (8.0, 18.0)
    assert w.path == str(dst)
    assert (w.fps, w.width, w.height) == (10.0, 1280, 720)
    assert w.status == "pending"
    assert w.id == window_id("side_left", 8.0)


def test_window_times_on_session_clock(src_1080p: Path, tmp_path: Path) -> None:
    w = cut_window(
        src_1080p, tmp_path / "w.mp4", 0.0, 2.0, camera_id="front", session_start_s=100.25
    )
    assert (w.t0, w.t1) == (100.25, 102.25)
    assert w.id == "front_000100250"


def test_window_clamped_to_clip_end(src_1080p: Path, tmp_path: Path) -> None:
    w = cut_window(src_1080p, tmp_path / "tail.mp4", 16.0, 26.0, camera_id="front")
    assert w.t1 == pytest.approx(20.0)
    assert probe(tmp_path / "tail.mp4").duration == pytest.approx(4.0, abs=0.15)
    with pytest.raises(WindowError):
        cut_window(src_1080p, tmp_path / "none.mp4", 25.0, 35.0, camera_id="front")
    with pytest.raises(ValueError):
        cut_window(src_1080p, tmp_path / "bad.mp4", 5.0, 5.0, camera_id="front")


def _solid(w: int, h: int):
    def frame(i: int) -> np.ndarray:
        return np.full((h, w, 3), (i * 10) % 255, np.uint8)

    return frame


@pytest.mark.parametrize(
    ("size", "expected"),
    [((640, 480), (640, 480)), ((2560, 1080), (1280, 540)), ((1300, 731), (1280, 720))],
)
def test_window_keeps_aspect_and_even_dims(
    tmp_path: Path, size: tuple[int, int], expected: tuple[int, int]
) -> None:
    pix = "yuv444p" if size[0] % 2 or size[1] % 2 else "yuv420p"
    src = write_video(tmp_path / "s.mp4", _solid(*size), 15, 15.0, size, pix_fmt=pix)
    cut_window(src, tmp_path / "w.mp4", 0.0, 1.0, camera_id="front")
    info = probe(tmp_path / "w.mp4")
    assert (info.width, info.height) == expected
    assert info.width <= 1280
    assert info.width % 2 == 0
    assert info.height % 2 == 0


def test_window_applies_privacy_polygons(src_1080p: Path, tmp_path: Path) -> None:
    polys = [[(0, 300), (1280, 300), (1280, 420), (0, 420)]]  # 1280x720 reference frame
    dst = tmp_path / "masked.mp4"
    cut_window(src_1080p, dst, 2.0, 4.0, camera_id="front", polygons=polys, ref_size=(1280, 720))
    assert verify_clean(dst, polys, ref_size=(1280, 720))
    assert not verify_clean(tmp_path / "masked.mp4", [[(0, 0), (1280, 0), (1280, 100)]])


def test_cut_windows_follows_plan(src_1080p: Path, tmp_path: Path) -> None:
    wins = cut_windows(src_1080p, tmp_path / "out", "backyard", length_s=10.0, overlap_s=2.0)
    assert [(w.t0, w.t1) for w in wins] == [(0.0, 10.0), (8.0, 18.0), (16.0, 20.0)]
    assert all(Path(w.path or "").exists() for w in wins)
    assert len({w.id for w in wins}) == 3
