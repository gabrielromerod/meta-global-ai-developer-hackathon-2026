"""Overlay JSON for the synced player canvas (FR-018).

Shape (all keys sorted deterministically, NFR-011)::

    {"version": 1,
     "cameras": {
        "<camera_id>": {
           "width": 1280, "height": 720,            # only when sizes are given
           "tracks": {"<track_id>": {"tag": "T1", "cls": "person"}},
           "frames": [{"t": 12.3,
                       "objects": [{"track_id": "...", "tag": "T1", "cls": "person",
                                    "box": [x1, y1, x2, y2],   # half-open pixels
                                    "mask_rle": "...",         # COCO counts, if present
                                    "confidence": 0.91,        # if present
                                    "clipped": true}]}]}}}     # only when true

Times are seconds on the aligned session clock; the player draws the frame whose ``t`` is
nearest its ``currentTime`` plus the camera's offset.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vigil.models import Track

OVERLAY_VERSION = 1


def overlay_json(
    tracks: Sequence[Track], sizes: Mapping[str, tuple[int, int]] | None = None
) -> dict:
    """Per camera and frame time: boxes (+ mask RLE when present), track tag and class."""
    cameras: dict[str, dict] = {}
    frames_by_cam: dict[str, dict[float, list[dict]]] = {}
    for tr in sorted(tracks, key=lambda t: (t.camera_id, t.id)):
        cam = cameras.setdefault(tr.camera_id, {"tracks": {}, "frames": []})
        cam["tracks"][tr.id] = {"tag": tr.tag, "cls": tr.cls}
        by_t = frames_by_cam.setdefault(tr.camera_id, {})
        for f in tr.frames:
            obj: dict = {
                "track_id": tr.id,
                "tag": tr.tag,
                "cls": tr.cls,
                "box": [float(f.box.x1), float(f.box.y1), float(f.box.x2), float(f.box.y2)],
            }
            if f.mask_rle is not None:
                obj["mask_rle"] = f.mask_rle
            if f.confidence is not None:
                obj["confidence"] = f.confidence
            if f.clipped:
                obj["clipped"] = True
            by_t.setdefault(round(f.t, 3), []).append(obj)

    for cam_id, cam in cameras.items():
        if sizes and cam_id in sizes:
            cam["width"], cam["height"] = (int(v) for v in sizes[cam_id])
        by_t = frames_by_cam.get(cam_id, {})
        cam["frames"] = [
            {"t": t, "objects": sorted(by_t[t], key=lambda o: o["track_id"])} for t in sorted(by_t)
        ]
    return {"version": OVERLAY_VERSION, "cameras": dict(sorted(cameras.items()))}
