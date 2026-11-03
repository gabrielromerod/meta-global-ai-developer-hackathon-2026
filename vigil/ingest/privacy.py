"""Privacy at source: black out polygons, strip audio, refuse upload otherwise (FR-003).

- :func:`mask_clip` re-encodes a clip with every privacy polygon blanked in every frame,
  audio, subtitle and data streams dropped, and container metadata (titles, device, GPS
  location atoms) removed.
- :func:`verify_clean` / :func:`scan_media` decode every frame and require 0 in all
  channels for every pixel inside the exact polygons, and ffprobe to find no audio stream.
- :func:`assert_uploadable` is the pre-upload guard (spec 5.8): it raises
  :class:`PrivacyViolation` unless the file is clean, so nothing unmasked is uploaded.

Polygons are pixel polygons in a reference frame ``ref_size`` (``CameraCfg.width/height``,
1280x720 for the processed window frame); they are rescaled to each file's resolution.
The mask is applied to the polygon dilated by ``margin_px`` with super-black luma (see
:mod:`vigil.ingest.media`) so lossy re-encoding cannot bleed into the exact polygon, which
is the region the check guarantees.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, Field

from vigil.ingest.media import (
    IMAGE_EXTS,
    MediaError,
    count_audio_streams,
    even,
    iter_frames,
    polygon_mask,
    probe,
    transcode_masked,
)
from vigil.models import Polygon

__all__ = [
    "DEFAULT_MARGIN_PX",
    "PrivacyReport",
    "PrivacyViolation",
    "assert_uploadable",
    "mask_clip",
    "mask_image",
    "polygon_mask",
    "scan_media",
    "verify_clean",
]

DEFAULT_MARGIN_PX = 12
"""Dilation (output pixels) applied when masking; 8 px measured sufficient up to CRF 45."""

Size = tuple[int, int]


class PrivacyReport(BaseModel):
    """Result of checking one file against its privacy polygons."""

    path: str
    kind: Literal["video", "image"]
    width: int = 0
    height: int = 0
    frames: int = 0
    bad_frames: int = 0
    nonzero_pixels: int = 0
    first_bad_frame: int | None = None
    audio_streams: int = 0
    reasons: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons


class PrivacyViolation(RuntimeError):
    """Raised by :func:`assert_uploadable`: the file must not be uploaded or committed."""

    def __init__(self, report: PrivacyReport) -> None:
        self.report = report
        super().__init__(f"privacy check failed for {report.path}: {'; '.join(report.reasons)}")


def mask_clip(
    src: Path | str,
    dst: Path | str,
    polygons: Sequence[Polygon],
    *,
    ref_size: Size | None = None,
    margin_px: int = DEFAULT_MARGIN_PX,
    crf: int = 18,
) -> Path:
    """Write ``dst``: ``src`` with every polygon blanked in every frame and no audio.

    Keeps resolution (rounded down to even) and frame rate; output is H.264 MP4 with
    +faststart and no metadata. Returns ``dst``.
    """
    info = probe(src)
    w, h = even(info.width), even(info.height)
    ref = ref_size or (info.width, info.height)
    mask = polygon_mask((w, h), polygons, ref_size=ref, margin_px=margin_px)
    transcode_masked(src, dst, out_size=(w, h), mask=mask, crf=crf)
    return Path(dst)


def mask_image(
    src: Path | str,
    dst: Path | str,
    polygons: Sequence[Polygon],
    *,
    ref_size: Size | None = None,
    margin_px: int | None = None,
) -> Path:
    """Blank polygons in a still. PNG is lossless (no margin needed); lossy formats get the
    default margin and JPEG is written 4:4:4 so chroma blocks cannot straddle the edge."""
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise MediaError(f"cannot read image {src}")
    h, w = img.shape[:2]
    dst = Path(dst)
    lossless = dst.suffix.lower() in {".png", ".bmp", ".tif", ".tiff"}
    margin = margin_px if margin_px is not None else (0 if lossless else DEFAULT_MARGIN_PX)
    mask = polygon_mask((w, h), polygons, ref_size=ref_size or (w, h), margin_px=margin)
    img[mask] = 0
    params: list[int] = []
    if dst.suffix.lower() in {".jpg", ".jpeg"}:
        params = [cv2.IMWRITE_JPEG_QUALITY, 95]
        if hasattr(cv2, "IMWRITE_JPEG_SAMPLING_FACTOR"):
            params += [cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444]
    dst.parent.mkdir(parents=True, exist_ok=True)
    # imwrite drops EXIF/GPS: OpenCV writes pixels only.
    if not cv2.imwrite(str(dst), img, params):
        raise MediaError(f"cannot write image {dst}")
    return dst


def scan_media(
    path: Path | str, polygons: Sequence[Polygon], *, ref_size: Size | None = None
) -> PrivacyReport:
    """Check every frame (or the still) of ``path``: polygon pixels all 0, no audio stream."""
    path = Path(path)
    if path.suffix.lower() in IMAGE_EXTS:
        return _scan_image(path, polygons, ref_size)
    return _scan_video(path, polygons, ref_size)


def verify_clean(
    path: Path | str, polygons: Sequence[Polygon], *, ref_size: Size | None = None
) -> bool:
    """True only if every pixel inside every polygon is 0 in every frame and there is no
    audio stream. Unreadable files are not clean."""
    return scan_media(path, polygons, ref_size=ref_size).ok


def assert_uploadable(
    path: Path | str, polygons: Sequence[Polygon] | None, *, ref_size: Size | None = None
) -> PrivacyReport:
    """Pre-upload guard (spec 5.8): returns the report, or raises :class:`PrivacyViolation`."""
    if polygons is None:
        raise PrivacyViolation(
            PrivacyReport(
                path=str(path),
                kind="video",
                reasons=[
                    "privacy context omitted; explicitly supply camera polygons or none_needed"
                ],
            )
        )
    report = scan_media(path, polygons, ref_size=ref_size)
    if report.ok:
        from vigil.ingest.metadata import scan

        report.reasons.extend(scan(Path(path)))
    if not report.ok:
        raise PrivacyViolation(report)
    return report


# ---------------------------------------------------------------------------


def _count_inside(frame: np.ndarray, inside: np.ndarray) -> int:
    if not inside.any():
        return 0
    return int(np.count_nonzero(frame[inside].reshape(-1, frame.shape[-1]).max(axis=1)))


def _scan_image(path: Path, polygons: Sequence[Polygon], ref_size: Size | None) -> PrivacyReport:
    rep = PrivacyReport(path=str(path), kind="image")
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        rep.reasons.append("unreadable image")
        return rep
    if img.ndim == 2:
        img = img[:, :, None]
    elif img.shape[2] == 4:
        img = img[:, :, :3]  # alpha does not hide pixels once composited elsewhere
    h, w = img.shape[:2]
    rep.width, rep.height, rep.frames = w, h, 1
    inside = polygon_mask((w, h), polygons, ref_size=ref_size or (w, h))
    n = _count_inside(img, inside)
    if n:
        rep.nonzero_pixels, rep.bad_frames, rep.first_bad_frame = n, 1, 0
        rep.reasons.append(f"{n} non-zero pixels inside privacy polygons")
    return rep


def _scan_video(path: Path, polygons: Sequence[Polygon], ref_size: Size | None) -> PrivacyReport:
    rep = PrivacyReport(path=str(path), kind="video")
    try:
        info = probe(path)
        rep.audio_streams = count_audio_streams(path)
    except MediaError as exc:
        rep.reasons.append(f"unreadable video: {str(exc).splitlines()[0]}")
        return rep
    rep.width, rep.height = info.width, info.height
    if rep.audio_streams:
        rep.reasons.append(f"{rep.audio_streams} audio stream(s) present")
    inside: np.ndarray | None = None
    try:
        for i, _t, frame in iter_frames(path):
            rep.frames += 1
            if not polygons:
                continue
            if inside is None or inside.shape != frame.shape[:2]:
                fh, fw = frame.shape[:2]
                inside = polygon_mask((fw, fh), polygons, ref_size=ref_size or (fw, fh))
            n = _count_inside(frame, inside)
            if n:
                rep.bad_frames += 1
                rep.nonzero_pixels += n
                if rep.first_bad_frame is None:
                    rep.first_bad_frame = i
    except MediaError as exc:
        rep.reasons.append(f"unreadable video: {exc}")
        return rep
    if rep.frames == 0:
        rep.reasons.append("no decodable frames")
    if rep.nonzero_pixels:
        rep.reasons.append(
            f"{rep.nonzero_pixels} non-zero pixels inside privacy polygons in "
            f"{rep.bad_frames} frame(s), first at frame {rep.first_bad_frame}"
        )
    return rep
