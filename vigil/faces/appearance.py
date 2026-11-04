"""Recurring-visitor profiles by clothing when no face is large enough (change 2026-11-04).

The fallback for the 180° Duo panoramas, where faces are often 10–20 px wide. It groups
person tracks across processed captures by Muse Spark's FR-009 allowlist notes only (upper
and lower clothing colour, carried items). It never uses a face, body shape or any
measurement. Like faces, it covers only people inside the property: a track counts only if
one of its SAM boxes has its foot point in a non-`perimeter` zone. Clips that start within
`ARRIVAL_GAP_S` of each other are one arrival, so two cameras on one visit count once.

A clothing match is weak evidence: different people dressed alike are grouped together. The
card says so, and nothing here reaches a role, a rule, the ledger or a story.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from vigil.faces.enroll import OUTSIDE_PROPERTY, foot_zone_kind
from vigil.models import CameraCfg

ARRIVAL_GAP_S = 120.0
UNKNOWN = {"", "unknown", "none", "null"}
MAX_THUMBS = 4


def _known(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() not in UNKNOWN


def signature(note: dict[str, Any]) -> tuple[str, str, tuple[str, ...]] | None:
    """(upper, lower, carried) when at least two traits are known; otherwise None."""
    upper = str(note.get("upper_color") or "unknown").strip().lower()
    lower = str(note.get("lower_color") or "unknown").strip().lower()
    carried = tuple(
        sorted({str(c).strip().lower() for c in note.get("carrying") or [] if _known(c)})
    )
    known = int(_known(upper)) + int(_known(lower)) + int(bool(carried))
    if known < 2:
        return None
    return (upper if _known(upper) else "unknown", lower if _known(lower) else "unknown", carried)


def label(sig: tuple[str, str, tuple[str, ...]]) -> str:
    upper, lower, carried = sig
    parts = []
    if _known(upper):
        parts.append(f"{upper} top")
    if _known(lower):
        parts.append(f"{lower} bottoms")
    if carried:
        parts.append("carrying " + " and ".join(carried))
    return ", ".join(parts)


def profile_id(sig: tuple[str, str, tuple[str, ...]]) -> str:
    return "ap_" + hashlib.sha256(json.dumps(sig).encode()).hexdigest()[:10]


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sightings(folder: Path, cams: dict[str, CameraCfg]) -> Iterable[dict[str, Any]]:
    data = _read(folder / "visits.json")
    if not isinstance(data, dict):
        return
    try:
        start = datetime.fromisoformat(str(data.get("session_start")))
    except ValueError:
        return
    notes = data.get("appearance") or {}
    tracks = {t.get("id"): t for t in data.get("tracks") or [] if isinstance(t, dict)}
    for camera_id, overlay in ((data.get("overlays") or {}).get("cameras") or {}).items():
        camera = cams.get(camera_id)
        ow, oh = float(overlay.get("width") or 0), float(overlay.get("height") or 0)
        if camera is None or not camera.zones or ow <= 0 or oh <= 0:
            continue
        scale = (camera.width / ow, camera.height / oh)
        inside: dict[str, list[tuple[float, list[float]]]] = {}
        for frame in overlay.get("frames") or []:
            for obj in frame.get("objects") or []:
                tid, box = obj.get("track_id"), obj.get("box")
                if tid not in notes or not isinstance(box, list) or len(box) != 4:
                    continue
                kind = foot_zone_kind(camera, tuple(box), scale=scale)  # type: ignore[arg-type]
                if kind is not None and kind not in OUTSIDE_PROPERTY:
                    inside.setdefault(tid, []).append((float(frame.get("t", 0.0)), box))
        for tid, hits in inside.items():
            note = notes.get(tid) or {}
            sig = signature(note) if str(note.get("class") or "person") == "person" else None
            if sig is None:
                continue
            hits.sort(key=lambda h: h[0])
            t_mid, box = hits[len(hits) // 2]
            first = float((tracks.get(tid) or {}).get("t_first") or hits[0][0])
            yield {
                "signature": sig,
                "capture_id": folder.name,
                "track_id": tid,
                "camera_id": camera_id,
                "seen_at": start + timedelta(seconds=first),
                "t": t_mid,
                "box": [float(v) for v in box],
                "overlay_size": [ow, oh],
            }


def appearance_profiles(results_root: Path, cameras: Iterable[CameraCfg]) -> list[dict[str, Any]]:
    """Clothing profiles across processed captures, most-seen first.

    Merged `moment-*` results are skipped: their source clips are already counted.
    """
    cams = {c.id: c for c in cameras}
    groups: dict[tuple, list[dict[str, Any]]] = {}
    if not Path(results_root).is_dir():
        return []
    for folder in sorted(Path(results_root).iterdir()):
        if folder.name.startswith("moment-") or folder.is_symlink() or not folder.is_dir():
            continue
        for s in _sightings(folder, cams):
            groups.setdefault(s["signature"], []).append(s)
    out = []
    for sig, rows in groups.items():
        rows.sort(key=lambda s: s["seen_at"])
        arrivals: list[list[dict[str, Any]]] = []
        for s in rows:
            if (
                arrivals
                and (s["seen_at"] - arrivals[-1][0]["seen_at"]).total_seconds() <= ARRIVAL_GAP_S
            ):
                arrivals[-1].append(s)
            else:
                arrivals.append([s])
        newest = list(reversed(arrivals))
        out.append({
            "id": profile_id(sig),
            "basis": "clothing",
            "label": label(sig),
            "count": len(arrivals),
            "sightings": [
                {k: (s[k].isoformat() if k == "seen_at" else s[k])
                 for k in ("capture_id", "track_id", "camera_id", "seen_at")}
                for arrival in newest for s in arrival
            ],
            "thumbs": [
                {k: (a[0][k].isoformat() if k == "seen_at" else a[0][k])
                 for k in ("capture_id", "track_id", "camera_id", "seen_at", "t", "box",
                           "overlay_size")}
                for a in newest[:MAX_THUMBS]
            ],
        })  # fmt: skip
    out.sort(key=lambda p: (-p["count"], p["label"]))
    return out


def upper_body_crop(frame_bgr: Any, box_frame: list[float], max_px: int = 160) -> bytes | None:
    """JPEG of the top 55% of a person box (head and upper body), padded, long side ≤ max_px."""
    import cv2

    h, w = frame_bgr.shape[:2]
    x0, y0, x1, y1 = box_frame
    bw, bh = x1 - x0, y1 - y0
    if bw <= 2 or bh <= 2:
        return None
    pad = 0.15 * bw
    cx0, cy0 = max(0, int(x0 - pad)), max(0, int(y0 - 0.05 * bh))
    cx1, cy1 = min(w, int(x1 + pad)), min(h, int(y0 + 0.55 * bh))
    if cx1 - cx0 < 4 or cy1 - cy0 < 4:
        return None
    crop = frame_bgr[cy0:cy1, cx0:cx1]
    scale = max_px / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(
            crop, (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale)))
        )
    elif scale > 1:
        crop = cv2.resize(crop, (int(crop.shape[1] * scale), int(crop.shape[0] * scale)),
                          interpolation=cv2.INTER_CUBIC)  # fmt: skip
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None
