"""Camera calibration: product path and audit harness (FR-036, FR-037, NFR-024; spec 7).

Product path (every home):

* Intrinsics: **nominal lens FOV** is the primary path (``intrinsics_from_fov``): focal
  length from the datasheet's horizontal FOV at the processed resolution, principal point
  at the centre, no distortion, flagged ``source="fov_nominal"`` (and ``fov_fallback``).
  Optional lab refinement: one checkerboard session (about 20 views) **per camera model**,
  stored as a lens profile (``source="lens_profile"``) and reused for identical units;
  accepted when RMS is under 1.0 px, otherwise nominal FOV is used.
* Extrinsics: SAM 3.1 proposes fixed landmarks (``vigil.spatial.landmarks``); the
  installer accepts 6 and clicks each once on the mesh. PnP with RANSAC on the 6
  (``solve_landmarks``). Accepted when the mean landmark reprojection is under 6 px
  (nominal FOV) or 4 px (lens profile) at 1280 px; over it, the worst point is dropped and
  the pose re-solved once. A planar homography is the fallback when the mesh is unusable.

Audit harness (benchmark only): ``audit_error`` compares 6 surveyed ground markers per
camera, never used in the solve, with where the calibrated camera places them (held-out
ground error, target under 0.25 m). ``with_audit`` records it on the calibration so that
``locate()`` widens r95 with the measured error instead of the landmark error.

``config/calibration.json`` is a JSON list of ``vigil.models.Calibration``.

OpenCV API used (checked against the installed opencv-python-headless 5.0 docstrings, since
docs.opencv.org refused automated fetches): ``calibrateCamera``, ``fisheye.calibrate``,
``findChessboardCorners``, ``cornerSubPix``, ``solvePnPRansac``, ``solvePnP`` (``SQPNP``
initialises 4 or 5 non-coplanar points, where ``ITERATIVE`` needs 6), ``findHomography``,
``projectPoints`` and ``undistortPoints``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vigil.models import Calibration, Extrinsics, Intrinsics
from vigil.spatial.geometry import CameraGeom, RaycastScene, undistort_normalized

RMS_ACCEPT_PX = 1.0
"""FR-036: a lens profile is accepted below this RMS; otherwise nominal FOV is used."""
NOMINAL_ACCEPT_PX = 6.0
"""FR-037: mean landmark reprojection accepted below this at 1280 px (nominal FOV)."""
PROFILE_ACCEPT_PX = 4.0
"""FR-037: mean landmark reprojection accepted below this at 1280 px (lens profile)."""
REPROJ_ACCEPT_PX = PROFILE_ACCEPT_PX
"""Kept for callers of the earlier single threshold (lens profile)."""
REFERENCE_WIDTH_PX = 1280.0
"""Thresholds are stated at this frame width and scale with the processed width."""
AUDIT_TARGET_M = 0.25
"""NFR-024: audit-harness held-out ground error target."""
HELDOUT_ACCEPT_M = AUDIT_TARGET_M
DEFAULT_HFOV_DEG = 90.0
"""Used only when no lens field of view is given; pass the datasheet value."""
MIN_BOARD_VIEWS = 3
MIN_PNP_POINTS = 4
MAX_DROPS = 1
"""Drop-worst-point retries when the landmark reprojection is over the threshold (UC-10)."""
LEGACY_HOLDOUT_MIN_PAIRS = 8
"""The earlier 8-marker protocol (PnP on 6, 2 held out) applies only from 8 pairs up."""
SAME_POINT_M = 0.01


class MarkerPair(BaseModel):
    """One clicked point: pixel in the camera still and its world position on the mesh.

    This is the ``PixelPoint3D`` of spec 9.5 (module-local until promoted to vigil.models):
    a landmark pair in the product path.
    """

    model_config = ConfigDict(extra="forbid")

    u: float
    v: float
    x: float
    y: float
    z: float
    id: str | None = None


PixelPoint3D = MarkerPair
LandmarkPair = MarkerPair


class SurveyedMarker(MarkerPair):
    """An audit-harness marker: where it appears in the still and its tape-measured world
    position. Benchmark only; never passed to the extrinsic solve."""


PairLike = MarkerPair | Sequence[float] | Sequence[Sequence[float]]


# ---------------------------------------------------------------------------
# Intrinsics (FR-036)
# ---------------------------------------------------------------------------


def intrinsics_from_fov(
    hfov_deg: float, width: int, height: int, rms_px: float | None = None
) -> Intrinsics:
    """Nominal-FOV intrinsics (the primary path): pinhole focal length from the datasheet's
    horizontal FOV at ``width``, centred principal point, no distortion, flagged
    ``fov_nominal``. ``rms_px`` keeps a rejected lens-profile RMS for the report."""
    if not 0.0 < hfov_deg < 180.0:
        raise ValueError(f"horizontal field of view must be in (0, 180) degrees, got {hfov_deg}")
    if width <= 0 or height <= 0:
        raise ValueError(f"image size must be positive, got {width}x{height}")
    f = (width / 2.0) / float(np.tan(np.radians(hfov_deg) / 2.0))
    return Intrinsics(
        model="pinhole",
        k=[[f, 0.0, width / 2.0], [0.0, f, height / 2.0], [0.0, 0.0, 1.0]],
        dist=[],
        width=width,
        height=height,
        rms_px=rms_px,
        fov_fallback=True,
        source="fov_nominal",
    )


def fov_intrinsics(
    width: int, height: int, hfov_deg: float = DEFAULT_HFOV_DEG, rms_px: float | None = None
) -> Intrinsics:
    """``intrinsics_from_fov`` with the earlier argument order (width, height, hfov)."""
    return intrinsics_from_fov(hfov_deg, width, height, rms_px)


def is_nominal(k: Intrinsics) -> bool:
    """True when the intrinsics carry no measured lens model (nominal FOV)."""
    return k.source == "fov_nominal" or k.fov_fallback


def landmark_threshold_px(k: Intrinsics) -> float:
    """FR-037 acceptance threshold in this image's own pixels (6 or 4 px at 1280 px)."""
    base = NOMINAL_ACCEPT_PX if is_nominal(k) else PROFILE_ACCEPT_PX
    return base * k.width / REFERENCE_WIDTH_PX


