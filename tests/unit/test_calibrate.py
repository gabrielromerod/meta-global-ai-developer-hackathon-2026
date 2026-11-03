"""Spatial: synthetic camera (spec 12.1) — FR-036, FR-037, NFR-024."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from vigil.models import Calibration, Extrinsics, Intrinsics
from vigil.spatial.calibrate import (
    MarkerPair,
    SurveyedMarker,
    audit_error,
    calibrate_extrinsics,
    calibrate_from_points,
    calibrate_intrinsics,
    calibration_report,
    fov_intrinsics,
    intrinsics_from_fov,
    landmark_threshold_px,
    load_calibrations,
    save_calibrations,
    solve_landmarks,
    with_audit,
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
    # Since the Nov 2 revision every landmark is used by default (FR-037); the 2-point
    # hold-out is now asked for explicitly.
    est = calibrate_extrinsics(pairs[:6], k, method="homography", holdout=2)
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
    assert intr.source == "fov_nominal"
    assert intr.dist == []
    assert intr.k[0][0] == pytest.approx(320.0)  # (w/2) / tan(45 deg)
    assert (intr.width, intr.height) == (640, 480)


def test_fov_intrinsics_focal_from_horizontal_fov():
    intr = fov_intrinsics(1280, 720, hfov_deg=100.0)
    assert intr.fov_fallback
    assert intr.source == "fov_nominal"
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
    assert intr.source == "lens_profile"
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


# ---------------------------------------------------------------------------
# Product path (FR-036, FR-037 revised Nov 2): nominal FOV + 6 SAM landmarks
# ---------------------------------------------------------------------------

HFOV = 100.0


def _landmarks() -> np.ndarray:
    """6 fixed landmarks (door-frame corners, gate-post tops and bases, a shed corner)."""
    return np.array(
        [[-1.5, 2.1, 4.0], [3.5, 0.0, 4.5], [0.0, 1.0, 6.5], [4.5, 2.2, 7.5],
         [-2.0, 0.0, 9.0], [2.5, 1.5, 10.5]]
    )  # fmt: skip


def _audit_points() -> np.ndarray:
    """6 surveyed ground markers, separate from the landmarks (benchmark only)."""
    xz = np.array([[-1.0, 3.5], [2.0, 4.0], [0.5, 6.0], [3.0, 8.0], [-1.5, 10.0], [1.5, 12.0]])
    return np.column_stack([xz[:, 0], 0.04 * xz[:, 1], xz[:, 1]])


def _nominal_camera() -> tuple[Intrinsics, Extrinsics]:
    return intrinsics_from_fov(HFOV, W, H), look_at_extrinsics((1.0, 3.0, -1.0), (2.0, 0.0, 7.0))


def _pairs_for(k: Intrinsics, ext: Extrinsics, pts: np.ndarray, noise_px=0.0, seed=7, tag="l"):
    geom = CameraGeom.from_calibration(Calibration(camera_id="c", intrinsics=k, extrinsics=ext))
    uv, front = geom.project(pts)
    assert front.all()
    uv = uv + np.random.default_rng(seed).normal(0.0, noise_px, uv.shape)
    return [
        MarkerPair(u=float(u), v=float(v), x=float(p[0]), y=float(p[1]), z=float(p[2]),
                   id=f"{tag}{i}")
        for i, ((u, v), p) in enumerate(zip(uv, pts, strict=True))
    ]  # fmt: skip


def test_intrinsics_from_fov_is_nominal_and_flagged():
    intr = intrinsics_from_fov(HFOV, 1280, 720)
    assert intr.source == "fov_nominal"
    assert intr.fov_fallback
    assert intr.model == "pinhole"
    assert intr.dist == []
    assert intr.rms_px is None
    assert intr.k[0][0] == pytest.approx(640.0 / np.tan(np.radians(HFOV / 2)))
    assert intr.k[1][1] == intr.k[0][0]
    assert (intr.k[0][2], intr.k[1][2]) == (640.0, 360.0)
    assert (intr.width, intr.height) == (1280, 720)
    for bad in (0.0, 180.0, -5.0):
        with pytest.raises(ValueError):
            intrinsics_from_fov(bad, 1280, 720)


def test_checkerboard_path_is_a_lens_profile(tmp_path):
    k = np.array([[520.0, 0, 322.0], [0, 520.0, 238.0], [0, 0, 1]])
    paths = _render_board_views(tmp_path, k)
    intr = calibrate_intrinsics(paths, pattern=PATTERN, square_m=SQUARE)
    assert intr.source == "lens_profile"
    assert intr.rms_px < 1.0


def test_landmark_threshold_by_source_scaled_to_1280():
    assert landmark_threshold_px(intrinsics_from_fov(90.0, 1280, 720)) == pytest.approx(6.0)
    assert landmark_threshold_px(pinhole_intrinsics(1280, 720, 900.0)) == pytest.approx(4.0)
    # Thresholds are stated at 1280 px width: a 640 px frame accepts half the pixels.
    assert landmark_threshold_px(intrinsics_from_fov(90.0, 640, 360)) == pytest.approx(3.0)


def test_pnp_on_six_landmarks_recovers_pose_within_2cm_and_half_degree():
    k, true_ext = _nominal_camera()
    pairs = _pairs_for(k, true_ext, _landmarks(), noise_px=0.3)
    est = calibrate_extrinsics(pairs, k)
    pos_err, ang_err = _pose_errors(est, true_ext)
    assert est.method == "pnp_ransac"
    assert pos_err < 0.02, pos_err
    assert ang_err < 0.5, ang_err
    assert est.reproj_mean_px < 6.0
    # Accuracy is not asserted from the 6 landmarks: no held-out error without the audit.
    assert est.heldout_ground_m is None


def test_solve_landmarks_accepts_under_threshold():
    k, true_ext = _nominal_camera()
    res = solve_landmarks(_pairs_for(k, true_ext, _landmarks(), noise_px=0.5), k)
    assert res.accepted
    assert res.threshold_px == pytest.approx(6.0)
    assert res.reproj_px_at_1280 < 6.0
    assert res.used == [f"l{i}" for i in range(6)]
    assert res.dropped == []


def test_gross_landmark_outlier_is_rejected_by_ransac():
    k, true_ext = _nominal_camera()
    pairs = _pairs_for(k, true_ext, _landmarks(), noise_px=0.3)
    pairs[2] = pairs[2].model_copy(update={"u": pairs[2].u + 60.0})  # mis-clicked landmark
    res = solve_landmarks(pairs, k)
    assert res.accepted
    assert res.dropped == ["l2"]
    pos_err, ang_err = _pose_errors(res.extrinsics, true_ext)
    assert pos_err < 0.05
    assert ang_err < 0.5


def test_landmark_over_threshold_drops_worst_point_and_retries():
    k = pinhole_intrinsics(W, H, f=640.0 / np.tan(np.radians(HFOV / 2)))  # lens profile: 4 px
    true_ext = _nominal_camera()[1]
    pairs = _pairs_for(k, true_ext, _landmarks(), noise_px=0.2)
    pairs[4] = pairs[4].model_copy(update={"u": pairs[4].u + 30.0, "v": pairs[4].v - 20.0})
    # A wide RANSAC gate keeps every point in the first solve, so the mean is over 4 px.
    first = solve_landmarks(pairs, k, ransac_px=200.0, max_drops=0)
    assert not first.accepted
    assert first.reproj_px_at_1280 > 4.0
    res = solve_landmarks(pairs, k, ransac_px=200.0)
    assert res.accepted
    assert res.dropped == ["l4"]
    assert len(res.used) == 5
    assert res.reproj_px_at_1280 < 4.0
    # calibrate_extrinsics runs the same retry and returns the accepted pose.
    ext = calibrate_extrinsics(pairs, k, ransac_px=200.0)
    assert ext.reproj_mean_px == pytest.approx(res.extrinsics.reproj_mean_px)


def test_landmark_solve_still_over_threshold_is_not_accepted():
    k, true_ext = _nominal_camera()
    pairs = _pairs_for(k, true_ext, _landmarks(), noise_px=12.0, seed=3)
    res = solve_landmarks(pairs, k, ransac_px=200.0)
    assert not res.accepted
    assert len(res.dropped) <= 1
    assert res.reproj_px_at_1280 >= 6.0


def test_pairs_accept_nested_pixel_world_tuples():
    k, true_ext = _nominal_camera()
    nested = [((p.u, p.v), (p.x, p.y, p.z)) for p in _pairs_for(k, true_ext, _landmarks())]
    est = calibrate_extrinsics(nested, k)
    assert est.reproj_mean_px < 0.1


# ---------------------------------------------------------------------------
# Audit harness (NFR-024, benchmark only)
# ---------------------------------------------------------------------------


def _calibrated_nominal() -> Calibration:
    k, true_ext = _nominal_camera()
    ext = calibrate_extrinsics(_pairs_for(k, true_ext, _landmarks(), noise_px=0.3), k)
    return Calibration(camera_id="side_left", intrinsics=k, extrinsics=ext)


def _audit_markers(noise_px: float = 0.0) -> list[SurveyedMarker]:
    k, true_ext = _nominal_camera()
    return [
        SurveyedMarker(**p.model_dump())
        for p in _pairs_for(k, true_ext, _audit_points(), noise_px=noise_px, tag="a")
    ]


def test_audit_error_reports_held_out_ground_error_per_camera():
    cal = _calibrated_nominal()
    rep = audit_error(cal, _audit_markers(noise_px=0.3))
    assert rep.camera_id == "side_left"
    assert rep.n_markers == 6
    assert [m.id for m in rep.markers] == [f"a{i}" for i in range(6)]
    assert rep.mean_ground_m < 0.05
    assert rep.max_ground_m >= rep.mean_ground_m
    assert rep.mean_reproj_px < 2.0
    assert rep.passed
    assert rep.target_m == pytest.approx(0.25)


def test_audit_error_exposes_a_bad_calibration():
    cal = _calibrated_nominal()
    markers = _audit_markers()
    markers[0] = markers[0].model_copy(update={"x": markers[0].x + 1.0})
    markers[3] = markers[3].model_copy(update={"z": markers[3].z + 1.0})
    rep = audit_error(cal, markers)
    assert rep.max_ground_m > 0.9
    assert rep.mean_ground_m > 0.3
    assert not rep.passed


def test_audit_markers_are_never_landmarks():
    cal = _calibrated_nominal()
    k, true_ext = _nominal_camera()
    landmarks = _pairs_for(k, true_ext, _landmarks())
    reused = [SurveyedMarker(**landmarks[0].model_dump()), *_audit_markers()[1:]]
    with pytest.raises(ValueError, match="never used"):
        audit_error(cal, reused, landmarks=landmarks)
    with pytest.raises(ValueError, match="at least 1"):
        audit_error(cal, [])


def test_with_audit_records_error_for_locate_and_report():
    cal = _calibrated_nominal()
    rep = audit_error(cal, _audit_markers(noise_px=0.3))
    audited = with_audit(cal, rep)
    assert audited.extrinsics.heldout_ground_m == pytest.approx(rep.mean_ground_m)
    assert cal.extrinsics.heldout_ground_m is None  # the input is not mutated
    report = calibration_report(audited)
    assert report["intrinsics_source"] == "fov_nominal"
    assert report["intrinsics_ok"] is True  # nominal FOV is always accepted, but flagged
    assert report["fov_fallback"] is True
    assert report["landmark_threshold_px"] == pytest.approx(6.0)
    assert report["reproj_ok"] is True
    assert report["audit_measured"] is True
    assert report["heldout_ground_m"] == pytest.approx(rep.mean_ground_m)
    assert report["heldout_ok"] is True


def test_calibration_report_without_audit_says_not_measured():
    report = calibration_report(_calibrated_nominal())
    assert report["audit_measured"] is False
    assert report["heldout_ground_m"] is None
    assert report["heldout_ok"] is False
