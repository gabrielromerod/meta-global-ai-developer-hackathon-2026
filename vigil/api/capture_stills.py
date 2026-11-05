"""Masked stills from real captures, for tap-to-protect and the camera preview (LAN only).

A still is one frame read from a capture's masked window part (never the raw ring clip).
It is written once under `data/stills/` (gitignored) and kept only if the pre-upload privacy
guard passes: the camera's privacy review is approved and every pixel inside its privacy
polygons is masked. A still id is `<capture_id>@<milliseconds>` on the capture's clock.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from vigil.ingest.config import privacy_polygons
from vigil.ingest.review import require_privacy_review

CAPTURE_ID = re.compile(r"[a-z0-9_-]{1,128}")
STILL_ID = re.compile(r"(?P<capture>[a-z0-9_-]{1,128})@(?P<ms>\d{1,9})")
MAX_LISTED = 6


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _data(settings: Any) -> Path:
    return Path(settings.data_dir)


def still_path(settings: Any, capture_id: str, ms: int) -> Path:
    return _data(settings) / "stills" / f"{capture_id}__{ms}.png"


def _windows(settings: Any, capture_id: str) -> tuple[Path, list[dict[str, Any]]] | None:
    if not CAPTURE_ID.fullmatch(capture_id) or capture_id.startswith("moment-"):
        return None
    folder = _data(settings) / "windows" / capture_id
    if folder.is_symlink() or not folder.is_dir():
        return None
    rows = _read(folder / "windows.json")
    if not isinstance(rows, list):
        return None
    return folder, [w for w in rows if isinstance(w, dict) and w.get("path")]


def person_time(settings: Any, capture_id: str) -> float | None:
    """Middle of the first person track in the capture's results, on the capture clock."""
    data = _read(_data(settings) / "results" / capture_id / "visits.json")
    if not isinstance(data, dict):
        return None
    for track in data.get("tracks") or []:
        if not isinstance(track, dict) or "person" not in str(track.get("phrase") or ""):
            continue
        try:
            t0 = float(track.get("t_first"))
            t1 = float(track.get("t_last", t0))
        except (TypeError, ValueError):
            continue
        return (t0 + t1) / 2
    return None


def extract(settings: Any, cfg: Any, capture_id: str, t: float | None = None) -> dict | None:
    """The masked still of a capture at `t` (seconds), or None when it cannot be shown safely."""
    found = _windows(settings, capture_id)
    if found is None or cfg is None:
        return None
    folder, windows = found
    if not windows:
        return None
    if t is None:
        t = person_time(settings, capture_id)
    if t is None:
        first = windows[0]
        t = (float(first.get("t0", 0)) + float(first.get("t1", 0))) / 2
    lo = min(float(w.get("t0", 0)) for w in windows)
    hi = max(float(w.get("t1", 0)) for w in windows)
    t = min(max(float(t), lo), hi)
    window = next(
        (w for w in windows if float(w.get("t0", 0)) <= t <= float(w.get("t1", -1))), windows[0]
    )
    try:
        camera = cfg.camera(str(window.get("camera_id")))
    except (KeyError, AttributeError):
        return None
    polygons = privacy_polygons(cfg, camera.id, Path(settings.config_path).parent / "privacy")
    try:
        require_privacy_review(camera, polygons)
    except Exception:  # unreviewed camera: never shown
        return None
    ms = round(t * 1000)
    path = still_path(settings, capture_id, ms)
    if not path.is_file() and not _write(folder, window, t, camera, polygons, path):
        return None
    try:
        import cv2

        image = cv2.imread(str(path))
        height, width = image.shape[:2]
        visible = _visible_box(image)
    except Exception:
        return None
    return {
        "still_id": f"{capture_id}@{ms}",
        "capture_id": capture_id,
        "camera_id": camera.id,
        "name": camera.name,
        "frame_ts": round(t, 3),
        "width": int(width),
        "height": int(height),
        "camera_width": camera.width,
        "camera_height": camera.height,
        "url": f"/api/ui/capture-stills/{capture_id}/{ms}.png",
        "visible": visible,
        "path": path,
    }


