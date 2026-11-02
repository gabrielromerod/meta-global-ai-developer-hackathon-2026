"""From detection to 3D position (FR-039; spec 7 "From detection to 3D position", 9.4).

1. Foot point: median x and maximum y of the lowest 5% of the SAM mask's pixels
   (box bottom-centre when there is no usable mask), undistorted.
2. Ray cast from the camera centre through the foot point onto the ground mesh.
3. Occlusion: a mask touching the image's bottom edge (or flagged clipped) hides the feet;
   the top of the mask with a 1.7 ± 0.15 m height prior is used instead, flagged
   ``low_confidence`` with method ``height_prior``.
4. Uncertainty: 50 samples with 3 px noise, plus the camera's held-out ground error,
   give the 95% radius ``r95``.
5. Smoothing at 2 Hz with a 1 s median filter; nothing is interpolated across a gap, and no
   position is ever kept inside a gap.
6. Two cameras: inverse-variance weighted mean (method ``fused``); estimates more than 1 m
   apart are kept separately and flagged ``inconsistent``.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from vigil.models import Calibration, Gap, Position, TrackFrame
from vigil.spatial.geometry import CameraGeom, RaycastScene, rle_decode

N_SAMPLES = 50
PIXEL_SIGMA = 3.0
HEIGHT_PRIOR_M = 1.7
HEIGHT_SIGMA_M = 0.15
LOWEST_FRACTION = 0.05
BOTTOM_MARGIN_PX = 1
CHI2_2D_95 = 5.991464547107979
"""95% quantile of the chi-square distribution with 2 degrees of freedom."""
K95 = math.sqrt(CHI2_2D_95)
FUSE_MAX_SEP_M = 1.0
MIN_HIT_FRACTION = 0.5
MAX_RANGE_M = 60.0


@dataclass(frozen=True)
class FootPoint:
    foot: tuple[float, float]
    top: tuple[float, float]
    clipped: bool
    from_mask: bool


def _decode_mask(frame: TrackFrame, width: int, height: int) -> np.ndarray | None:
    if not frame.mask_rle:
        return None
    try:
        mask = rle_decode(frame.mask_rle, height, width)
    except (ValueError, KeyError, TypeError, IndexError):
        return None
    return mask if mask.any() else None


def foot_point(frame: TrackFrame, width: int, height: int) -> FootPoint:
    """Foot and head pixels of a detection, and whether the feet are hidden (clipped)."""
    mask = _decode_mask(frame, width, height)
    if mask is not None:
        ys, xs = np.nonzero(mask)
        n = len(ys)
        k = max(1, math.ceil(LOWEST_FRACTION * n))
        order = np.argsort(ys, kind="stable")
        low = order[-k:]
        high = order[:k]
        foot = (float(np.median(xs[low])), float(ys[low].max()))
        top = (float(np.median(xs[high])), float(ys[high].min()))
        bottom_y = float(ys.max())
        from_mask = True
    else:
        b = frame.box
        cx = (b.x1 + b.x2) / 2.0
        foot = (float(cx), float(b.y2))
        top = (float(cx), float(b.y1))
        bottom_y = float(b.y2)
        from_mask = False
    clipped = bool(frame.clipped) or bottom_y >= height - 1 - BOTTOM_MARGIN_PX
    return FootPoint(foot=foot, top=top, clipped=clipped, from_mask=from_mask)


def _geom(cam: Calibration | CameraGeom) -> CameraGeom:
    return cam if isinstance(cam, CameraGeom) else CameraGeom.from_calibration(cam)


def _height_prior_hits(
    geom: CameraGeom, ground: RaycastScene, uv: np.ndarray, heights: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Point on each ray where it is ``heights`` above the ground; returns (points, ok)."""
    dirs = geom.pixel_rays(uv)
    c = geom.center
    s = np.arange(0.05, MAX_RANGE_M, 0.05)
    pts = c[None, None, :] + s[None, :, None] * dirs[:, None, :]
    g = ground.height_at(pts[..., 0], pts[..., 2])
    f = pts[..., 1] - g - heights[:, None]
    sign = np.sign(f)
    change = (sign[:, :-1] * sign[:, 1:] <= 0) & np.isfinite(f[:, :-1]) & np.isfinite(f[:, 1:])
    ok = change.any(axis=1)
    idx = np.argmax(change, axis=1)
    rows = np.arange(len(uv))
    f0, f1 = f[rows, idx], f[rows, idx + 1]
    denom = np.where(np.abs(f0 - f1) > 1e-12, f0 - f1, 1.0)
    frac = np.clip(np.where(ok, f0 / denom, 0.0), 0.0, 1.0)
    s_hit = s[idx] + frac * (s[1] - s[0])
    head = c[None, :] + s_hit[:, None] * dirs
    foot_y = ground.height_at(head[:, 0], head[:, 2])
    out = np.column_stack([head[:, 0], foot_y, head[:, 2]])
    ok &= np.isfinite(foot_y)
    return out, ok


