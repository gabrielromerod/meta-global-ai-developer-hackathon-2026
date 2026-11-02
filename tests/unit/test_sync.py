"""FR-002: per-camera clock offsets from one clap + phone-flash sync event; aligned sync
times agree within 0.2 s; sessions whose residual exceeds 0.5 s are rejected
(spec 3 "Camera clocks drift" -> test_sync_residual)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.video.synth import flash_clip
from vigil.ingest.sync import (
    MAX_RESIDUAL_S,
    SyncError,
    SyncEventNotFoundError,
    SyncResidualError,
    apply_offsets,
    detect_audio_onsets,
    detect_flashes,
    detect_sync_events,
    measure_offsets,
    sync_session,
)
from vigil.models import Config

FPS = 15.0
FRAME = 1 / FPS


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, float]]:
    """Three cameras that started recording at different moments: the single clap/flash
    happens at a different clip time on each."""
    d = tmp_path_factory.mktemp("sync")
    truth = {"front": 1.0, "side_left": 2.4, "backyard": 3.2}
    return {
        cam: (flash_clip(d / f"{cam}.mp4", 6.0, [t], fps=FPS, seed=i), t)
        for i, (cam, t) in enumerate(truth.items())
    }


def test_detect_flash_time_within_one_frame(session: dict[str, tuple[Path, float]]) -> None:
    path, t = session["side_left"]
    flashes = detect_flashes(path)
    assert len(flashes) == 1
    assert abs(flashes[0] - t) <= FRAME + 1e-6


def test_offsets_align_sync_event_within_0_2s(session: dict[str, tuple[Path, float]]) -> None:
    clips = {cam: p for cam, (p, _) in session.items()}
    offsets = measure_offsets(clips)
    assert offsets["front"] == 0.0  # first camera is the reference
    for cam, (_, t) in session.items():
        true_offset = session["front"][1] - t
        assert abs(offsets[cam] - true_offset) <= 0.1, cam
    # The sync event lands at the same session time on every camera.
    aligned = [t + offsets[cam] for cam, (_, t) in session.items()]
    assert max(aligned) - min(aligned) <= 0.2


def test_offsets_with_clip_start_times(session: dict[str, tuple[Path, float]]) -> None:
    """Clip start times on each camera's own clock are added before aligning."""
    clips = {cam: p for cam, (p, _) in session.items()}
    starts = {"front": 1000.0, "side_left": 1000.5, "backyard": 999.0}
    res = sync_session(clips, clip_starts=starts, reference="side_left")
    assert res.reference == "side_left"
    assert res.offsets["side_left"] == 0.0
    t_sl = starts["side_left"] + session["side_left"][1]
    for cam, (_, t) in session.items():
        assert abs(starts[cam] + t + res.offsets[cam] - t_sl) <= 0.1


def test_sync_residual(tmp_path: Path) -> None:
    """Start and end claps: a camera whose clock runs 0.8 s off by the end is rejected."""
    good = {
        "front": flash_clip(tmp_path / "f.mp4", 8.0, [1.0, 6.0], fps=FPS, seed=1),
        "side_left": flash_clip(tmp_path / "s.mp4", 8.0, [1.5, 6.5], fps=FPS, seed=2),
    }
    res = sync_session(good)
    assert res.residual_s <= 0.2
    assert res.offsets["side_left"] == pytest.approx(-0.5, abs=0.1)

    drifted = dict(good, backyard=flash_clip(tmp_path / "b.mp4", 8.0, [0.5, 6.3], fps=FPS))
    with pytest.raises(SyncResidualError) as ei:
        sync_session(drifted)
    assert ei.value.residual_s > MAX_RESIDUAL_S
    assert ei.value.camera_id == "backyard"
    assert MAX_RESIDUAL_S == 0.5


def test_small_drift_is_accepted_and_reported(tmp_path: Path) -> None:
    clips = {
        "front": flash_clip(tmp_path / "f.mp4", 8.0, [1.0, 6.0], fps=FPS, seed=1),
        "backyard": flash_clip(tmp_path / "b.mp4", 8.0, [2.0, 7.3], fps=FPS, seed=3),
    }
    res = sync_session(clips)
    assert 0.2 <= res.residual_s <= 0.5  # 0.3 s drift: accepted, but visible in the result


def test_camera_without_sync_event_is_excluded(
    session: dict[str, tuple[Path, float]], tmp_path: Path
) -> None:
    """UC-01: sync event not found on a camera -> that camera is excluded until fixed."""
    clips = {cam: p for cam, (p, _) in session.items()}
    clips["side_right"] = flash_clip(tmp_path / "dark.mp4", 4.0, [], fps=FPS)
    res = sync_session(clips)
    assert "side_right" in res.excluded
    assert "side_right" not in res.offsets
    assert set(res.offsets) == {"front", "side_left", "backyard"}
    with pytest.raises(SyncEventNotFoundError):
        detect_sync_events(clips["side_right"])


def test_reference_without_event_is_an_error(tmp_path: Path) -> None:
    clips = {
        "front": flash_clip(tmp_path / "dark.mp4", 3.0, [], fps=FPS),
        "side_left": flash_clip(tmp_path / "s.mp4", 3.0, [1.0], fps=FPS),
    }
    with pytest.raises(SyncError):
        sync_session(clips, reference="front")
    with pytest.raises(SyncError):
        sync_session({"front": clips["front"]})


def test_audio_clap_used_when_no_flash_is_visible(tmp_path: Path) -> None:
    path = flash_clip(tmp_path / "a.mp4", 4.0, [], fps=FPS, click_times=[2.25])
    onsets = detect_audio_onsets(path)
    assert len(onsets) == 1
    assert abs(onsets[0] - 2.25) <= 0.05
    events = detect_sync_events(path)
    assert events[0].source == "audio"
    assert abs(events[0].t - 2.25) <= 0.05


def test_flash_preferred_and_av_agreement_reported(tmp_path: Path) -> None:
    path = flash_clip(tmp_path / "av.mp4", 4.0, [2.0], fps=FPS, click_times=[2.0])
    ev = detect_sync_events(path)[0]
    assert ev.source == "video"
    assert ev.av_delta_s is not None
    assert abs(ev.av_delta_s) <= 0.1


def test_no_audio_means_no_onsets(session: dict[str, tuple[Path, float]]) -> None:
    assert detect_audio_onsets(session["front"][0]) == []


def test_apply_offsets(sample_config: Config) -> None:
    cfg = apply_offsets(sample_config, {"side_left": -1.25, "front": 0.0})
    assert cfg.camera("side_left").offset_s == -1.25
    assert cfg.camera("side_right").offset_s == sample_config.camera("side_right").offset_s
    assert sample_config.camera("side_left").offset_s == -0.42  # original untouched
    with pytest.raises(SyncError):
        apply_offsets(sample_config, {"garage": 1.0})
