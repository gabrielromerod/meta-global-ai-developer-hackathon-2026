"""Burn code-assigned SAM tags into masked clips before Spark sees them (FR-009)."""

from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from vigil.ingest.media import MediaError, iter_frames, probe
from vigil.ingest.privacy import assert_uploadable, mask_clip
from vigil.models import Box, CameraCfg, Track, Window

YELLOW = (0, 255, 255)
BLACK = (0, 0, 0)
GAP = 6


def label_style(frame_width: int) -> tuple[float, int]:
    """Font scale and stroke for a tag Spark can read on this frame width."""
    scale = max(0.6, 1.3 * frame_width / 1920)
    return scale, max(2, round(scale * 2.5))


def _scaled(polygons: Sequence, frame: tuple[int, int], ref_size: tuple[int, int]) -> list:
    sx, sy = frame[0] / ref_size[0], frame[1] / ref_size[1]
    return [
        np.array([[px * sx, py * sy] for px, py in poly], dtype=np.float32) for poly in polygons
    ]


def _clear(rect: tuple[float, float, float, float], frame: tuple[int, int], polys: list) -> bool:
    x1, y1, x2, y2 = rect
    if x1 < 0 or y1 < 0 or x2 > frame[0] or y2 > frame[1]:
        return False
    points = [(x, y) for x in np.linspace(x1, x2, 5) for y in np.linspace(y1, y2, 3)]
    return not any(
        cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0
        for poly in polys
        for x, y in points
    )


def label_anchor(
    box: Box,
    size: tuple[int, int],
    frame: tuple[int, int],
    polygons: Sequence,
    *,
    ref_size: tuple[int, int],
) -> tuple[int, int]:
    """Text origin (bottom-left) for a tag label that the privacy mask will not cover.

    Tries above the box, inside its top, below it, then inside its bottom; the first spot
    whose whole label lies in the frame and outside every privacy polygon wins.
    """
    w, h = size
    x = int(min(max(0, box.x1), max(0, frame[0] - w)))
    xi = int(min(max(0, box.x1 + GAP), max(0, frame[0] - w)))
    candidates = [
        (x, int(box.y1 - GAP)),
        (xi, int(box.y1 + h + GAP)),
        (x, int(box.y2 + h + GAP)),
        (xi, int(box.y2 - GAP)),
    ]
    polys = _scaled(polygons, frame, ref_size)
    for cx, cy in candidates:
        if _clear((cx, cy - h, cx + w, cy), frame, polys):
            return cx, cy
    return xi, int(min(max(h, box.y1 + h + GAP), frame[1]))


def burn_tags(window: Window, tracks: list[Track], cam: CameraCfg, dst: Path) -> Path:
    """Draw only observed boxes/tags, then reapply privacy after drawing and encoding."""
    if not window.path:
        raise ValueError(f"window {window.id} has no media")
    ref = (cam.width, cam.height)
    assert_uploadable(window.path, cam.privacy, ref_size=ref)
    info = probe(window.path)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="vigil-tags-") as scratch:
        intermediate = Path(scratch) / "tags.avi"
        writer = cv2.VideoWriter(
            str(intermediate),
            cv2.VideoWriter_fourcc(*"MJPG"),
            info.fps,
            (info.width, info.height),
        )
        if not writer.isOpened():
            raise MediaError("cannot open tag clip encoder")
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale, thickness = label_style(info.width)
        frame_size = (info.width, info.height)
        sx, sy = info.width / cam.width, info.height / cam.height
        try:
            for _, relative_t, frame in iter_frames(window.path):
                t = window.t0 + relative_t
                for track in tracks:
                    if track.camera_id != cam.id or not track.frames or not track.tag:
                        continue
                    f = min(track.frames, key=lambda f: abs(f.t - t))
                    if abs(f.t - t) > 0.21:
                        continue
                    # Tracks are in the camera's configured size; this clip may be smaller.
                    b = Box(x1=f.box.x1 * sx, y1=f.box.y1 * sy, x2=f.box.x2 * sx, y2=f.box.y2 * sy)
                    p1, p2 = (round(b.x1), round(b.y1)), (round(b.x2), round(b.y2))
                    cv2.rectangle(frame, p1, p2, YELLOW, max(2, thickness - 1))
                    (tw, th), base = cv2.getTextSize(track.tag, font, scale, thickness)
                    size = (tw + 2 * GAP, th + base + GAP)
                    ax, ay = label_anchor(b, size, frame_size, cam.privacy, ref_size=ref)
                    cv2.rectangle(frame, (ax, ay - size[1]), (ax + size[0], ay), BLACK, -1)
                    cv2.putText(
                        frame,
                        track.tag,
                        (ax + GAP, ay - base - GAP // 2),
                        font,
                        scale,
                        YELLOW,
                        thickness,
                    )
                writer.write(frame)
        finally:
            writer.release()
        mask_clip(intermediate, dst, cam.privacy, ref_size=ref)
    assert_uploadable(dst, cam.privacy, ref_size=ref)
    return dst
