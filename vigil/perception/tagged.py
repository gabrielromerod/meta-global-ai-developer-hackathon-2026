"""Burn code-assigned SAM tags into masked clips before Spark sees them (FR-009)."""

from pathlib import Path
from tempfile import TemporaryDirectory

import cv2

from vigil.ingest.media import MediaError, iter_frames, probe
from vigil.ingest.privacy import assert_uploadable, mask_clip
from vigil.models import CameraCfg, Track, Window


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
        try:
            for _, relative_t, frame in iter_frames(window.path):
                t = window.t0 + relative_t
                for track in tracks:
                    if track.camera_id != cam.id or not track.frames or not track.tag:
                        continue
                    f = min(track.frames, key=lambda f: abs(f.t - t))
                    if abs(f.t - t) > 0.21:
                        continue
                    b = f.box
                    p1, p2 = (round(b.x1), round(b.y1)), (round(b.x2), round(b.y2))
                    cv2.rectangle(frame, p1, p2, (0, 255, 255), 2)
                    cv2.putText(
                        frame,
                        track.tag,
                        (p1[0], max(14, p1[1] - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 255, 255),
                        2,
                    )
                writer.write(frame)
        finally:
            writer.release()
        mask_clip(intermediate, dst, cam.privacy, ref_size=ref)
    assert_uploadable(dst, cam.privacy, ref_size=ref)
    return dst
