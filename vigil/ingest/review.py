"""Owner review bound to the exact still and mask definition; no network operations."""

import hashlib
import json
import re
from pathlib import Path

from shapely.geometry import Polygon as Shape
from shapely.ops import unary_union

from vigil.ingest.media import probe
from vigil.models import CameraCfg, Polygon


def privacy_digest(camera: CameraCfg, polygons: list[Polygon]) -> str:
    payload = {
        "camera_id": camera.id,
        "size": [camera.width, camera.height],
        "polygons": polygons,
        "regions": camera.privacy_regions,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def require_privacy_review(camera: CameraCfg, polygons: list[Polygon] | None = None) -> None:
    if camera.evidence_kind == "fixture":
        return
    polygons = camera.privacy if polygons is None else polygons
    if not camera.privacy_reviewed or not re.fullmatch(
        r"[a-f0-9]{64}", camera.privacy_still_sha256 or ""
    ):
        raise ValueError(f"camera {camera.id}: owner privacy review of a real still is required")
    if camera.privacy_polygons_sha256 != privacy_digest(camera, polygons):
        raise ValueError(
            f"camera {camera.id}: privacy polygons changed; repeat owner privacy review"
        )
    required = {"timestamp_watermark"}
    if camera.frame_layout == "duo_panorama":
        required |= {
            "sky_ridgeline",
            "opposite_houses_cars",
            "neighbour_left",
            "neighbour_right",
            "curb_numbers",
        }
    if not required <= camera.privacy_regions.keys():
        raise ValueError(f"camera {camera.id}: required anti-doxxing regions are missing")
    union = unary_union([Shape(p) for p in polygons])
    if not all(union.covers(Shape(camera.privacy_regions[name])) for name in required):
        raise ValueError(
            f"camera {camera.id}: masks do not cover the reviewed anti-doxxing regions"
        )


def require_silent_source(path: Path | str) -> None:
    if probe(path).audio_streams:
        raise ValueError("audio stream at ingest is an error; disable camera audio and re-export")
