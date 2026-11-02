"""Marker-walk accuracy: median and p90 error, share inside r95 (NFR-025, NFR-026, FR-039).

A person stands on surveyed markers not used for calibration (spec 7, step 7). Each
point is a dict:

    {"marker_id": "m3", "camera_id": "side_left",
     "true": [x, y, z] or [x, z], "est": [x, y, z] or [x, z],
     "r95": 0.42, "range_m": 6.1}

Error is horizontal: world frame is Y-up (glTF), so 3-vectors use x and z; 2-vectors are
taken as (x, z). `range_m` (camera to marker) is optional and enables the "within 10 m"
figure that NFR-025's target refers to. Pure; percentiles use linear interpolation.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

MEDIAN_TARGET_M = 0.5
INSIDE_R95_TARGET = 0.90
NEAR_RANGE_M = 10.0


def _xz(v: list[float]) -> tuple[float, float]:
    if len(v) == 3:
        return float(v[0]), float(v[2])
    if len(v) == 2:
        return float(v[0]), float(v[1])
    raise ValueError(f"expected [x, z] or [x, y, z], got {v!r}")


def _err(p: dict) -> float:
    (tx, tz), (ex, ez) = _xz(p["true"]), _xz(p["est"])
    return math.hypot(ex - tx, ez - tz)


def _stats(errs: list[float], inside: list[bool]) -> dict[str, Any]:
    if not errs:
        return {"n": 0, "median_m": None, "p90_m": None, "mean_m": None, "max_m": None,
                "inside_r95_share": None}  # fmt: skip
    a = np.asarray(errs, dtype=float)
    return {
        "n": len(errs),
        "median_m": round(float(np.median(a)), 6),
        "p90_m": round(float(np.percentile(a, 90)), 6),
        "mean_m": round(float(a.mean()), 6),
        "max_m": round(float(a.max()), 6),
        "inside_r95_share": round(sum(inside) / len(inside), 6),
    }


def spatial_report(points: list[dict]) -> dict:
    errs = [_err(p) for p in points]
    inside = [e <= float(p["r95"]) for e, p in zip(errs, points, strict=True)]
    report = _stats(errs, inside)

    near = [
        (e, i)
        for e, i, p in zip(errs, inside, points, strict=True)
        if p.get("range_m") is not None and float(p["range_m"]) <= NEAR_RANGE_M
    ]
    report["within_10m"] = _stats([e for e, _ in near], [i for _, i in near])

    per_cam: dict[str, dict] = {}
    for cam in sorted({str(p.get("camera_id", "?")) for p in points}):
        idx = [k for k, p in enumerate(points) if str(p.get("camera_id", "?")) == cam]
        per_cam[cam] = _stats([errs[k] for k in idx], [inside[k] for k in idx])
    report["per_camera"] = per_cam

    # NFR-025 is stated "within 10 m of the camera"; fall back to all points when no
    # range was recorded, and say so.
    basis = report["within_10m"] if report["within_10m"]["n"] else report
    report["median_basis"] = "within_10m" if report["within_10m"]["n"] else "all_points"
    median = basis["median_m"]
    share = report["inside_r95_share"]
    report["targets"] = {
        "median_under_m": MEDIAN_TARGET_M,
        "inside_r95_at_least": INSIDE_R95_TARGET,
    }
    report["met"] = {
        "median_under_0_5m": None if median is None else median < MEDIAN_TARGET_M,
        "inside_r95_at_least_90pct": None if share is None else share >= INSIDE_R95_TARGET,
    }
    return report
