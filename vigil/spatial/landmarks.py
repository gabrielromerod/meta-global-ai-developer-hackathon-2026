"""SAM 3.1 landmark proposals for camera calibration (FR-037, UC-10; spec 7, 9.5).

On a camera still, SAM 3.1 is asked for fixed landmarks with one concept request per noun
phrase (``door``, ``gate``, ``fence post``, ``window``; comma lists return zero matches).
Each returned mask becomes a proposal with candidate points the installer can accept: the
four mask corners (extreme points along the diagonals), the base (median x of the lowest 5%
of the mask, at its lowest row: where a post or door frame meets the ground) and the
centroid. The installer accepts 6 points and clicks each once on the mesh; ``to_pair``
turns an accepted point and its mesh click into the pair ``calibrate_extrinsics`` solves.

Requests are built with ``vigil.meta.sam``'s concept builder (phrase validation, model,
``include_confidence`` as the string ``"true"``), with the still sent as a base64 data URL
``input_image`` in place of the video part; output is parsed with
``vigil.meta.sam.parse_image_output``. Every call goes through the injected client
(``MetaClient``: cache, budget guard, ledger). This module never retries.
"""

from __future__ import annotations

import base64
import logging
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vigil.meta.sam import (
    SAM_MODEL,
    SamClient,
    SamParseError,
    build_image_concept_request,
    parse_image_output,
    response_payload,
)
from vigil.models import Box, CameraCfg
from vigil.spatial.calibrate import MarkerPair
from vigil.spatial.geometry import rle_decode

log = logging.getLogger(__name__)

LANDMARK_CONCEPTS: tuple[str, ...] = ("door", "gate", "fence post", "window")
"""FR-037 concept prompts, one request each."""
LANDMARK_PURPOSE = "landmark_proposal"
MIN_CONFIDENCE = 0.3
MAX_PER_CONCEPT = 6
MIN_MASK_PX = 50
"""Masks smaller than this give no stable corners."""
BASE_FRACTION = 0.05

PointKind = Literal["corner_tl", "corner_tr", "corner_br", "corner_bl", "base", "centroid"]

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class LandmarkPoint(BaseModel):
    """One candidate landmark pixel in the processed frame."""

    model_config = ConfigDict(extra="forbid")

    id: str
    """``<proposal id>:<kind>``, unique per still."""
    kind: PointKind
    u: float
    v: float


