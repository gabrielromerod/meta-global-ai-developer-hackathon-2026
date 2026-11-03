"""Property: uncertainty (spec 12.1) — FR-039, NFR-026.

On synthetic noise the true point must be inside the stated 95% radius at least 93% of the
time, for both intrinsics sources (lens profile and nominal FOV) and for both calibration
error terms (audit-harness error where measured, landmark reprojection error otherwise).
The observation is the true foot pixel plus 3 px Gaussian noise (the noise model ``locate``
assumes); calibration error is simulated with a perturbed camera whose audit error is
reported to ``locate``, with a real lens that differs from the nominal FOV, or with a pose
solved from 6 noisy landmarks.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import vigil.spatial.locate as locate_mod
from vigil.models import Box, Calibration, TrackFrame
from vigil.spatial.calibrate import MarkerPair, calibrate_extrinsics, intrinsics_from_fov
from vigil.spatial.geometry import (
    CameraGeom,
    RaycastScene,
    grid_ground,
    look_at_extrinsics,
    pinhole_intrinsics,
)
from vigil.spatial.locate import locate

W, H = 1280, 720


def slope(x, z):
    return 0.06 * z - 0.02 * x + 0.05 * np.sin(0.5 * x)


SCENE = RaycastScene(ground=grid_ground(-14, -2, 14, 26, slope, step=1.0))
CAL = Calibration(
    camera_id="backyard",
    intrinsics=pinhole_intrinsics(W, H, f=900.0, dist=[-0.05, 0.0, 0.0, 0.0, 0.0]),
    extrinsics=look_at_extrinsics((0.0, 3.2, -1.0), (0.0, 0.3, 9.0)),
)
GEOM = CameraGeom.from_calibration(CAL)


def _trial(x: float, z: float, rng: np.random.Generator) -> bool | None:
    p = np.array([x, slope(x, z), z])
    uv, front = GEOM.project(p[None])
    u, v = uv[0] + rng.normal(0.0, 3.0, 2)
    if not front[0] or not (0 <= u < W and 0 <= v < H - 3):
        return None
    frame = TrackFrame(t=0.0, box=Box(x1=u - 20, y1=v - 200, x2=u + 20, y2=v))
    pos = locate(frame, CAL, SCENE, rng)
    if pos is None:
        return None
    return bool(np.hypot(pos.x - p[0], pos.z - p[2]) <= pos.r95)


@settings(
    max_examples=40,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    x=st.floats(min_value=-4.0, max_value=4.0),
    z=st.floats(min_value=3.0, max_value=14.0),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
def test_true_point_inside_r95_at_each_location(x, z, seed):
    rng = np.random.default_rng(seed)
    results = [r for _ in range(30) if (r := _trial(x, z, rng)) is not None]
    if len(results) < 20:
        return  # outside the view: nothing to state
    # 30 Bernoulli trials at p >= 0.95: at least 24 inside unless something is wrong.
    assert sum(results) >= 24, (x, z, sum(results), len(results))


def test_true_point_inside_r95_at_least_93_percent_overall():
    rng = np.random.default_rng(20261102)
    results = []
    while len(results) < 800:
        x, z = rng.uniform(-5, 5), rng.uniform(3, 15)
        r = _trial(x, z, rng)
        if r is not None:
            results.append(r)
    share = float(np.mean(results))
    assert share >= 0.93, share


def test_calibration_error_is_covered_by_heldout_term():
    """A camera whose true pose differs from the calibrated one by a known ground error."""
    rng = np.random.default_rng(11)
    true_geom = GEOM
    # Calibrated pose shifted 0.12 m sideways: about 0.12 m ground error everywhere.
    bad_ext = look_at_extrinsics((0.12, 3.2, -1.0), (0.12, 0.3, 9.0))
    bad_ext.heldout_ground_m = 0.12
    bad = Calibration(camera_id="backyard", intrinsics=CAL.intrinsics, extrinsics=bad_ext)
    inside = []
    for _ in range(300):
        x, z = rng.uniform(-4, 4), rng.uniform(3, 13)
        p = np.array([x, slope(x, z), z])
        uv, _ = true_geom.project(p[None])
        u, v = uv[0] + rng.normal(0.0, 3.0, 2)
        if not (0 <= u < W and 0 <= v < H - 3):
            continue
        frame = TrackFrame(t=0.0, box=Box(x1=u - 20, y1=v - 200, x2=u + 20, y2=v))
        pos = locate(frame, bad, SCENE, rng)
        if pos is not None:
            inside.append(np.hypot(pos.x - p[0], pos.z - p[2]) <= pos.r95)
    assert len(inside) > 200
    assert np.mean(inside) >= 0.93


# ---------------------------------------------------------------------------
# Both intrinsics sources (FR-036 revised Nov 2): fov_nominal and lens_profile
# ---------------------------------------------------------------------------

HFOV = 90.0
NOMINAL = intrinsics_from_fov(HFOV, W, H)
F_NOM = NOMINAL.k[0][0]
POSE = look_at_extrinsics((0.0, 3.2, -1.0), (0.0, 0.3, 9.0))
LANDMARKS = np.array(
    [[-3.0, 2.1, 5.0], [3.5, 0.0, 4.5], [0.0, 1.0, 8.5], [4.0, 2.2, 10.0],
     [-4.0, 0.0, 11.0], [2.0, 1.5, 14.0]]
)  # fmt: skip


def _true_lens(df: float, k1: float) -> CameraGeom:
    """The real lens: focal length off the datasheet by ``df`` and radial distortion k1."""
    k = pinhole_intrinsics(W, H, f=F_NOM * (1 + df), dist=[k1, 0.0, 0.0, 0.0, 0.0])
    return CameraGeom.from_calibration(Calibration(camera_id="c", intrinsics=k, extrinsics=POSE))


def _coverage(cal: Calibration, truth: CameraGeom, rng: np.random.Generator, n: int) -> float:
    inside = []
    while len(inside) < n:
        x, z = rng.uniform(-6, 6), rng.uniform(3, 15)
        p = np.array([x, slope(x, z), z])
        uv, front = truth.project(p[None])
        u, v = uv[0] + rng.normal(0.0, 3.0, 2)
        if not front[0] or not (0 <= u < W and 0 <= v < H - 3):
            continue
        frame = TrackFrame(t=0.0, box=Box(x1=u - 20, y1=v - 200, x2=u + 20, y2=v))
        pos = locate(frame, cal, SCENE, rng)
        if pos is not None:
            inside.append(np.hypot(pos.x - p[0], pos.z - p[2]) <= pos.r95)
    return float(np.mean(inside))


@pytest.mark.parametrize(("df", "k1"), [(0.0, 0.0), (0.02, -0.03), (-0.02, 0.03)])
def test_fov_nominal_true_point_inside_r95_at_least_93_percent(df, k1):
    """Nominal-FOV intrinsics (no lens model) on a lens whose focal error and distortion are
    at the 1-sigma prior: the radial term keeps r95 truthful, including at the edges."""
    cal = Calibration(camera_id="c", intrinsics=NOMINAL, extrinsics=POSE)
    share = _coverage(cal, _true_lens(df, k1), np.random.default_rng(5), 300)
    assert share >= 0.93, share


def _landmark_calibration(intr, truth: CameraGeom, click_px: float, rng) -> Calibration:
    uv, _ = truth.project(LANDMARKS)
    uv = uv + rng.normal(0.0, click_px, uv.shape)
    pairs = [
        MarkerPair(u=a, v=b, x=p[0], y=p[1], z=p[2])
        for (a, b), p in zip(uv, LANDMARKS, strict=True)
    ]
    ext = calibrate_extrinsics(pairs, intr)
    assert ext.heldout_ground_m is None  # product path: no audit measured
    return Calibration(camera_id="c", intrinsics=intr, extrinsics=ext)


def _landmark_only_share(intr, truth: CameraGeom, click_px: float, seed: int) -> float:
    rng = np.random.default_rng(seed)
    shares = [
        _coverage(_landmark_calibration(intr, truth, click_px, rng), truth, rng, 50)
        for _ in range(8)
    ]
    return float(np.mean(shares))


def test_landmark_only_lens_profile_r95_truthful(monkeypatch):
    """A product home: lens profile, 6 landmarks clicked with 4 px error, no audit. The
    landmark reprojection term keeps r95 truthful; without it r95 is over-confident."""
    truth = _true_lens(0.0, 0.0)
    profile = pinhole_intrinsics(W, H, f=F_NOM)
    with_term = _landmark_only_share(profile, truth, 4.0, seed=8)
    assert with_term >= 0.93, with_term
    monkeypatch.setattr(locate_mod, "LANDMARK_SIGMA_FACTOR", 0.0)
    without = _landmark_only_share(profile, truth, 4.0, seed=8)
    assert without < with_term


def test_landmark_only_fov_nominal_r95_truthful():
    """Nominal FOV on a real lens at the prior, 6 landmarks with 2 px clicks, no audit."""
    share = _landmark_only_share(NOMINAL, _true_lens(0.02, -0.03), 2.0, seed=9)
    assert share >= 0.93, share