def _ground_hits(
    geom: CameraGeom, ground: RaycastScene, uv: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    dirs = geom.pixel_rays(uv)
    origins = np.broadcast_to(geom.center, dirs.shape)
    return ground.cast_ground(origins, dirs, max_t=MAX_RANGE_M)


def r95_from_samples(center_xz: np.ndarray, samples_xz: np.ndarray, extra_sigma: float) -> float:
    """95% horizontal radius from Monte Carlo samples plus an isotropic calibration term.

    Uses the larger of the empirical 95th percentile and the circle that covers 95% of a
    Gaussian with the samples' largest principal variance (both widened by the calibration
    term), so an elongated depth error is never under-stated.
    """
    d = samples_xz - center_xz[None, :]
    m = d.T @ d / max(1, len(d))
    lam = float(np.linalg.eigvalsh(m).max()) + extra_sigma**2
    r_param = K95 * math.sqrt(max(lam, 0.0))
    r_emp = float(np.quantile(np.linalg.norm(d, axis=1), 0.95)) if len(d) else 0.0
    r_emp = math.sqrt(r_emp**2 + CHI2_2D_95 * extra_sigma**2)
    return max(r_param, r_emp)


def locate(
    frame: TrackFrame,
    cam: Calibration | CameraGeom,
    ground: RaycastScene,
    rng: np.random.Generator | None = None,
    *,
    track_id: str = "",
    n_samples: int = N_SAMPLES,
    pixel_sigma: float = PIXEL_SIGMA,
) -> Position | None:
    """Foot point -> undistort -> ray -> ground hit; 50 noisy samples give r95 (spec 9.4).

    Returns None when the ray never meets the ground (sky, outside the mesh) or when too few
    noisy samples hit to state an honest radius.
    """
    rng = rng if rng is not None else np.random.default_rng(0)
    geom = _geom(cam)
    fp = foot_point(frame, geom.width, geom.height)
    # Mean horizontal error e of an isotropic 2D Gaussian is sigma * sqrt(pi / 2).
    cal_sigma = geom.heldout_ground_m / math.sqrt(math.pi / 2.0)
    noise = rng.normal(0.0, pixel_sigma, (n_samples, 2))
    flags: list[str] = []

    if not fp.clipped:
        method = "footpoint"
        uv0 = np.asarray(fp.foot, float)[None]
        pts, hit = _ground_hits(geom, ground, uv0)
        if not hit[0]:
            return None
        center = pts[0]
        spts, shit = _ground_hits(geom, ground, uv0 + noise)
    else:
        method = "height_prior"
        flags.append("low_confidence")
        uv0 = np.asarray(fp.top, float)[None]
        pts, hit = _height_prior_hits(geom, ground, uv0, np.array([HEIGHT_PRIOR_M]))
        if not hit[0]:
            return None
        center = pts[0]
        hs = rng.normal(HEIGHT_PRIOR_M, HEIGHT_SIGMA_M, n_samples)
        spts, shit = _height_prior_hits(geom, ground, uv0 + noise, hs)

    if shit.mean() < MIN_HIT_FRACTION:
        return None
    if shit.mean() < 0.9 and "low_confidence" not in flags:
        flags.append("low_confidence")
    r95 = r95_from_samples(center[[0, 2]], spts[shit][:, [0, 2]], cal_sigma)
    return Position(
        track_id=track_id,
        t=frame.t,
        x=float(center[0]),
        y=float(center[1]),
        z=float(center[2]),
        r95=float(r95),
        method=method,
        cameras=[geom.camera_id],
        flags=flags,
    )


def locate_track(
    frames: Iterable[TrackFrame],
    cam: Calibration | CameraGeom,
    ground: RaycastScene,
    rng: np.random.Generator | None = None,
    *,
    track_id: str = "",
    gaps: Sequence[Gap] = (),
) -> list[Position]:
    """Locate every frame of one camera track, then smooth at 2 Hz and drop gap times."""
    rng = rng if rng is not None else np.random.default_rng(0)
    geom = _geom(cam)
    raw = [p for f in frames if (p := locate(f, geom, ground, rng, track_id=track_id))]
    return smooth(raw, gaps=gaps)


# ---------------------------------------------------------------------------
# Gaps and smoothing
# ---------------------------------------------------------------------------


def in_gap(t: float, gaps: Iterable[Gap]) -> bool:
    return any(g.t0 < t < g.t1 for g in gaps)


def filter_gaps(positions: Iterable[Position], gaps: Iterable[Gap]) -> list[Position]:
    """Drop every position strictly inside a gap: no camera saw the subject then."""
    gl = list(gaps)
    return [p for p in positions if not in_gap(p.t, gl)]


def _segments(ps: list[Position], window_s: float, gaps: list[Gap]) -> list[list[Position]]:
    segs: list[list[Position]] = []
    for p in ps:
        if segs:
            prev = segs[-1][-1]
            crosses = any(prev.t <= g.t0 < p.t or prev.t < g.t1 <= p.t for g in gaps)
            if p.t - prev.t <= window_s and not crosses:
                segs[-1].append(p)
                continue
        segs.append([p])
    return segs


def _median_position(ps: list[Position], t: float) -> Position:
    methods = Counter(p.method for p in ps)
    method = methods.most_common(1)[0][0]
    cams: list[str] = []
    flags: list[str] = []
    for p in ps:
        cams.extend(c for c in p.cameras if c not in cams)
        flags.extend(f for f in p.flags if f not in flags)
    return Position(
        track_id=ps[0].track_id,
        t=t,
        x=float(np.median([p.x for p in ps])),
        y=float(np.median([p.y for p in ps])),
        z=float(np.median([p.z for p in ps])),
        r95=float(np.median([p.r95 for p in ps])),
        method=method,
        cameras=cams,
        flags=flags,
    )


def smooth(
    positions: Iterable[Position],
    hz: float = 2.0,
    window_s: float = 1.0,
    gaps: Sequence[Gap] = (),
) -> list[Position]:
    """Resample each track at ``hz`` (aligned to the session clock) with a centred median
    filter of ``window_s``. Segments are split at gaps and at breaks longer than the window,
    so nothing is ever interpolated across a gap."""
    gl = list(gaps)
    by_track: dict[str, list[Position]] = defaultdict(list)
    for p in filter_gaps(positions, gl):
        by_track[p.track_id].append(p)
    step = 1.0 / hz
    half = window_s / 2.0
    out: list[Position] = []
    for track_id in sorted(by_track):
        ps = sorted(by_track[track_id], key=lambda p: p.t)
        for seg in _segments(ps, window_s, gl):
            t_first, t_last = seg[0].t, seg[-1].t
            k0 = math.ceil(round(t_first * hz, 6))
            k1 = math.floor(round(t_last * hz, 6))
            grid = [k * step for k in range(k0, k1 + 1)]
            if not grid:
                grid = [float(np.median([p.t for p in seg]))]
            ts = np.array([p.t for p in seg])
            for tk in grid:
                sel = [seg[i] for i in np.flatnonzero(np.abs(ts - tk) <= half + 1e-9)]
                if sel:
                    out.append(_median_position(sel, round(tk, 6)))
    return filter_gaps(out, gl)


# ---------------------------------------------------------------------------
# Two-camera fusion
# ---------------------------------------------------------------------------


def _sigma(p: Position) -> float:
    return max(p.r95 / K95, 1e-3)


def fuse(estimates: Sequence[Position], max_sep_m: float = FUSE_MAX_SEP_M) -> list[Position]:
    """Fuse simultaneous estimates of one subject from different cameras.

    Inverse-variance weighted mean (variance from r95). When any two estimates are more than
    ``max_sep_m`` apart horizontally, all are kept separately and flagged ``inconsistent``.
    """
    ests = list(estimates)
    if len(ests) < 2:
        return [p.model_copy(deep=True) for p in ests]
    for i in range(len(ests)):
        for j in range(i + 1, len(ests)):
            a, b = ests[i], ests[j]
            if math.hypot(a.x - b.x, a.z - b.z) > max_sep_m:
                return [
                    p.model_copy(
                        update={"flags": [*p.flags, "inconsistent"]}
                        if "inconsistent" not in p.flags
                        else {},
                        deep=True,
                    )
                    for p in ests
                ]
    w = np.array([1.0 / _sigma(p) ** 2 for p in ests])
    ws = float(w.sum())

    def wmean(attr: str) -> float:
        return float(sum(wi * getattr(p, attr) for wi, p in zip(w, ests, strict=True)) / ws)

    cams: list[str] = []
    for p in ests:
        cams.extend(c for c in p.cameras if c not in cams)
    flags: list[str] = []
    if all("low_confidence" in p.flags for p in ests):
        flags.append("low_confidence")
    return [
        Position(
            track_id=ests[0].track_id,
            t=float(np.mean([p.t for p in ests])),
            x=wmean("x"),
            y=wmean("y"),
            z=wmean("z"),
            r95=K95 / math.sqrt(ws),
            method="fused",
            cameras=cams,
            flags=flags,
        )
    ]


def fuse_tracks(
    a: Sequence[Position], b: Sequence[Position], max_dt: float = 0.25
) -> list[Position]:
    """Pair two linked tracks' positions by time (within ``max_dt``) and fuse each pair;
    unpaired positions are kept as they are. Output is sorted by time."""
    out: list[Position] = []
    used_b: set[int] = set()
    bt = np.array([p.t for p in b]) if b else np.zeros(0)
    for pa in a:
        j = -1
        if len(bt):
            cand = np.argsort(np.abs(bt - pa.t))
            j = next((int(c) for c in cand if int(c) not in used_b), -1)
        if j >= 0 and abs(bt[j] - pa.t) <= max_dt:
            used_b.add(j)
            out.extend(fuse([pa, b[j]]))
        else:
            out.append(pa.model_copy(deep=True))
    out.extend(p.model_copy(deep=True) for i, p in enumerate(b) if i not in used_b)
    return sorted(out, key=lambda p: (p.t, p.cameras))