class LandmarkProposal(BaseModel):
    """A SAM 3.1 landmark mask on one camera still (spec 9.5 ``LandmarkProposal``)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    """``<camera id>:<concept>:<SAM object id>``."""
    camera_id: str
    concept: str
    obj_id: int
    confidence: float | None = None
    box: Box
    mask_rle: str
    """COCO RLE of the full-frame mask (width x height)."""
    width: int
    height: int
    points: list[LandmarkPoint] = Field(default_factory=list)


def build_landmark_request(image_ref: str, concept: str) -> dict:
    """One concept request on one still (:func:`vigil.meta.sam.build_image_concept_request`):
    the phrase as ``input_text`` and ``{"type": "input_image", "image_url": image_ref}``."""
    return build_image_concept_request(image_ref, concept, include_confidence=True)


def mask_points(mask: np.ndarray) -> list[tuple[PointKind, float, float]]:
    """Candidate points of a boolean mask: 4 corners, base and centroid ([] if empty).

    Corners are the extreme mask pixels along the image diagonals (top-left minimises
    x + y, bottom-right maximises it; top-right maximises x - y, bottom-left minimises it).
    """
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return []
    s, d = xs + ys, xs - ys
    k = max(1, math.ceil(BASE_FRACTION * len(ys)))
    low = np.argsort(ys, kind="stable")[-k:]
    out: list[tuple[PointKind, float, float]] = []
    for kind, i in (
        ("corner_tl", int(np.argmin(s))),
        ("corner_tr", int(np.argmax(d))),
        ("corner_br", int(np.argmax(s))),
        ("corner_bl", int(np.argmin(d))),
    ):
        out.append((kind, float(xs[i]), float(ys[i])))  # type: ignore[arg-type]
    out.append(("base", float(np.median(xs[low])), float(ys[low].max())))
    out.append(("centroid", float(xs.mean()), float(ys.mean())))
    return out


def _still_ref(still: Path) -> tuple[str, int, int]:
    data = Path(still).read_bytes()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"could not decode the still image {still}")
    mime = _MIME.get(Path(still).suffix.lower(), "image/jpeg")
    ref = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    return ref, int(img.shape[1]), int(img.shape[0])


def _camera(camera: CameraCfg | str | None) -> tuple[str, tuple[int, int] | None]:
    if isinstance(camera, CameraCfg):
        return camera.id, (camera.width, camera.height)
    return (camera or "camera"), None


def propose_landmarks(
    client: SamClient,
    still: Path,
    camera: CameraCfg | str | None = None,
    *,
    concepts: Sequence[str] = LANDMARK_CONCEPTS,
    min_confidence: float = MIN_CONFIDENCE,
    max_per_concept: int = MAX_PER_CONCEPT,
) -> list[LandmarkProposal]:
    """Ask SAM 3.1 for fixed landmarks on a camera still (FR-037).

    One request per concept. Masks under ``min_confidence`` or ``MIN_MASK_PX`` pixels are
    dropped; each concept keeps its ``max_per_concept`` most confident masks. A concept
    whose output does not parse is skipped with a warning; HTTP errors (including 400) and
    budget refusals propagate. The still must be in the processed frame of ``camera``
    (pixel coordinates feed the calibration directly).
    """
    camera_id, size = _camera(camera)
    ref, width, height = _still_ref(still)
    if size is not None and size != (width, height):
        raise ValueError(
            f"the still is {width}x{height} but camera {camera_id} is processed at "
            f"{size[0]}x{size[1]}: capture the still from the processed stream"
        )
    out: list[LandmarkProposal] = []
    for concept in concepts:
        body = build_landmark_request(ref, concept)
        raw: Any = client.responses(SAM_MODEL, body, LANDMARK_PURPOSE, stream=True)
        try:
            masks = parse_image_output(response_payload(raw, LANDMARK_PURPOSE), width, height)
        except SamParseError as err:
            log.warning("SAM 3.1 landmark output for %r did not parse: %s", concept, err)
            continue
        found: list[LandmarkProposal] = []
        for m in masks:
            if m.confidence is not None and m.confidence < min_confidence:
                continue
            mask = rle_decode(m.mask_rle, height, width)
            if int(mask.sum()) < MIN_MASK_PX:
                continue
            pid = f"{camera_id}:{concept}:{m.obj_id}"
            found.append(
                LandmarkProposal(
                    id=pid,
                    camera_id=camera_id,
                    concept=concept,
                    obj_id=m.obj_id,
                    confidence=m.confidence,
                    box=m.box,
                    mask_rle=m.mask_rle,
                    width=width,
                    height=height,
                    points=[
                        LandmarkPoint(id=f"{pid}:{kind}", kind=kind, u=u, v=v)
                        for kind, u, v in mask_points(mask)
                    ],
                )
            )
        found.sort(key=lambda p: -(p.confidence if p.confidence is not None else 0.0))
        out.extend(found[:max_per_concept])
    return out


def candidate_points(proposals: Sequence[LandmarkProposal]) -> list[LandmarkPoint]:
    """Every candidate point of every proposal, in proposal order."""
    return [pt for p in proposals for pt in p.points]


def to_pair(point: LandmarkPoint, world: Sequence[float]) -> MarkerPair:
    """An accepted landmark point and its one mesh click, as a calibration pair."""
    x, y, z = (float(c) for c in world)
    return MarkerPair(u=point.u, v=point.v, x=x, y=y, z=z, id=point.id)
