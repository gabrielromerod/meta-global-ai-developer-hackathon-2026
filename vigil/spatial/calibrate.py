"""Intrinsic and extrinsic calibration (FR-036, FR-037; spec 7 "Camera calibration").

* Intrinsics: printed checkerboard, about 20 views per camera, OpenCV standard model or the
  fisheye model for very wide lenses. Accepted when RMS reprojection is under 1.0 px;
  otherwise (or when the board cannot be detected) the focal length comes from the lens
  field of view with no distortion, and ``fov_fallback`` is set (flagged low accuracy).
* Extrinsics: 8 ground markers clicked in the still and on the mesh; PnP with RANSAC on 6,
  holding out 2. Reports mean reprojection (px) and the held-out ground error (m). A planar
  homography from 4+ markers is the fallback when the mesh is unusable.
* ``config/calibration.json`` is a JSON list of ``vigil.models.Calibration``.

OpenCV API used (checked against the installed opencv-python-headless 5.0 docstrings, since
docs.opencv.org refused automated fetches): ``calibrateCamera``, ``fisheye.calibrate``,
``findChessboardCorners``, ``cornerSubPix``, ``solvePnPRansac``, ``solvePnP``,
``findHomography``, ``projectPoints`` and ``undistortPoints``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict

from vigil.models import Calibration, Extrinsics, Intrinsics
from vigil.spatial.geometry import CameraGeom, RaycastScene, undistort_normalized

RMS_ACCEPT_PX = 1.0
"""FR-036: intrinsics accepted below this RMS; otherwise the field-of-view fallback."""
REPROJ_ACCEPT_PX = 4.0
"""FR-037: mean reprojection accepted below this at 1280 px width."""
HELDOUT_ACCEPT_M = 0.25
"""FR-037: held-out ground error accepted below this."""
DEFAULT_HFOV_DEG = 90.0
"""Used only when no lens field of view is given to the fallback; pass the datasheet value."""
MIN_BOARD_VIEWS = 3


class MarkerPair(BaseModel):
    """One clicked marker: pixel in the camera still and its world position on the mesh.

    This is the ``PixelPoint3D`` of spec 9.5 (module-local until promoted to vigil.models).
    """

    model_config = ConfigDict(extra="forbid")

    u: float
    v: float
    x: float
    y: float
    z: float
    id: str | None = None


PairLike = MarkerPair | Sequence[float]


# ---------------------------------------------------------------------------
# Intrinsics (FR-036)
# ---------------------------------------------------------------------------


def fov_intrinsics(
    width: int, height: int, hfov_deg: float = DEFAULT_HFOV_DEG, rms_px: float | None = None
) -> Intrinsics:
    """Pinhole intrinsics from the horizontal field of view, no distortion, flagged."""
    if not 0.0 < hfov_deg < 180.0:
        raise ValueError(f"horizontal field of view must be in (0, 180) degrees, got {hfov_deg}")
    f = (width / 2.0) / float(np.tan(np.radians(hfov_deg) / 2.0))
    return Intrinsics(
        model="pinhole",
        k=[[f, 0.0, width / 2.0], [0.0, f, height / 2.0], [0.0, 0.0, 1.0]],
        dist=[],
        width=width,
        height=height,
        rms_px=rms_px,
        fov_fallback=True,
    )


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
    """Calibrate from checkerboard views (FR-036).

    ``pattern`` is the inner-corner count (columns, rows). Falls back to
    ``fov_intrinsics(hfov_deg)`` when fewer than 3 views are detected or the RMS is at or
    above 1.0 px; the fallback is flagged with ``fov_fallback=True``.
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
    )


# ---------------------------------------------------------------------------
# Extrinsics (FR-037)
# ---------------------------------------------------------------------------


def _as_pair(p: PairLike) -> MarkerPair:
    if isinstance(p, MarkerPair):
        return p
    u, v, x, y, z = (float(c) for c in p)
    return MarkerPair(u=u, v=v, x=x, y=y, z=z)


def _split_holdout(n: int, holdout: int | Sequence[int] | None) -> tuple[list[int], list[int]]:
    if holdout is None:
        held = list(range(n - 2, n)) if n >= 6 else []
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
    """Pose from markers on (approximately) one level plane y = y0."""
    y0 = float(world[:, 1].mean())
    plane = world[:, [0, 2]]
    norm = (np.linalg.inv(kk) @ np.column_stack([ideal, np.ones(len(ideal))]).T).T[:, :2]
    hmat, _ = cv2.findHomography(plane, norm, 0)
    if hmat is None:
        raise ValueError("homography failed: markers may be collinear")
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


