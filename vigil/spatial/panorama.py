"""Duo geometry uses two panoramic sections, never a single pinhole frame."""

import math

import numpy as np

from vigil.models import CameraCfg, Position, TrackFrame


def section_for_pixel(x: float, width: int) -> tuple[str, float]:
    if not 0 <= x < width:
        raise ValueError("pixel outside panoramic frame")
    half = width / 2
    return ("left", x) if x < half else ("right", x - half)


def rectify_section(u: float, v: float, width: float, hfov_deg: float) -> tuple[float, float]:
    """Nominal cylindrical horizontal angle to a section-local rectified coordinate."""
    if not 0 < hfov_deg < 180:
        raise ValueError("section field of view must be between 0 and 180 degrees")
    angle = (u / width - 0.5) * math.radians(hfov_deg)
    focal = width / (2 * math.tan(math.radians(hfov_deg) / 2))
    return width / 2 + focal * math.tan(angle), v


def locate_panorama(frame: TrackFrame, camera: CameraCfg, track_id: str) -> Position | None:
    """No invented calibration: absent section homography/error means no estimate."""
    x = (frame.box.x1 + frame.box.x2) / 2
    section, u = section_for_pixel(x, camera.width)
    if frame.clipped:
        return None
    matrix = camera.panorama_homographies.get(section)
    if matrix is None or camera.panorama_r95_m is None:
        return None
    homography = np.asarray(matrix, dtype=float)
    if homography.shape != (3, 3) or not np.isfinite(homography).all():
        raise ValueError("panoramic section needs a finite 3x3 ground homography")
    if not math.isfinite(camera.panorama_r95_m) or camera.panorama_r95_m <= 0:
        raise ValueError("section uncertainty must be finite and positive")
    ru, rv = rectify_section(u, frame.box.y2, camera.width / 2, camera.panorama_hfov_deg)
    result = homography @ [ru, rv, 1]
    if abs(result[2]) < 1e-9:
        return None
    px, pz = result[:2] / result[2]
    edge_distance = min(u, camera.width / 2 - u) / (camera.width / 4)
    penalty = 1 + 2 * (1 - max(0, min(1, edge_distance))) ** 2
    return Position(
        track_id=track_id,
        t=frame.t,
        x=float(px),
        y=0,
        z=float(pz),
        r95=camera.panorama_r95_m * penalty,
        method="footpoint",
        cameras=[camera.id],
        flags=[
            "panoramic_section:" + section,
            "fov_nominal",
            "ground_homography",
            "low_confidence",
        ],
    )
