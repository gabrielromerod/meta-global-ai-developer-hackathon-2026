"""Make one aligned, silent, masked camera video from overlapping session windows."""

from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from vigil.ingest.media import MediaError, iter_frames, probe
from vigil.ingest.privacy import assert_uploadable, mask_clip
from vigil.models import CameraCfg, Window


def session_clip(
    windows: list[Window],
    cam: CameraCfg,
    dst: Path,
    t0: float,
    t1: float,
    fps: float = 10,
) -> Path:
    mine = sorted((w for w in windows if w.camera_id == cam.id), key=lambda w: (w.t0, w.id))
    if not mine or any(not w.path for w in mine):
        raise ValueError(f"camera {cam.id}: masked window media missing")
    ref = (cam.width, cam.height)
    for w in mine:
        assert_uploadable(w.path, cam.privacy, ref_size=ref)
    info = probe(mine[0].path)
    black = np.zeros((info.height, info.width, 3), dtype=np.uint8)
    count = round((t1 - t0) * fps)
    written = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="vigil-session-") as scratch:
        raw = Path(scratch) / "timeline.avi"
        writer = cv2.VideoWriter(
            str(raw), cv2.VideoWriter_fourcc(*"MJPG"), fps, (info.width, info.height)
        )
        if not writer.isOpened():
            raise MediaError("cannot open aligned video encoder")
        try:
            for w in mine:
                for _, relative_t, frame in iter_frames(w.path):
                    index = round((w.t0 + relative_t - t0) * fps)
                    if index < written or index >= count or relative_t >= w.t1 - w.t0:
                        continue
                    while written < index:
                        writer.write(black)  # missing observations remain blank
                        written += 1
                    writer.write(cv2.resize(frame, (info.width, info.height)))
                    written += 1
            while written < count:
                writer.write(black)
                written += 1
        finally:
            writer.release()
        mask_clip(raw, dst, cam.privacy, ref_size=ref)
    assert_uploadable(dst, cam.privacy, ref_size=ref)
    return dst
