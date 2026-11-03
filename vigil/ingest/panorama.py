"""Full stitched Duo frames for perception; sectioning is geometry-only."""

from pathlib import Path

import cv2
import numpy as np

from vigil.ingest.media import iter_frames
from vigil.ingest.windows import cut_windows
from vigil.models import CameraCfg, Window


def illumination_mode(path: Path | str) -> str:
    """Record observable chroma mode, including a floodlight change within the clip."""
    modes = set()
    for _, _, frame in iter_frames(path):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        visible = hsv[:, :, 2] > 24
        if np.count_nonzero(visible) < 32:
            continue
        modes.add("colour" if np.percentile(hsv[:, :, 1][visible], 90) > 20 else "infrared")
    if len(modes) == 2:
        return "mixed"
    return next(iter(modes), "unknown")


def cut_camera_windows(
    src: Path | str, out_dir: Path, camera: CameraCfg, **kwargs: object
) -> list[Window]:
    windows = cut_windows(
        src,
        out_dir,
        camera.id,
        max_width=1920 if camera.frame_layout == "duo_panorama" else 1280,
        polygons=camera.privacy,
        ref_size=(camera.width, camera.height),
        **kwargs,
    )
    for window in windows:
        window.illumination = illumination_mode(window.path)
    return windows