def _visible_box(image: Any) -> list[float]:
    """[x0, y0, x1, y1] as fractions: the box around unmasked (non-black) pixels."""
    gray = image.max(axis=2) if image.ndim == 3 else image
    rows = (gray > 8).mean(axis=1) > 0.02
    cols = (gray > 8).mean(axis=0) > 0.02
    if not rows.any() or not cols.any():
        return [0.0, 0.0, 1.0, 1.0]
    h, w = gray.shape
    y0, y1 = int(rows.argmax()), int(h - rows[::-1].argmax())
    x0, x1 = int(cols.argmax()), int(w - cols[::-1].argmax())
    return [round(x0 / w, 4), round(y0 / h, 4), round(x1 / w, 4), round(y1 / h, 4)]


def _write(folder: Path, window: dict, t: float, camera: Any, polygons: list, path: Path) -> bool:
    import cv2

    from vigil.faces.enroll import _VideoFrames, _window_path
    from vigil.ingest.privacy import PrivacyViolation, assert_uploadable

    reader = _VideoFrames()
    try:
        frame = reader(_window_path(folder, str(window["path"])), t - float(window.get("t0", 0)))
    finally:
        reader.close()
    if frame is None:
        return False
    # Defence in depth: the part is already masked; black the polygons again on the frame and
    # store it lossless, so no compression ringing reaches a masked pixel.
    import numpy as np

    sx, sy = frame.shape[1] / camera.width, frame.shape[0] / camera.height
    for poly in polygons:
        pts = np.array([[round(x * sx), round(y * sy)] for x, y in poly], dtype=np.int32)
        if len(pts) >= 3:
            cv2.fillPoly(frame, [pts], (0, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.png")
    if not cv2.imwrite(str(tmp), frame):
        return False
    try:
        assert_uploadable(tmp, polygons, ref_size=(camera.width, camera.height))
    except (PrivacyViolation, OSError, ValueError):
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(path)
    return True


def resolve(settings: Any, still_id: str) -> tuple[str, Path] | None:
    """(capture_id, path) for a still that was already extracted and checked."""
    match = STILL_ID.fullmatch(still_id or "")
    if not match:
        return None
    path = still_path(settings, match["capture"], int(match["ms"]))
    return (match["capture"], path) if path.is_file() else None


def recent_captures(settings: Any, camera_id: str | None = None) -> list[str]:
    """Analysed real captures, newest first (results with tracks), optionally for one camera."""
    root = _data(settings) / "results"
    if not root.is_dir():
        return []
    rows = []
    for folder in root.iterdir():
        name = folder.name
        if name.startswith("moment-") or folder.is_symlink() or not folder.is_dir():
            continue
        if not CAPTURE_ID.fullmatch(name) or (camera_id and not name.startswith(camera_id + "-")):
            continue
        if not (folder / "visits.json").is_file():
            continue
        rows.append((folder.stat().st_mtime, name))
    return [name for _, name in sorted(rows, reverse=True)]


def capture_stills(settings: Any, cfg: Any, prefer: str | None = None, t: float | None = None):
    """The preferred capture's still first, then one per camera from the newest captures."""
    out: list[dict] = []
    if prefer:
        still = extract(settings, cfg, prefer, t)
        if still:
            out.append(still)
    seen = {s["camera_id"] for s in out}
    for capture_id in recent_captures(settings):
        if len(out) >= MAX_LISTED:
            break
        camera = capture_id.rsplit("-", 2)[0]
        if camera in seen:
            continue
        still = extract(settings, cfg, capture_id)
        if still:
            out.append(still)
            seen.add(still["camera_id"])
    return out


def capture_counts(settings: Any) -> dict[str, int]:
    """Event clips captured per camera (capture folders with a capture.json)."""
    root = _data(settings) / "windows"
    counts: dict[str, int] = {}
    if not root.is_dir():
        return counts
    for folder in root.iterdir():
        if folder.name.startswith("moment-") or not (folder / "capture.json").is_file():
            continue
        data = _read(folder / "capture.json")
        camera = data.get("camera_id") if isinstance(data, dict) else None
        camera = camera or folder.name.rsplit("-", 2)[0]
        counts[camera] = counts.get(camera, 0) + 1
    return counts