def heldout_ground_error(
    cal: Calibration, held: Sequence[MarkerPair], ground: RaycastScene | None = None
) -> float | None:
    """Mean horizontal distance between held-out markers and their back-projected pixels.

    Each held-out pixel is cast from the calibrated camera onto the ground mesh when given,
    otherwise onto the level plane through that marker.
    """
    if not held:
        return None
    geom = CameraGeom.from_calibration(cal)
    uv = np.array([[p.u, p.v] for p in held])
    world = np.array([[p.x, p.y, p.z] for p in held])
    dirs = geom.pixel_rays(uv)
    c = geom.center
    errs = []
    for i, d in enumerate(dirs):
        hit = None
        if ground is not None:
            pts, ok = ground.cast_ground(c[None], d[None])
            if ok[0]:
                hit = pts[0]
        if hit is None and abs(d[1]) > 1e-9:
            s = (world[i, 1] - c[1]) / d[1]
            if s > 0:
                hit = c + s * d
        errs.append(np.inf if hit is None else float(np.hypot(*(hit - world[i])[[0, 2]])))
    return float(np.mean(errs))


def calibrate_extrinsics(
    pairs: Sequence[PairLike],
    k: Intrinsics,
    *,
    method: str = "pnp_ransac",
    holdout: int | Sequence[int] | None = None,
    ground: RaycastScene | None = None,
    ransac_px: float = 8.0,
) -> Extrinsics:
    """World -> camera pose from clicked marker pairs (FR-037).

    By default the last 2 markers are held out when 6 or more are given (8 markers: PnP with
    RANSAC on 6, 2 held out). ``method="homography"`` is the planar fallback from 4+ markers.
    """
    mp = [_as_pair(p) for p in pairs]
    if len(mp) < 4:
        raise ValueError(f"extrinsic calibration needs at least 4 marker pairs, got {len(mp)}")
    fit_idx, held_idx = _split_holdout(len(mp), holdout)
    if len(fit_idx) < 4:
        raise ValueError("at least 4 marker pairs must remain after holding out")
    fit = [mp[i] for i in fit_idx]
    held = [mp[i] for i in held_idx]
    world = np.array([[p.x, p.y, p.z] for p in fit], np.float64)
    uv = np.array([[p.u, p.v] for p in fit], np.float64)
    kk = np.asarray(k.k, float)
    ideal = _ideal_pixels(k, uv)
    zero = np.zeros(5)

    if method == "homography":
        rvec, tvec = _pose_from_homography(world, ideal, kk)
        ok, rvec, tvec = cv2.solvePnP(
            world, ideal, kk, zero, rvec, tvec, useExtrinsicGuess=True,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )  # fmt: skip
        inliers = np.arange(len(fit))
    elif method == "pnp_ransac":
        ok, rvec, tvec, inl = cv2.solvePnPRansac(
            world, ideal, kk, zero, reprojectionError=ransac_px, iterationsCount=500,
            confidence=0.999, flags=cv2.SOLVEPNP_ITERATIVE,
        )  # fmt: skip
        inliers = np.arange(len(fit)) if inl is None else inl.ravel()
        if not ok or len(inliers) < 4:
            ok, rvec, tvec = cv2.solvePnP(world, ideal, kk, zero, flags=cv2.SOLVEPNP_ITERATIVE)
            inliers = np.arange(len(fit))
        else:
            ok, rvec, tvec = cv2.solvePnP(
                world[inliers], ideal[inliers], kk, zero, rvec, tvec, useExtrinsicGuess=True,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )  # fmt: skip
    else:
        raise ValueError(f"unknown extrinsic method {method!r}")
    if not ok:
        raise ValueError("PnP failed: check marker clicks")

    ext = Extrinsics(
        rvec=[float(v) for v in np.asarray(rvec).ravel()],
        tvec=[float(v) for v in np.asarray(tvec).ravel()],
        method="homography" if method == "homography" else "pnp_ransac",
    )
    cal = Calibration(camera_id="_", intrinsics=k, extrinsics=ext)
    proj, _ = CameraGeom.from_calibration(cal).project(world)
    ext.reproj_mean_px = float(np.linalg.norm(proj - uv, axis=1).mean())
    ext.heldout_ground_m = heldout_ground_error(cal, held, ground)
    return ext


def calibration_report(cal: Calibration) -> dict:
    """Acceptance summary for the committed calibration report (NFR-024)."""
    i, e = cal.intrinsics, cal.extrinsics
    scale = 1280.0 / i.width if i.width else 1.0
    reproj = None if e.reproj_mean_px is None else e.reproj_mean_px * scale
    return {
        "camera_id": cal.camera_id,
        "intrinsics_rms_px": i.rms_px,
        "intrinsics_ok": (not i.fov_fallback) and i.rms_px is not None and i.rms_px < RMS_ACCEPT_PX,
        "fov_fallback": i.fov_fallback,
        "reproj_mean_px_at_1280": reproj,
        "reproj_ok": reproj is not None and reproj < REPROJ_ACCEPT_PX,
        "heldout_ground_m": e.heldout_ground_m,
        "heldout_ok": e.heldout_ground_m is not None and e.heldout_ground_m < HELDOUT_ACCEPT_M,
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
