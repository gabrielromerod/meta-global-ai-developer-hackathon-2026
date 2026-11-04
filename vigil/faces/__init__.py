"""Opt-in local face templates for recurring visitors (never sent to a model API)."""

from __future__ import annotations

from vigil.faces.engine import (
    DETECTOR_FILE,
    MAX_FACES_PER_TRACK,
    MIN_FACE_PX,
    RECOGNIZER_FILE,
    SAME_FACE_COSINE,
    FaceBox,
    FaceEngine,
    FacesUnavailable,
    TrackFace,
    best_faces_for_track,
    cosine,
    crop_face,
    head_region,
)
from vigil.faces.store import FaceStore, clean_name

__all__ = [
    "DETECTOR_FILE",
    "MAX_FACES_PER_TRACK",
    "MIN_FACE_PX",
    "RECOGNIZER_FILE",
    "SAME_FACE_COSINE",
    "FaceBox",
    "FaceEngine",
    "FaceStore",
    "FacesUnavailable",
    "TrackFace",
    "best_faces_for_track",
    "clean_name",
    "cosine",
    "crop_face",
    "head_region",
]