def board_points(pattern: tuple[int, int], square_m: float) -> np.ndarray:
    """Inner-corner coordinates on the board plane, in OpenCV's detection order."""
    cols, rows = pattern
    grid = np.zeros((rows * cols, 3), np.float64)
    grid[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_m
    return grid


def _load_gray(frame: Path | str | np.ndarray) -> np.ndarray | None:
    if isinstance(frame, np.ndarray):
        img = frame
    else:
        img = cv2.imread(str(frame), cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def detect_board(gray: np.ndarray, pattern: tuple[int, int]) -> np.ndarray | None:
    """Sub-pixel inner corners (N, 2) or None when the board is not found."""
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    found, corners = cv2.findChessboardCorners(gray, pattern, flags=flags)
    if not found or corners is None:
        return None
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-3)
    corners = cv2.cornerSubPix(gray, corners.astype(np.float32), (5, 5), (-1, -1), crit)
    return corners.reshape(-1, 2).astype(np.float64)


def calibrate_intrinsics(
    frames: Sequence[Path | str | np.ndarray],
    fisheye: bool = False,
    *,
    pattern: tuple[int, int] = (9, 6),
    square_m: float = 0.025,
    hfov_deg: float = DEFAULT_HFOV_DEG,
    image_size: tuple[int, int] | None = None,
) -> Intrinsics:
    """Lens profile from checkerboard views (FR-036, optional, once per camera model).

    ``pattern`` is the inner-corner count (columns, rows). Accepted as
    ``source="lens_profile"`` when the RMS is under 1.0 px; otherwise (or with fewer than 3
    detected views) nominal FOV ``intrinsics_from_fov(hfov_deg)`` is returned, flagged.
    """
    size = image_size
    obj: list[np.ndarray] = []
    img: list[np.ndarray] = []
    template = board_points(pattern, square_m)
    for frame in frames:
        gray = _load_gray(frame)
        if gray is None:
            continue
        if size is None:
            size = (int(gray.shape[1]), int(gray.shape[0]))
        corners = detect_board(gray, pattern)
        if corners is not None:
            obj.append(template)
            img.append(corners)
    if size is None:
        raise ValueError("no readable calibration frames and no image_size given")
    if len(obj) < MIN_BOARD_VIEWS:
        return fov_intrinsics(size[0], size[1], hfov_deg)
    return calibrate_from_points(obj, img, size, fisheye=fisheye, hfov_deg=hfov_deg)


def _fisheye_flag(name: str) -> int:
    """OpenCV 4 exposes fisheye flags as cv2.fisheye.X; OpenCV 5 moved them to cv2.X."""
    value = getattr(cv2.fisheye, name, None)
    return int(value if value is not None else getattr(cv2, name))


def calibrate_from_points(
    obj_points: Sequence[np.ndarray],
    img_points: Sequence[np.ndarray],
    image_size: tuple[int, int],
    fisheye: bool = False,
    hfov_deg: float = DEFAULT_HFOV_DEG,
) -> Intrinsics:
    """Calibrate from known board/pixel correspondences (one array pair per view)."""
    w, h = image_size
    try:
        if fisheye:
            o = [np.asarray(p, np.float64).reshape(1, -1, 3) for p in obj_points]
            i = [np.asarray(p, np.float64).reshape(1, -1, 2) for p in img_points]
            flags = _fisheye_flag("CALIB_RECOMPUTE_EXTRINSIC") | _fisheye_flag("CALIB_FIX_SKEW")
            crit = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 100, 1e-9)
            rms, k, d, _, _ = cv2.fisheye.calibrate(
                o, i, (w, h), np.eye(3), np.zeros(4), flags=flags, criteria=crit
            )
            model = "fisheye"
        else:
            o = [np.asarray(p, np.float32).reshape(-1, 3) for p in obj_points]
            i = [np.asarray(p, np.float32).reshape(-1, 2) for p in img_points]
            rms, k, d, _, _ = cv2.calibrateCamera(o, i, (w, h), None, None)
            model = "pinhole"
    except cv2.error:
        return fov_intrinsics(w, h, hfov_deg)
    rms = float(rms)
    if not np.isfinite(rms) or rms >= RMS_ACCEPT_PX:
        return fov_intrinsics(w, h, hfov_deg, rms_px=rms if np.isfinite(rms) else None)
    return Intrinsics(
        model=model,
        k=np.asarray(k, float).tolist(),
        dist=[float(v) for v in np.asarray(d).ravel()],
        width=w,
        height=h,
        rms_px=rms,
        fov_fallback=False,
        source="lens_profile",
    )


