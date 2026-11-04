"""Local face detection, embedding and crops for the opt-in recurring-visitor feature.

YuNet finds faces and SFace turns each into a 128-d template, both through OpenCV on this
machine. The ONNX files live under `data/models/` (gitignored) and load lazily on first
use; when one is missing every call raises `FacesUnavailable` naming it. Nothing here is
ever sent to a model API, and no template is a name: it only says two crops look alike.

`best_faces_for_track` is pure: the detector and embedder are passed in, so tests run on
fakes and never need the model files.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"
SCORE_THRESHOLD = 0.8
MIN_FACE_PX = 24
"""Faces narrower than this carry too little detail for a usable template; skipped."""
MAX_FACES_PER_TRACK = 5
HEAD_FRACTION = 0.45
"""Faces are only searched in the top 45% of a person box (the head region)."""
SAME_FACE_COSINE = 0.363
"""SFace's published cosine threshold (OpenCV zoo, LFW): at or above it, same person."""
CROP_PAD = 0.2
CROP_MAX_PX = 160

Box = tuple[int, int, int, int]
"""Pixel box as (x0, y0, x1, y1)."""


class FacesUnavailable(RuntimeError):
    """The face models are not on disk (or OpenCV lacks YuNet/SFace)."""


@dataclass(frozen=True)
class FaceBox:
    """One detected face in full-frame pixels: box (x, y, w, h), 5 landmarks, score."""

    box: tuple[float, float, float, float]
    landmarks: tuple[tuple[float, float], ...]
    score: float

    @classmethod
    def from_row(cls, row: np.ndarray, dx: float = 0, dy: float = 0) -> FaceBox:
        r = [float(v) for v in row]
        pts = tuple((r[4 + 2 * i] + dx, r[5 + 2 * i] + dy) for i in range(5))
        return cls((r[0] + dx, r[1] + dy, r[2], r[3]), pts, r[14])

    def as_row(self) -> np.ndarray:
        """The 15-float YuNet row SFace's alignCrop expects."""
        flat = [c for p in self.landmarks for c in p]
        return np.array([*self.box, *flat, self.score], dtype=np.float32)


