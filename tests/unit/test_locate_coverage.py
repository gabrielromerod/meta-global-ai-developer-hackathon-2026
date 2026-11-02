"""Property: uncertainty (spec 12.1) — FR-039, NFR-026.

On synthetic noise the true point must be inside the stated 95% radius at least 93% of the
time. The observation is the true foot pixel plus 3 px Gaussian noise (the noise model
``locate`` assumes); calibration error is simulated with a perturbed camera whose held-out
ground error is reported to ``locate``.
"""

from __future__ import annotations

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vigil.models import Box, Calibration, TrackFrame
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
