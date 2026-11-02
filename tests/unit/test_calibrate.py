"""Spatial: synthetic camera (spec 12.1) — FR-036, FR-037, NFR-024."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from vigil.models import Calibration, Extrinsics, Intrinsics
from vigil.spatial.calibrate import (
    MarkerPair,
    calibrate_extrinsics,
    calibrate_from_points,
    calibrate_intrinsics,
    fov_intrinsics,
    load_calibrations,
    save_calibrations,
)
from vigil.spatial.geometry import (
    CameraGeom,
    look_at_extrinsics,
    pinhole_intrinsics,
    rotation_angle_deg,
    undistort_normalized,
)

W, H = 1280, 720


def _true_camera() -> tuple[Intrinsics, Extrinsics]:
    k = pinhole_intrinsics(W, H, f=900.0)
    ext = look_at_extrinsics((1.0, 3.0, -1.0), (2.0, 0.0, 7.0))
    return k, ext


def _markers() -> np.ndarray:
    """8 ground markers on a gentle slope (y = 0.04 z), 3 to 12 m from the camera."""
    xz = np.array(
        [[-1.5, 3.0], [3.5, 3.5], [0.0, 5.5], [4.5, 6.5], [-2.0, 8.0], [2.5, 9.5],
         [5.5, 11.0], [-0.5, 12.0]]
    )  # fmt: skip
    return np.column_stack([xz[:, 0], 0.04 * xz[:, 1], xz[:, 1]])


def _pairs(noise_px: float, seed: int = 7) -> list[MarkerPair]:
    k, ext = _true_camera()
    geom = CameraGeom.from_calibration(Calibration(camera_id="c", intrinsics=k, extrinsics=ext))
    pts = _markers()
    uv, front = geom.project(pts)
    assert front.all()
    rng = np.random.default_rng(seed)
    uv = uv + rng.normal(0.0, noise_px, uv.shape)
    return [
        MarkerPair(u=float(u), v=float(v), x=float(p[0]), y=float(p[1]), z=float(p[2]), id=f"m{i}")
        for i, ((u, v), p) in enumerate(zip(uv, pts, strict=True))
    ]


def _pose_errors(est: Extrinsics, true: Extrinsics) -> tuple[float, float]:
    r_e, _ = cv2.Rodrigues(np.asarray(est.rvec))
    r_t, _ = cv2.Rodrigues(np.asarray(true.rvec))
    c_e = -r_e.T @ np.asarray(est.tvec)
    c_t = -r_t.T @ np.asarray(true.tvec)
    return float(np.linalg.norm(c_e - c_t)), rotation_angle_deg(r_e, r_t)


# ---------------------------------------------------------------------------
# Extrinsics (FR-037)
# ---------------------------------------------------------------------------


def test_pnp_recovers_pose_within_2cm_and_half_degree():
    k, true_ext = _true_camera()
    est = calibrate_extrinsics(_pairs(noise_px=0.3), k)
    pos_err, ang_err = _pose_errors(est, true_ext)
    assert est.method == "pnp_ransac"
    assert pos_err < 0.02, pos_err
    assert ang_err < 0.5, ang_err
    assert est.reproj_mean_px is not None
    assert est.reproj_mean_px < 4.0
    assert est.heldout_ground_m is not None
    assert est.heldout_ground_m < 0.25


def test_pnp_holds_out_two_markers_and_reports_heldout_error():
    k, _ = _true_camera()
    pairs = _pairs(noise_px=0.0)
    # Corrupt the two held-out markers' world positions by 1 m: the fit is unaffected,
    # but the held-out ground error must expose them.
    pairs[-1] = pairs[-1].model_copy(update={"x": pairs[-1].x + 1.0})
    pairs[-2] = pairs[-2].model_copy(update={"z": pairs[-2].z + 1.0})
    est = calibrate_extrinsics(pairs, k)
    assert est.reproj_mean_px < 0.5
    assert est.heldout_ground_m > 0.8


def test_pnp_accepts_tuples_and_rejects_too_few_points():
    k, _ = _true_camera()
    tuples = [(p.u, p.v, p.x, p.y, p.z) for p in _pairs(0.0)]
    est = calibrate_extrinsics(tuples, k)
    assert est.reproj_mean_px < 0.1
    with pytest.raises(ValueError, match="at least 4"):
        calibrate_extrinsics(tuples[:3], k)


def test_pnp_with_distorted_lens():
    k = pinhole_intrinsics(W, H, f=900.0, dist=[-0.12, 0.03, 0.0, 0.0, 0.0])
    _, true_ext = _true_camera()
    geom = CameraGeom.from_calibration(
        Calibration(camera_id="c", intrinsics=k, extrinsics=true_ext)
    )
    pts = _markers()
    uv, _ = geom.project(pts)
    pairs = [
        MarkerPair(u=a, v=b, x=p[0], y=p[1], z=p[2]) for (a, b), p in zip(uv, pts, strict=True)
    ]
    est = calibrate_extrinsics(pairs, k)
    pos_err, ang_err = _pose_errors(est, true_ext)
    assert pos_err < 0.01
    assert ang_err < 0.1


def test_homography_fallback_from_four_flat_markers():
    k, _ = _true_camera()
    true_ext = look_at_extrinsics((0.5, 2.8, -0.5), (1.5, 0.0, 7.0))
    geom = CameraGeom.from_calibration(
        Calibration(camera_id="c", intrinsics=k, extrinsics=true_ext)
    )
    pts = _markers()
    pts[:, 1] = 0.0  # flat ground
    uv, _ = geom.project(pts)
    pairs = [
        MarkerPair(u=a, v=b, x=p[0], y=p[1], z=p[2]) for (a, b), p in zip(uv, pts, strict=True)
    ]
    est = calibrate_extrinsics(pairs[:6], k, method="homography")
    assert est.method == "homography"
    pos_err, ang_err = _pose_errors(est, true_ext)
    assert pos_err < 0.02
    assert ang_err < 0.5
    assert est.heldout_ground_m is not None
    assert est.heldout_ground_m < 0.05


# ---------------------------------------------------------------------------
# Distortion model round trip (FR-036)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "dist"),
    [("pinhole", [-0.25, 0.08, 0.001, -0.0005, -0.01]), ("fisheye", [0.05, -0.01, 0.002, -0.0005])],
)
def test_distortion_model_round_trips(model, dist):
    k = np.array([[700.0, 0, 640.0], [0, 700.0, 360.0], [0, 0, 1]])
    rng = np.random.default_rng(1)
    norm = rng.uniform(-0.6, 0.6, (200, 2))
    obj = np.column_stack([norm, np.ones(len(norm))]).reshape(-1, 1, 3)
    zero = np.zeros((3, 1))
    if model == "fisheye":
        uv, _ = cv2.fisheye.projectPoints(obj, zero, zero, k, np.asarray(dist))
    else:
        uv, _ = cv2.projectPoints(obj, zero, zero, k, np.asarray(dist))
    back = undistort_normalized(k, np.asarray(dist), model, uv.reshape(-1, 2))
    assert np.abs(back - norm).max() < 1e-5


# ---------------------------------------------------------------------------
# Intrinsics (FR-036)
# ---------------------------------------------------------------------------

PATTERN = (9, 6)
SQUARE = 0.03


def _render_board_views(tmp_path, k: np.ndarray, size=(640, 480), n_views=10):
    """Render a 10x7-square checkerboard through known poses (no lens distortion)."""
    cols, rows = PATTERN[0] + 1, PATTERN[1] + 1
    ppsq = 24
    margin = ppsq
    tex = np.full((rows * ppsq + 2 * margin, cols * ppsq + 2 * margin), 255, np.uint8)
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                y0, x0 = margin + r * ppsq, margin + c * ppsq
                tex[y0 : y0 + ppsq, x0 : x0 + ppsq] = 0
    s = ppsq / SQUARE
    a = np.array([[s, 0, margin], [0, s, margin], [0, 0, 1.0]])
    rng = np.random.default_rng(3)
    paths = []
    centre = np.array([cols * SQUARE / 2, rows * SQUARE / 2, 0.0])
    for i in range(n_views):
        rx, ry, rz = np.radians(rng.uniform(-25, 25, 3) * [1, 1, 0.4])
        r, _ = cv2.Rodrigues(np.array([rx, ry, rz]))
        dist = rng.uniform(0.45, 0.6)
        offset = np.array([rng.uniform(-0.05, 0.05), rng.uniform(-0.04, 0.04), dist])
        t = offset - r @ centre
        h = k @ np.column_stack([r[:, 0], r[:, 1], t]) @ np.linalg.inv(a)
        img = cv2.warpPerspective(
            tex, h, size, flags=cv2.INTER_AREA, borderMode=cv2.BORDER_CONSTANT, borderValue=128
        )
        p = tmp_path / f"board_{i:02d}.png"
        cv2.imwrite(str(p), img)
        paths.append(p)
    return paths


def test_intrinsics_from_synthetic_checkerboard_rms_under_1px(tmp_path):
    k = np.array([[520.0, 0, 322.0], [0, 520.0, 238.0], [0, 0, 1]])
    paths = _render_board_views(tmp_path, k)
    intr = calibrate_intrinsics(paths, fisheye=False, pattern=PATTERN, square_m=SQUARE)
    assert not intr.fov_fallback
    assert intr.rms_px is not None
    assert intr.rms_px < 1.0
    assert (intr.width, intr.height) == (640, 480)
    est = np.asarray(intr.k)
    assert abs(est[0, 0] - 520.0) / 520.0 < 0.03
    assert abs(est[0, 2] - 322.0) < 10
    assert abs(est[1, 2] - 238.0) < 10


def test_intrinsics_detection_failure_uses_fov_fallback(tmp_path):
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((480, 640), 128, np.uint8))
    intr = calibrate_intrinsics([blank, blank, blank], hfov_deg=90.0)
    assert intr.fov_fallback
    assert intr.dist == []
    assert intr.k[0][0] == pytest.approx(320.0)  # (w/2) / tan(45 deg)
    assert (intr.width, intr.height) == (640, 480)


def test_fov_intrinsics_focal_from_horizontal_fov():
    intr = fov_intrinsics(1280, 720, hfov_deg=100.0)
    assert intr.fov_fallback
    assert intr.model == "pinhole"
    assert intr.k[0][0] == pytest.approx(640.0 / np.tan(np.radians(50.0)))
    assert intr.k[0][2] == 640.0
    assert intr.k[1][2] == 360.0


def _synthetic_point_views(k, dist, model, n_views=12, seed=5):
    rng = np.random.default_rng(seed)
    grid = np.array([[i * SQUARE, j * SQUARE, 0.0] for j in range(6) for i in range(9)])
    obj, img = [], []
    centre = grid.mean(axis=0)
    for _ in range(n_views):
        r, _ = cv2.Rodrigues(np.radians(rng.uniform(-30, 30, 3) * [1, 1, 0.3]))
        t = np.array([rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), rng.uniform(0.3, 0.45)])
        t = t - r @ centre
        rvec, _ = cv2.Rodrigues(r)
        if model == "fisheye":
            uv, _ = cv2.fisheye.projectPoints(grid.reshape(-1, 1, 3), rvec, t, k, dist)
        else:
            uv, _ = cv2.projectPoints(grid, rvec, t, k, dist)
        uv = uv.reshape(-1, 2) + rng.normal(0, 0.1, (len(grid), 2))
        obj.append(grid.copy())
        img.append(uv)
    return obj, img


@pytest.mark.parametrize("model", ["pinhole", "fisheye"])
def test_calibrate_from_points_recovers_model(model):
    k = np.array([[600.0, 0, 640.0], [0, 600.0, 360.0], [0, 0, 1]])
    if model == "fisheye":
        dist = np.array([0.04, -0.01, 0.003, -0.001])
    else:
        dist = np.array([-0.2, 0.05, 0.0, 0.0, 0.0])
    obj, img = _synthetic_point_views(k, dist, model)
    intr = calibrate_from_points(obj, img, (1280, 720), fisheye=(model == "fisheye"))
    assert intr.model == model
    assert intr.rms_px < 1.0
    assert not intr.fov_fallback
    assert abs(intr.k[0][0] - 600.0) < 6.0
    expected_len = 4 if model == "fisheye" else 5
    assert len(intr.dist) == expected_len


def test_intrinsics_high_rms_falls_back_and_keeps_rms():
    k = np.array([[600.0, 0, 640.0], [0, 600.0, 360.0], [0, 0, 1]])
    obj, img = _synthetic_point_views(k, np.zeros(5), "pinhole")
    rng = np.random.default_rng(0)
    img = [uv + rng.normal(0, 4.0, uv.shape) for uv in img]  # far too noisy
    intr = calibrate_from_points(obj, img, (1280, 720), fisheye=False, hfov_deg=95.0)
    assert intr.fov_fallback
    assert intr.rms_px is not None
    assert intr.rms_px >= 1.0
    assert intr.k[0][0] == pytest.approx(640.0 / np.tan(np.radians(47.5)))


# ---------------------------------------------------------------------------
# calibration.json
# ---------------------------------------------------------------------------


def test_calibration_json_round_trip(tmp_path):
    k, ext = _true_camera()
    cals = [
        Calibration(camera_id="front", intrinsics=k, extrinsics=ext, date="2026-11-02"),
        Calibration(
            camera_id="backyard", intrinsics=fov_intrinsics(1280, 720, 100.0), extrinsics=ext
        ),
    ]
    path = tmp_path / "calibration.json"
    save_calibrations(path, cals)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert raw[0]["camera_id"] == "front"
    back = load_calibrations(path)
    assert back == cals
    # A {"cameras": [...]} wrapper is accepted too.
    path.write_text(json.dumps({"cameras": raw}), encoding="utf-8")
    assert load_calibrations(path) == cals