class TrackFace(NamedTuple):
    t: float
    face: FaceBox
    embedding: np.ndarray
    crop: bytes


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity; 0.0 when either vector is zero."""
    a, b = np.asarray(a, dtype=np.float64).ravel(), np.asarray(b, dtype=np.float64).ravel()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def normalise(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).ravel()
    n = float(np.linalg.norm(v))
    return v / n if n else v


def face_quality(face: FaceBox) -> float:
    """Ranking key: detection score times face width in pixels."""
    return face.score * face.box[2]


def head_region(person_box: Box, shape: tuple[int, ...]) -> Box | None:
    """Top `HEAD_FRACTION` of a person box, clamped to the frame; None when empty."""
    h, w = shape[:2]
    x0, y0 = max(0, int(person_box[0])), max(0, int(person_box[1]))
    x1, y1 = min(w, int(person_box[2])), min(h, int(person_box[3]))
    y1 = min(y1, y0 + round((y1 - y0) * HEAD_FRACTION))
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _inside(face: FaceBox, roi: Box) -> bool:
    cx, cy = face.box[0] + face.box[2] / 2, face.box[1] + face.box[3] / 2
    return roi[0] <= cx < roi[2] and roi[1] <= cy < roi[3]


def crop_face(frame_bgr: np.ndarray, face: FaceBox) -> bytes:
    """JPEG of the face box padded 20% each side, at most `CROP_MAX_PX` on its long side."""
    h, w = frame_bgr.shape[:2]
    x, y, bw, bh = face.box
    px, py = bw * CROP_PAD, bh * CROP_PAD
    x0, y0 = max(0, int(x - px)), max(0, int(y - py))
    x1, y1 = min(w, round(x + bw + px)), min(h, round(y + bh + py))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("face box lies outside the frame")
    img = frame_bgr[y0:y1, x0:x1]
    scale = CROP_MAX_PX / max(img.shape[:2])
    if scale < 1:
        size = (max(1, round(img.shape[1] * scale)), max(1, round(img.shape[0] * scale)))
        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("could not encode face crop")
    return buf.tobytes()


def best_faces_for_track(
    samples: Iterable[tuple[float, np.ndarray, Box]],
    *,
    detect: Callable[..., list[FaceBox]],
    embed: Callable[[np.ndarray, FaceBox], np.ndarray],
    crop: Callable[[np.ndarray, FaceBox], bytes] = crop_face,
    max_faces: int = MAX_FACES_PER_TRACK,
) -> list[TrackFace]:
    """Best faces of one person track, best first.

    `samples` are (t, frame_bgr, person_box_xyxy). `detect(frame, roi=head)` runs only on
    the head region; faces narrower than `MIN_FACE_PX` or centred outside it are dropped.
    Only the kept top `max_faces` (score x width) are embedded and cropped.
    """
    top: list[tuple[float, int, float, np.ndarray, FaceBox]] = []
    for n, (t, frame, person_box) in enumerate(samples):
        roi = head_region(person_box, frame.shape)
        if roi is None:
            continue
        for k, face in enumerate(detect(frame, roi=roi)):
            if face.box[2] < MIN_FACE_PX or not _inside(face, roi):
                continue
            item = (face_quality(face), -(n * 1000 + k), float(t), frame, face)
            if len(top) < max_faces:
                heapq.heappush(top, item)
            elif item[:2] > top[0][:2]:
                heapq.heapreplace(top, item)
    ranked = sorted(top, key=lambda i: i[:2], reverse=True)
    return [TrackFace(t, f, normalise(embed(fr, f)), crop(fr, f)) for _, _, t, fr, f in ranked]


class FaceEngine:
    """YuNet + SFace on the local CPU, built on first use from `models_dir`."""

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = Path(models_dir)
        self.skipped_small = 0
        self._detector = None
        self._recognizer = None

    def _models(self):
        if self._detector is None or self._recognizer is None:
            missing = [
                name
                for name in (DETECTOR_FILE, RECOGNIZER_FILE)
                if not (self.models_dir / name).is_file()
            ]
            if missing:
                raise FacesUnavailable(
                    f"face models missing in {self.models_dir}: {', '.join(missing)}"
                )
            if not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
                raise FacesUnavailable("this OpenCV build lacks FaceDetectorYN/FaceRecognizerSF")
            self._detector = cv2.FaceDetectorYN.create(
                str(self.models_dir / DETECTOR_FILE), "", (320, 320), SCORE_THRESHOLD, 0.3, 5000
            )
            self._recognizer = cv2.FaceRecognizerSF.create(
                str(self.models_dir / RECOGNIZER_FILE), ""
            )
        return self._detector, self._recognizer

    def detect(self, frame_bgr: np.ndarray, *, roi: Box | None = None) -> list[FaceBox]:
        """Faces scoring >= 0.8 in `roi` (x0, y0, x1, y1), in full-frame pixels.

        Faces narrower than `MIN_FACE_PX` are dropped and counted in `skipped_small`.
        """
        detector, _ = self._models()
        h, w = frame_bgr.shape[:2]
        x0, y0, x1, y1 = roi if roi is not None else (0, 0, w, h)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            return []
        sub = np.ascontiguousarray(frame_bgr[y0:y1, x0:x1])
        detector.setInputSize((x1 - x0, y1 - y0))
        _, rows = detector.detect(sub)
        faces = [FaceBox.from_row(r, x0, y0) for r in (rows if rows is not None else [])]
        kept = [f for f in faces if f.box[2] >= MIN_FACE_PX]
        self.skipped_small += len(faces) - len(kept)
        return kept

    def embed(self, frame_bgr: np.ndarray, face: FaceBox) -> np.ndarray:
        """SFace template of one face: aligned crop, feature, L2-normalised float32."""
        _, recognizer = self._models()
        aligned = recognizer.alignCrop(frame_bgr, face.as_row())
        return normalise(recognizer.feature(aligned))

    def crop(self, frame_bgr: np.ndarray, face: FaceBox) -> bytes:
        return crop_face(frame_bgr, face)