# ---------------------------------------------------------------------------
# Extrinsics from landmarks (FR-037)
# ---------------------------------------------------------------------------


def _as_pair(p: PairLike) -> MarkerPair:
    """A pair from a MarkerPair, a dict, ``(u, v, x, y, z)`` or ``((u, v), (x, y, z))``."""
    if isinstance(p, MarkerPair):
        return p
    if isinstance(p, dict):
        return MarkerPair.model_validate(p)
    items = list(p)
    if len(items) == 2 and all(not isinstance(c, (int, float)) for c in items):
        flat = [float(c) for c in items[0]] + [float(c) for c in items[1]]
    else:
        flat = [float(c) for c in items]
    if len(flat) != 5:
        raise ValueError(f"a pair needs u, v, x, y, z; got {len(flat)} numbers")
    u, v, x, y, z = flat
    return MarkerPair(u=u, v=v, x=x, y=y, z=z)


def _pair_ids(pairs: Sequence[MarkerPair]) -> list[str]:
    return [p.id if p.id is not None else f"#{i}" for i, p in enumerate(pairs)]


def _split_holdout(n: int, holdout: int | Sequence[int] | None) -> tuple[list[int], list[int]]:
    """Indices to fit and to hold out. ``None``: every landmark is used (FR-037), except in
    the earlier 8-marker protocol (8 or more pairs), which holds the last 2 out."""
    if holdout is None:
        held = list(range(n - 2, n)) if n >= LEGACY_HOLDOUT_MIN_PAIRS else []
    elif isinstance(holdout, int):
        held = list(range(n - holdout, n)) if holdout > 0 else []
    else:
        held = sorted({int(i) % n for i in holdout})
    fit = [i for i in range(n) if i not in held]
    return fit, held


def _ideal_pixels(k: Intrinsics, uv: np.ndarray) -> np.ndarray:
    """Undistorted pixel coordinates (so PnP can run with zero distortion for both models)."""
    kk = np.asarray(k.k, float)
    n = undistort_normalized(kk, np.asarray(k.dist, float), k.model, uv)
    return (kk @ np.column_stack([n, np.ones(len(n))]).T).T[:, :2]


