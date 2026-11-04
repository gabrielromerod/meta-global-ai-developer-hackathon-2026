"""Enrol faces from one processed capture into the local face store.

Spec change 2026-11-04 (face templates). Only person tracks are sampled, and only on frames
whose foot point (bottom centre of the SAM box) lies in a property zone: a frame in a
`perimeter` zone (the street strip) or outside every zone is never read, so passers-by on the
street get no template. Frames come from the capture's own video parts on the home box;
nothing here calls a model API. Faces narrower than `MIN_FACE_PX` are counted, not kept.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from vigil.faces.engine import MIN_FACE_PX, FaceBox, best_faces_for_track, crop_face
from vigil.faces.store import FaceStore
from vigil.models import CameraCfg

SAMPLES_PER_TRACK = 12
OUTSIDE_PROPERTY = frozenset({"perimeter"})

Box = tuple[float, float, float, float]
ReadFrame = Callable[[Path, float], "np.ndarray | None"]


def _inside(x: float, y: float, poly: Iterable[tuple[float, float]]) -> bool:
    pts = list(poly)
    hit = False
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


def foot_zone_kind(camera: CameraCfg, box: Box, *, scale: tuple[float, float]) -> str | None:
    """Kind of the zone under the box's foot point, in config pixels; None outside every zone.

    `scale` maps the box's pixels to the camera config's pixels. When zones overlap, a
    `perimeter` zone wins, so a doubtful frame is treated as the street.
    """
    x = (box[0] + box[2]) / 2 * scale[0]
    y = box[3] * scale[1]
    kinds = {camera.zone_kind(z) for z, poly in camera.zones.items() if _inside(x, y, poly)}
    if not kinds:
        return None
    return "perimeter" if "perimeter" in kinds else sorted(kinds)[0]


class _VideoFrames:
    """Reads one frame at an offset (seconds) from a local mp4 with OpenCV."""

    def __init__(self) -> None:
        self._open: dict[Path, Any] = {}

    def __call__(self, path: Path, offset: float) -> np.ndarray | None:
        import cv2

        cap = self._open.get(path)
        if cap is None:
            cap = self._open[path] = cv2.VideoCapture(str(path))
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, offset) * 1000.0)
        ok, frame = cap.read()
        return frame if ok else None

    def close(self) -> None:
        for cap in self._open.values():
            cap.release()
        self._open.clear()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _window_path(windows_dir: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_file() else windows_dir / path.name


def enroll_capture(
    capture_id: str,
    results_dir: Path,
    windows_dir: Path,
    cameras: Iterable[CameraCfg],
    store: FaceStore,
    *,
    detect: Callable[..., list[FaceBox]],
    embed: Callable[[np.ndarray, FaceBox], np.ndarray],
    crop: Callable[[np.ndarray, FaceBox], bytes] = crop_face,
    read_frame: ReadFrame | None = None,
    samples_per_track: int = SAMPLES_PER_TRACK,
) -> dict[str, Any]:
    """Sample each person track inside the property, keep its best faces, match a profile."""
    report: dict[str, Any] = {"capture_id": capture_id, "person_tracks": 0, "tracks_inside": 0,
                              "frames_read": 0, "faces_kept": 0, "faces_too_small": 0,
                              "profiles": []}  # fmt: skip
    data = _read_json(results_dir / "visits.json")
    windows = _read_json(windows_dir / "windows.json")
    if not isinstance(data, dict) or not isinstance(windows, list):
        return report
    cams = {c.id: c for c in cameras}
    start = datetime.fromisoformat(str(data.get("session_start")))
    people = {
        t["id"]: t
        for t in data.get("tracks") or []
        if isinstance(t, dict) and str(t.get("phrase") or t.get("cls")) == "person"
    }
    report["person_tracks"] = len(people)
    reader = read_frame or _VideoFrames()

    def counting(frame: np.ndarray, *, roi: Box | None = None) -> list[FaceBox]:
        faces = detect(frame, roi=roi)
        report["faces_too_small"] += sum(1 for f in faces if f.box[2] < MIN_FACE_PX)
        return faces

    try:
        overlays = (data.get("overlays") or {}).get("cameras") or {}
        for camera_id, overlay in overlays.items():
            camera = cams.get(camera_id)
            if camera is None or not camera.zones:
                continue
            ow, oh = float(overlay.get("width") or 0), float(overlay.get("height") or 0)
            if ow <= 0 or oh <= 0:
                continue
            scale = (camera.width / ow, camera.height / oh)
            inside: dict[str, list[tuple[float, Box]]] = {}
            for frame in overlay.get("frames") or []:
                for obj in frame.get("objects") or []:
                    tid = obj.get("track_id")
                    if tid not in people or len(obj.get("box") or []) != 4:
                        continue
                    box = tuple(float(v) for v in obj["box"])
                    kind = foot_zone_kind(camera, box, scale=scale)  # type: ignore[arg-type]
                    if kind is not None and kind not in OUTSIDE_PROPERTY:
                        inside.setdefault(tid, []).append((float(frame["t"]), box))  # type: ignore[arg-type]
            cam_windows = [
                w for w in windows if isinstance(w, dict) and w.get("camera_id") == camera_id
            ]
            for tid, hits in inside.items():
                report["tracks_inside"] += 1
                hits.sort()
                step = max(1, len(hits) // samples_per_track)
                picked = hits[::step][:samples_per_track]
                faces = best_faces_for_track(
                    _samples(picked, cam_windows, windows_dir, reader, (ow, oh), report),
                    detect=counting, embed=embed, crop=crop,
                )  # fmt: skip
                report["faces_kept"] += len(faces)
                seen_at = start + timedelta(seconds=picked[0][0])
                pid = store.add_track_faces(capture_id, tid, seen_at, faces)
                if pid and pid not in report["profiles"]:
                    report["profiles"].append(pid)
    finally:
        if isinstance(reader, _VideoFrames):
            reader.close()
    return report


def _samples(picked, cam_windows, windows_dir, reader, overlay_size, report):
    """(t, frame, person box in frame pixels) for each picked overlay hit."""
    for t, box in picked:
        window = next(
            (w for w in cam_windows if float(w.get("t0", 0)) <= t <= float(w.get("t1", -1))), None
        )
        if window is None or not window.get("path"):
            continue
        frame = reader(_window_path(windows_dir, str(window["path"])), t - float(window["t0"]))
        if frame is None:
            continue
        report["frames_read"] += 1
        sx, sy = frame.shape[1] / overlay_size[0], frame.shape[0] / overlay_size[1]
        yield t, frame, (box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy)
