"""Spatial: locate (spec 12.1) — FR-039 on a synthetic slope."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from vigil.models import Box, Calibration, Gap, Position, TrackFrame
from vigil.spatial.calibrate import intrinsics_from_fov
from vigil.spatial.geometry import (
    CameraGeom,
    RaycastScene,
    grid_ground,
    look_at_extrinsics,
    pinhole_intrinsics,
    rle_decode,
    rle_encode,
)
from vigil.spatial.locate import (
    filter_gaps,
    foot_point,
    fuse,
    locate,
    radial_sigma_px,
    smooth,
)

W, H = 1280, 720


def slope(x, z):
    return 0.08 * z + 0.03 * x


@pytest.fixture(scope="module")
def scene() -> RaycastScene:
    return RaycastScene(ground=grid_ground(-12, -2, 12, 24, slope, step=1.0))


def make_cal(heldout: float = 0.0, dist=(-0.08, 0.01, 0.0, 0.0, 0.0)) -> Calibration:
    intr = pinhole_intrinsics(W, H, f=900.0, dist=list(dist))
    ext = look_at_extrinsics((0.0, 3.5, -1.0), (0.0, 0.5, 8.0))
    ext.heldout_ground_m = heldout
    return Calibration(camera_id="side_left", intrinsics=intr, extrinsics=ext)


def ground_point(x: float, z: float) -> np.ndarray:
    return np.array([x, slope(x, z), z])


def project(cal: Calibration, pts) -> np.ndarray:
    uv, front = CameraGeom.from_calibration(cal).project(np.asarray(pts, float))
    assert front.all()
    return uv


def billboard_mask(cal: Calibration, p: np.ndarray, width_m=0.4, height_m=1.7) -> np.ndarray:
    """A flat person-sized rectangle standing at p, facing the camera, rendered as a mask."""
    geom = CameraGeom.from_calibration(cal)
    to_cam = geom.center - p
    right = np.cross([0.0, 1.0, 0.0], to_cam)
    right[1] = 0.0
    right /= np.linalg.norm(right)
    up = np.array([0.0, 1.0, 0.0])
    corners = [
        p - right * width_m / 2,
        p + right * width_m / 2,
        p + right * width_m / 2 + up * height_m,
        p - right * width_m / 2 + up * height_m,
    ]
    uv = project(cal, corners)
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [np.round(uv).astype(np.int32)], 1)
    return mask.astype(bool)


def frame_from_mask(mask: np.ndarray, t: float = 3.0, clipped: bool = False) -> TrackFrame:
    ys, xs = np.nonzero(mask)
    box = Box(x1=float(xs.min()), y1=float(ys.min()), x2=float(xs.max()), y2=float(ys.max()))
    return TrackFrame(t=t, box=box, mask_rle=rle_encode(mask), clipped=clipped)


# ---------------------------------------------------------------------------
# Foot point and ray cast
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("x", "z"), [(0.0, 5.0), (-2.5, 8.0), (3.0, 11.0), (1.0, 3.5)])
def test_footpoint_ray_hits_known_point_on_slope(scene, x, z):
    cal = make_cal()
    p = ground_point(x, z)
    (u, v) = project(cal, [p])[0]
    frame = TrackFrame(t=12.5, box=Box(x1=u - 25, y1=v - 220, x2=u + 25, y2=v))
    pos = locate(frame, cal, scene, np.random.default_rng(0), track_id="t1")
    assert pos is not None
    assert pos.method == "footpoint"
    assert pos.track_id == "t1"
    assert pos.t == 12.5
    assert pos.cameras == ["side_left"]
    assert np.linalg.norm(np.array([pos.x, pos.y, pos.z]) - p) < 0.02
    assert pos.y == pytest.approx(slope(pos.x, pos.z), abs=0.02)
    assert 0.0 < pos.r95 < 1.5
    assert "low_confidence" not in pos.flags


def test_footpoint_from_sam_mask_rle(scene):
    cal = make_cal()
    p = ground_point(1.0, 7.0)
    frame = frame_from_mask(billboard_mask(cal, p))
    pos = locate(frame, cal, scene, np.random.default_rng(1))
    assert pos is not None
    assert pos.method == "footpoint"
    assert np.hypot(pos.x - p[0], pos.z - p[2]) < 0.25


def test_foot_point_is_median_x_and_max_y_of_lowest_5_percent():
    mask = np.zeros((100, 200), bool)
    mask[10:60, 50:70] = True  # body
    mask[60:80, 90:100] = True  # a lower leg on the right, lowest 200 px
    fp = foot_point(
        TrackFrame(t=0, box=Box(x1=50, y1=10, x2=100, y2=80), mask_rle=rle_encode(mask)), 200, 100
    )
    assert fp.from_mask
    assert fp.foot[1] == 79
    assert 90 <= fp.foot[0] <= 99
    assert fp.top[1] == 10
    assert not fp.clipped


def test_foot_point_falls_back_to_box_bottom_centre():
    fp = foot_point(TrackFrame(t=0, box=Box(x1=100, y1=50, x2=140, y2=300)), W, H)
    assert not fp.from_mask
    assert fp.foot == (120.0, 300.0)
    assert fp.top == (120.0, 50.0)


def test_rle_round_trip_and_size_check():
    rng = np.random.default_rng(4)
    mask = rng.random((37, 53)) > 0.6
    s = rle_encode(mask)
    assert np.array_equal(rle_decode(s, 37, 53), mask)
    assert np.array_equal(rle_decode(rle_encode(np.ones((4, 5), bool)), 4, 5), np.ones((4, 5)))
    with pytest.raises(ValueError):
        rle_decode(s, 37, 54)


def test_bad_rle_falls_back_to_box(scene):
    cal = make_cal()
    p = ground_point(0.5, 6.0)
    (u, v) = project(cal, [p])[0]
    frame = TrackFrame(t=1.0, box=Box(x1=u - 20, y1=v - 200, x2=u + 20, y2=v), mask_rle="0123")
    pos = locate(frame, cal, scene, np.random.default_rng(0))
    assert pos is not None
    assert np.hypot(pos.x - p[0], pos.z - p[2]) < 0.05


def test_ray_above_horizon_returns_none(scene):
    cal = make_cal()
    frame = TrackFrame(t=1.0, box=Box(x1=600, y1=0, x2=640, y2=5))
    assert locate(frame, cal, scene, np.random.default_rng(0)) is None


# ---------------------------------------------------------------------------
# Occlusion: height prior (FR-039 step 3)
# ---------------------------------------------------------------------------


def test_clipped_mask_uses_height_prior_and_is_flagged(scene):
    cal = make_cal()
    p = ground_point(0.8, 2.2)  # close: feet fall below the image bottom
    full = billboard_mask(cal, p)
    head_uv = project(cal, [p + np.array([0.0, 1.7, 0.0])])[0]
    foot_uv = project(cal, [p])[0]
    assert foot_uv[1] > H, "test setup: feet must be outside the image"
    assert full[-1].any(), "mask must touch the bottom edge"
    frame = frame_from_mask(full)
    pos = locate(frame, cal, scene, np.random.default_rng(2))
    assert pos is not None
    assert pos.method == "height_prior"
    assert "low_confidence" in pos.flags
    assert np.hypot(pos.x - p[0], pos.z - p[2]) < 0.3
    assert pos.r95 > 0.05
    assert head_uv[1] >= 0


def test_explicitly_clipped_box_uses_height_prior(scene):
    cal = make_cal()
    p = ground_point(-1.0, 9.0)
    head = project(cal, [p + np.array([0.0, 1.7, 0.0])])[0]
    frame = TrackFrame(
        t=4.0, box=Box(x1=head[0] - 20, y1=head[1], x2=head[0] + 20, y2=head[1] + 80), clipped=True
    )
    pos = locate(frame, cal, scene, np.random.default_rng(0))
    assert pos is not None
    assert pos.method == "height_prior"
    assert "low_confidence" in pos.flags
    assert np.hypot(pos.x - p[0], pos.z - p[2]) < 0.05


# ---------------------------------------------------------------------------
# Uncertainty
# ---------------------------------------------------------------------------


def test_r95_grows_with_heldout_calibration_error(scene):
    p = ground_point(0.0, 8.0)
    a, b = make_cal(0.0), make_cal(0.3)
    (u, v) = project(a, [p])[0]
    frame = TrackFrame(t=0, box=Box(x1=u - 20, y1=v - 200, x2=u + 20, y2=v))
    pa = locate(frame, a, scene, np.random.default_rng(0))
    pb = locate(frame, b, scene, np.random.default_rng(0))
    assert pb.r95 > pa.r95 + 0.3


def test_r95_grows_with_distance(scene):
    cal = make_cal()
    rs = []
    for z in (4.0, 8.0, 14.0):
        (u, v) = project(cal, [ground_point(0.0, z)])[0]
        frame = TrackFrame(t=0, box=Box(x1=u - 20, y1=v - 200, x2=u + 20, y2=v))
        rs.append(locate(frame, cal, scene, np.random.default_rng(0)).r95)
    assert rs[0] < rs[1] < rs[2]


def test_locate_is_deterministic_for_a_seed(scene):
    cal = make_cal()
    (u, v) = project(cal, [ground_point(0.0, 6.0)])[0]
    frame = TrackFrame(t=0, box=Box(x1=u - 20, y1=v - 200, x2=u + 20, y2=v))
    a = locate(frame, cal, scene, np.random.default_rng(9))
    b = locate(frame, cal, scene, np.random.default_rng(9))
    assert a == b


# ---------------------------------------------------------------------------
# Gaps, smoothing, fusion
# ---------------------------------------------------------------------------


def pos(t, x=0.0, z=5.0, r95=0.4, cams=("side_left",), track="t1", method="footpoint", flags=()):
    return Position(
        track_id=track, t=t, x=x, y=0.0, z=z, r95=r95, method=method, cameras=list(cams),
        flags=list(flags),
    )  # fmt: skip


def test_no_positions_inside_gaps():
    gaps = [Gap(id="g4", visit_id="v1", kind="blind_spot", t0=10.0, t1=51.0)]
    ps = [pos(t) for t in (9.0, 10.0, 10.5, 30.0, 50.9, 51.0, 52.0)]
    kept = filter_gaps(ps, gaps)
    assert [p.t for p in kept] == [9.0, 10.0, 51.0, 52.0]


def test_smoothing_2hz_median_removes_outlier():
    ps = [pos(10.0 + i * 0.1, x=1.0 + 0.01 * i) for i in range(21)]
    ps[7] = pos(10.7, x=9.0)  # a one-frame outlier
    out = smooth(ps)
    ts = [p.t for p in out]
    assert ts == [10.0, 10.5, 11.0, 11.5, 12.0]
    assert all(abs(p.x - 1.1) < 0.2 for p in out)


def test_smoothing_never_interpolates_across_a_gap():
    gaps = [Gap(id="g1", visit_id="v1", kind="blind_spot", t0=12.0, t1=53.0)]
    ps = [pos(10.0 + i * 0.1) for i in range(21)] + [pos(53.0 + i * 0.1, x=5.0) for i in range(11)]
    out = smooth(ps, gaps=gaps)
    assert out
    assert not any(12.0 < p.t < 53.0 for p in out)
    # The two sides are smoothed separately: no mixed x values.
    assert all(p.x in (0.0, 5.0) for p in out)


def test_smoothing_keeps_tracks_separate():
    ps = [pos(i * 0.1, x=0.0, track="a") for i in range(11)]
    ps += [pos(i * 0.1, x=3.0, track="b") for i in range(11)]
    out = smooth(ps)
    assert {p.track_id for p in out} == {"a", "b"}
    assert all((p.x == 0.0) == (p.track_id == "a") for p in out)


def test_fusion_inverse_variance_weighted():
    a = pos(5.0, x=0.0, z=5.0, r95=0.8, cams=("side_left",))
    b = pos(5.0, x=0.4, z=5.0, r95=0.4, cams=("backyard",))
    out = fuse([a, b])
    assert len(out) == 1
    f = out[0]
    assert f.method == "fused"
    assert sorted(f.cameras) == ["backyard", "side_left"]
    assert f.x == pytest.approx(0.32)  # weights 1/0.64 and 1/0.16
    assert f.r95 < 0.4
    assert "inconsistent" not in f.flags


def test_fusion_more_than_1m_apart_keeps_both_flagged_inconsistent():
    a = pos(5.0, x=0.0, cams=("side_left",))
    b = pos(5.0, x=1.5, cams=("backyard",))
    out = fuse([a, b])
    assert len(out) == 2
    assert all("inconsistent" in p.flags for p in out)
    assert {p.method for p in out} == {"footpoint"}


# ---------------------------------------------------------------------------
# r95 calibration terms (spec 7 step 4, revised Nov 2)
# ---------------------------------------------------------------------------


def _cal_with(heldout=None, reproj=None, nominal=False) -> Calibration:
    if nominal:
        intr = intrinsics_from_fov(2 * np.degrees(np.arctan(640.0 / 900.0)), W, H)
    else:
        intr = pinhole_intrinsics(W, H, f=900.0)
    ext = look_at_extrinsics((0.0, 3.5, -1.0), (0.0, 0.5, 8.0))
    ext.heldout_ground_m = heldout
    ext.reproj_mean_px = reproj
    return Calibration(camera_id="side_left", intrinsics=intr, extrinsics=ext)


def _r95_at(scene, cal, x, z) -> float:
    (u, v) = project(cal, [ground_point(x, z)])[0]
    frame = TrackFrame(t=0, box=Box(x1=u - 20, y1=v - 200, x2=u + 20, y2=v))
    return locate(frame, cal, scene, np.random.default_rng(0)).r95


def test_r95_uses_landmark_error_when_no_audit_was_measured(scene):
    plain = _r95_at(scene, _cal_with(), 0.0, 8.0)
    landmark = _r95_at(scene, _cal_with(reproj=5.0), 0.0, 8.0)
    assert landmark > plain * 1.3


def test_r95_uses_audit_error_where_measured_instead_of_landmark_error(scene):
    audited = _r95_at(scene, _cal_with(heldout=0.1, reproj=5.0), 0.0, 8.0)
    audit_only = _r95_at(scene, _cal_with(heldout=0.1), 0.0, 8.0)
    assert audited == pytest.approx(audit_only)
    assert audited > _r95_at(scene, _cal_with(), 0.0, 8.0)


def test_fov_nominal_adds_a_radial_term_that_grows_toward_the_edge(scene):
    profile, nominal = _cal_with(), _cal_with(nominal=True)
    assert nominal.intrinsics.k[0][0] == pytest.approx(900.0)
    # Near the principal point the radial term is negligible ...
    centre_p = _r95_at(scene, profile, 0.0, 8.0)
    centre_n = _r95_at(scene, nominal, 0.0, 8.0)
    assert centre_n == pytest.approx(centre_p, rel=0.1)
    # ... toward the image edge it widens r95 clearly.
    edge_p = _r95_at(scene, profile, 6.0, 9.0)
    edge_n = _r95_at(scene, nominal, 6.0, 9.0)
    assert edge_n > edge_p * 1.3


def test_radial_sigma_is_zero_for_a_lens_profile_and_grows_with_radius():
    nominal = CameraGeom.from_calibration(_cal_with(nominal=True))
    profile = CameraGeom.from_calibration(_cal_with())
    uv = np.array([[640.0, 360.0], [840.0, 360.0], [1240.0, 360.0]])
    assert np.all(radial_sigma_px(profile, uv) == 0.0)
    s = radial_sigma_px(nominal, uv)
    assert s[0] == pytest.approx(0.0, abs=1e-9)
    assert 0.0 < s[1] < s[2]