def _pose_from_homography(
    world: np.ndarray, ideal: np.ndarray, kk: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Pose from points on (approximately) one level plane y = y0."""
    y0 = float(world[:, 1].mean())
    plane = world[:, [0, 2]]
    norm = (np.linalg.inv(kk) @ np.column_stack([ideal, np.ones(len(ideal))]).T).T[:, :2]
    hmat, _ = cv2.findHomography(plane, norm, 0)
    if hmat is None:
        raise ValueError("homography failed: points may be collinear")
    h1, h2, h3 = hmat[:, 0], hmat[:, 1], hmat[:, 2]
    s = 2.0 / (np.linalg.norm(h1) + np.linalg.norm(h2))
    probe = plane[0, 0] * h1 + plane[0, 1] * h2 + h3
    if probe[2] * s < 0:
        s = -s
    r1, r3 = s * h1, s * h2
    r2 = np.cross(r3, r1)
    u, _, vt = np.linalg.svd(np.column_stack([r1, r2, r3]))
    r = u @ vt
    if np.linalg.det(r) < 0:
        r = u @ np.diag([1.0, 1.0, -1.0]) @ vt
    t = s * h3 - y0 * r[:, 1]
    rvec, _ = cv2.Rodrigues(r)
    return rvec.reshape(3, 1), t.reshape(3, 1)


_ZERO_DIST = np.zeros(5)


def _refine(
    world: np.ndarray, ideal: np.ndarray, kk: np.ndarray, rvec: np.ndarray, tvec: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    ok, r, t = cv2.solvePnP(
        world, ideal, kk, _ZERO_DIST, rvec.copy(), tvec.copy(), useExtrinsicGuess=True,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )  # fmt: skip
    return (r, t) if ok else (rvec, tvec)


def _pnp_plain(world: np.ndarray, ideal: np.ndarray, kk: np.ndarray):
    """PnP on every point: SQPNP initialises 4 or more points (planar or not), then
    Levenberg-Marquardt refines."""
    try:
        ok, r, t = cv2.solvePnP(world, ideal, kk, _ZERO_DIST, flags=cv2.SOLVEPNP_SQPNP)
    except cv2.error:
        ok = False
    if not ok:
        ok, r, t = cv2.solvePnP(world, ideal, kk, _ZERO_DIST, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise ValueError("PnP failed: check the landmark clicks")
    return _refine(world, ideal, kk, r, t)


def _initial_pose(
    world: np.ndarray, ideal: np.ndarray, kk: np.ndarray, method: str, ransac_px: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(rvec, tvec, inlier indices) from all points."""
    n = len(world)
    if method == "homography":
        rvec, tvec = _pose_from_homography(world, ideal, kk)
        rvec, tvec = _refine(world, ideal, kk, rvec, tvec)
        return rvec, tvec, np.arange(n)
    if method != "pnp_ransac":
        raise ValueError(f"unknown extrinsic method {method!r}")
    try:
        ok, rvec, tvec, inl = cv2.solvePnPRansac(
            world, ideal, kk, _ZERO_DIST, reprojectionError=ransac_px, iterationsCount=500,
            confidence=0.999, flags=cv2.SOLVEPNP_ITERATIVE,
        )  # fmt: skip
    except cv2.error:
        ok, inl = False, None
    inliers = np.arange(n) if inl is None else np.sort(inl.ravel())
    if not ok or len(inliers) < MIN_PNP_POINTS:
        rvec, tvec = _pnp_plain(world, ideal, kk)
        return rvec, tvec, np.arange(n)
    rvec, tvec = _refine(world[inliers], ideal[inliers], kk, rvec, tvec)
    return rvec, tvec, inliers


def _reproj_errors(
    k: Intrinsics, rvec: np.ndarray, tvec: np.ndarray, world: np.ndarray, uv: np.ndarray
) -> np.ndarray:
    ext = Extrinsics(rvec=[float(v) for v in rvec.ravel()], tvec=[float(v) for v in tvec.ravel()])
    proj, _ = CameraGeom.from_calibration(
        Calibration(camera_id="_", intrinsics=k, extrinsics=ext)
    ).project(world)
    return np.linalg.norm(proj - uv, axis=1)


class LandmarkSolve(BaseModel):
    """Outcome of the 6-landmark solve, for the calibration tool and report (FR-037)."""

    model_config = ConfigDict(extra="forbid")

    extrinsics: Extrinsics
    used: list[str]
    """Landmark ids the final pose was solved from."""
    dropped: list[str] = Field(default_factory=list)
    """Landmarks left out: RANSAC outliers first, then the drop-worst retries."""
    reproj_px_at_1280: float
    """Mean landmark reprojection of the used points, scaled to a 1280 px wide frame."""
    threshold_px: float
    """Acceptance threshold at 1280 px: 6 (nominal FOV) or 4 (lens profile)."""
    intrinsics_source: str
    accepted: bool


def solve_landmarks(
    pairs: Sequence[PairLike],
    k: Intrinsics,
    *,
    method: str = "pnp_ransac",
    ransac_px: float = 8.0,
    max_drops: int = MAX_DROPS,
) -> LandmarkSolve:
    """World -> camera pose from accepted landmark pairs (FR-037, UC-10).

    PnP with RANSAC on the landmarks (6 in the product path; ``method="homography"`` is
    the planar fallback). When the mean reprojection is at or over the threshold for the
    intrinsics source, the worst landmark is dropped and the pose re-solved, up to
    ``max_drops`` times while at least 4 remain. ``accepted`` is False when it stays over;
    the tool then asks SAM 3.1 for more landmarks. The landmark error is a fit residual,
    not an accuracy claim: accuracy comes from the audit harness (``audit_error``).
    """
    mp = [_as_pair(p) for p in pairs]
    if len(mp) < MIN_PNP_POINTS:
        raise ValueError(
            f"extrinsic calibration needs at least {MIN_PNP_POINTS} landmark pairs, got {len(mp)}"
        )
    ids = _pair_ids(mp)
    world = np.array([[p.x, p.y, p.z] for p in mp], np.float64)
    uv = np.array([[p.u, p.v] for p in mp], np.float64)
    kk = np.asarray(k.k, float)
    ideal = _ideal_pixels(k, uv)

    rvec, tvec, inliers = _initial_pose(world, ideal, kk, method, ransac_px)
    active = [int(i) for i in inliers]
    dropped = [ids[i] for i in range(len(mp)) if i not in active]
    scale = REFERENCE_WIDTH_PX / k.width
    base = NOMINAL_ACCEPT_PX if is_nominal(k) else PROFILE_ACCEPT_PX
    errs = _reproj_errors(k, rvec, tvec, world[active], uv[active])
    drops = 0
    while errs.mean() * scale >= base and drops < max_drops and len(active) > MIN_PNP_POINTS:
        # The worst landmark is the one whose removal leaves the best fit: with 6 points a
        # least-squares pose spreads one bad click over the others, so the largest residual
        # alone often names the wrong point.
        best: tuple[float, int, np.ndarray, np.ndarray] | None = None
        for j in range(len(active)):
            rest = active[:j] + active[j + 1 :]
            r_j, t_j = _refine(world[rest], ideal[rest], kk, rvec, tvec)
            m_j = float(_reproj_errors(k, r_j, t_j, world[rest], uv[rest]).mean())
            if best is None or m_j < best[0]:
                best = (m_j, j, r_j, t_j)
        assert best is not None
        _, j, rvec, tvec = best
        dropped.append(ids[active.pop(j)])
        drops += 1
        errs = _reproj_errors(k, rvec, tvec, world[active], uv[active])

    mean_px = float(errs.mean())
    ext = Extrinsics(
        rvec=[float(v) for v in np.asarray(rvec).ravel()],
        tvec=[float(v) for v in np.asarray(tvec).ravel()],
        method="homography" if method == "homography" else "pnp_ransac",
        reproj_mean_px=mean_px,
    )
    return LandmarkSolve(
        extrinsics=ext,
        used=[ids[i] for i in active],
        dropped=dropped,
        reproj_px_at_1280=mean_px * scale,
        threshold_px=base,
        intrinsics_source="fov_nominal" if is_nominal(k) else k.source,
        accepted=bool(mean_px * scale < base),
    )


def _ground_errors(
    cal: Calibration, pts: Sequence[MarkerPair], ground: RaycastScene | None = None
) -> np.ndarray:
    """Horizontal distance between each point's world position and where the calibrated
    camera's ray through its pixel meets the ground mesh (or the level plane through the
    point when no mesh is given). ``inf`` when the ray never meets it."""
    if not pts:
        return np.zeros(0)
    geom = CameraGeom.from_calibration(cal)
    uv = np.array([[p.u, p.v] for p in pts])
    world = np.array([[p.x, p.y, p.z] for p in pts])
    dirs = geom.pixel_rays(uv)
    c = geom.center
    errs = []
    for i, d in enumerate(dirs):
        hit = None
        if ground is not None:
            hits, ok = ground.cast_ground(c[None], d[None])
            if ok[0]:
                hit = hits[0]
        if hit is None and abs(d[1]) > 1e-9:
            s = (world[i, 1] - c[1]) / d[1]
            if s > 0:
                hit = c + s * d
        errs.append(np.inf if hit is None else float(np.hypot(*(hit - world[i])[[0, 2]])))
    return np.asarray(errs, float)


def heldout_ground_error(
    cal: Calibration, held: Sequence[MarkerPair], ground: RaycastScene | None = None
) -> float | None:
    """Mean horizontal ground error of held-out points (None when there are none)."""
    if not held:
        return None
    return float(np.mean(_ground_errors(cal, held, ground)))


def calibrate_extrinsics(
    pairs: Sequence[PairLike],
    k: Intrinsics,
    *,
    method: str = "pnp_ransac",
    holdout: int | Sequence[int] | None = None,
    ground: RaycastScene | None = None,
    ransac_px: float = 8.0,
    max_drops: int = MAX_DROPS,
) -> Extrinsics:
    """World -> camera pose from landmark pairs (FR-037): ``solve_landmarks`` on all of them.

    The product path passes the 6 accepted landmarks and gets ``heldout_ground_m=None``:
    accuracy is measured separately by the audit harness. ``holdout`` keeps the earlier
    protocol available (an int or indices; by default only with 8 or more pairs, the last 2
    are held out and their ground error is reported).
    """
    mp = [_as_pair(p) for p in pairs]
    if len(mp) < MIN_PNP_POINTS:
        raise ValueError(
            f"extrinsic calibration needs at least {MIN_PNP_POINTS} landmark pairs, got {len(mp)}"
        )
    fit_idx, held_idx = _split_holdout(len(mp), holdout)
    if len(fit_idx) < MIN_PNP_POINTS:
        raise ValueError(f"at least {MIN_PNP_POINTS} pairs must remain after holding out")
    res = solve_landmarks(
        [mp[i] for i in fit_idx], k, method=method, ransac_px=ransac_px, max_drops=max_drops
    )
    ext = res.extrinsics
    if held_idx:
        cal = Calibration(camera_id="_", intrinsics=k, extrinsics=ext)
        ext.heldout_ground_m = heldout_ground_error(cal, [mp[i] for i in held_idx], ground)
    return ext


# ---------------------------------------------------------------------------
# Audit harness (NFR-024 to NFR-026, benchmark only)
# ---------------------------------------------------------------------------


class AuditMarkerError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    ground_m: float
    """Horizontal distance between the surveyed position and the camera's ground estimate."""
    reproj_px: float
    """Pixel distance between the surveyed position projected and where it was clicked."""


class AuditReport(BaseModel):
    """Held-out ground error of one camera from surveyed markers never used in the solve."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    intrinsics_source: str
    n_markers: int
    markers: list[AuditMarkerError]
    mean_ground_m: float
    median_ground_m: float
    max_ground_m: float
    mean_reproj_px: float
    target_m: float = AUDIT_TARGET_M
    passed: bool


def _same_point(a: MarkerPair, b: MarkerPair) -> bool:
    if a.id is not None and a.id == b.id:
        return True
    return bool(np.linalg.norm([a.x - b.x, a.y - b.y, a.z - b.z]) < SAME_POINT_M)


def audit_error(
    cal: Calibration,
    markers: Sequence[SurveyedMarker | PairLike],
    *,
    ground: RaycastScene | None = None,
    landmarks: Sequence[PairLike] = (),
    target_m: float = AUDIT_TARGET_M,
) -> AuditReport:
    """Audit-harness held-out ground error per camera (NFR-024). Benchmark only.

    Each surveyed marker's pixel is cast from the calibrated camera onto the ground (mesh
    when given, otherwise the level plane through the marker) and compared horizontally
    with its tape-measured position. Markers are never used for calibration: passing the
    solve's ``landmarks`` makes any shared point (same id or within 1 cm) an error.
    """
    ms = [m if isinstance(m, MarkerPair) else _as_pair(m) for m in markers]
    if not ms:
        raise ValueError("the audit needs at least 1 surveyed marker")
    used = [_as_pair(p) for p in landmarks]
    shared = [m.id or f"({m.x}, {m.y}, {m.z})" for m in ms if any(_same_point(m, p) for p in used)]
    if shared:
        raise ValueError(
            f"audit markers are never used for calibration, but {shared} were landmarks"
        )
    ground_m = _ground_errors(cal, ms, ground)
    world = np.array([[m.x, m.y, m.z] for m in ms])
    uv = np.array([[m.u, m.v] for m in ms])
    proj, front = CameraGeom.from_calibration(cal).project(world)
    reproj = np.where(front, np.linalg.norm(proj - uv, axis=1), np.inf)
    ids = _pair_ids(ms)
    mean_g = float(np.mean(ground_m))
    return AuditReport(
        camera_id=cal.camera_id,
        intrinsics_source="fov_nominal" if is_nominal(cal.intrinsics) else cal.intrinsics.source,
        n_markers=len(ms),
        markers=[
            AuditMarkerError(id=i, ground_m=float(g), reproj_px=float(r))
            for i, g, r in zip(ids, ground_m, reproj, strict=True)
        ],
        mean_ground_m=mean_g,
        median_ground_m=float(np.median(ground_m)),
        max_ground_m=float(np.max(ground_m)),
        mean_reproj_px=float(np.mean(reproj)),
        target_m=target_m,
        passed=bool(np.isfinite(mean_g) and mean_g < target_m),
    )


def with_audit(cal: Calibration, report: AuditReport) -> Calibration:
    """A copy of ``cal`` carrying the measured audit error (``extrinsics.heldout_ground_m``),
    which ``locate()`` then uses in place of the landmark error."""
    if report.camera_id != cal.camera_id:
        raise ValueError(f"audit is for {report.camera_id!r}, calibration is {cal.camera_id!r}")
    out = cal.model_copy(deep=True)
    out.extrinsics.heldout_ground_m = report.mean_ground_m
    return out


def calibration_report(cal: Calibration) -> dict:
    """Acceptance summary for the committed calibration report (FR-036, FR-037, NFR-024).

    ``heldout_ground_m`` is the audit-harness error when measured (``audit_measured``).
    """
    i, e = cal.intrinsics, cal.extrinsics
    nominal = is_nominal(i)
    scale = REFERENCE_WIDTH_PX / i.width if i.width else 1.0
    reproj = None if e.reproj_mean_px is None else e.reproj_mean_px * scale
    threshold = NOMINAL_ACCEPT_PX if nominal else PROFILE_ACCEPT_PX
    profile_ok = i.rms_px is not None and i.rms_px < RMS_ACCEPT_PX
    return {
        "camera_id": cal.camera_id,
        "intrinsics_source": "fov_nominal" if nominal else i.source,
        "intrinsics_rms_px": i.rms_px,
        "intrinsics_ok": True if nominal else profile_ok,
        "fov_fallback": i.fov_fallback,
        "reproj_mean_px_at_1280": reproj,
        "landmark_threshold_px": threshold,
        "reproj_ok": reproj is not None and reproj < threshold,
        "audit_measured": e.heldout_ground_m is not None,
        "heldout_ground_m": e.heldout_ground_m,
        "audit_target_m": AUDIT_TARGET_M,
        "heldout_ok": e.heldout_ground_m is not None and e.heldout_ground_m < AUDIT_TARGET_M,
        "method": e.method,
    }


# ---------------------------------------------------------------------------
# calibration.json
# ---------------------------------------------------------------------------


def save_calibrations(path: Path | str, cals: Sequence[Calibration]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = [c.model_dump(mode="json") for c in cals]
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def load_calibrations(path: Path | str) -> list[Calibration]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("cameras", [])
    return [Calibration.model_validate(c) for c in raw]
