"""Media helpers shared by the ingest modules: ffprobe, frame iteration, polygon rasters and
the masked YUV transcode pipeline used by privacy masking (FR-003) and windowing (FR-004).

ffmpeg and ffprobe are always resolved through ``vigil.settings`` (never a bare "ffmpeg").

Masking design (why "every pixel inside a polygon is 0" survives lossy H.264):
frames are decoded to raw planar YUV 4:2:0, and inside each privacy polygon dilated by a
safety margin the luma is set to 0 ("blacker than black"; limited-range black is 16) and
both chroma planes to the neutral 128, then the frames are re-encoded. Any decoder that
treats the stream as limited range (the H.264 default; ffmpeg, browsers, OpenCV) clips luma
up to about 16 back to RGB 0, so codec noise has a 16-level headroom, and the margin keeps
the transform blocks and deblocking that touch the polygon free of picture content.
Measured on worst-case texture: an 8 px margin gives 0 non-zero pixels up to CRF 45, whereas
plain RGB black (luma 16) still leaks with a 16 px margin. The default margin is 12 px.
The exact (undilated) polygon is what :func:`vigil.ingest.privacy.verify_clean` checks.
"""

from __future__ import annotations

import contextlib
import json
import struct
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from vigil.models import Polygon
from vigil.settings import ffmpeg_bin, ffprobe_bin

VIDEO_EXTS = frozenset({".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".ts", ".flv"})
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})

MASK_LUMA = 0
NEUTRAL_CHROMA = 128


class MediaError(RuntimeError):
    """ffmpeg/ffprobe failed or a file is not readable media."""


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    fps: float
    fps_str: str
    duration: float
    video_codec: str | None
    pix_fmt: str | None
    audio_streams: int
    nb_frames: int | None
    tags: dict[str, Any] = field(default_factory=dict)


def _run(cmd: list[str], timeout: float = 600) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:  # pragma: no cover - binaries resolved by settings
        raise MediaError(f"cannot run {cmd[0]}: {exc}") from exc


def probe(path: Path | str) -> MediaInfo:
    """ffprobe a media file (first video stream plus a count of audio streams)."""
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_streams",
           "-show_format", str(path)]  # fmt: skip
    proc = _run(cmd, timeout=60)
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed on {path}: {proc.stderr.decode(errors='replace')}")
    data = json.loads(proc.stdout or b"{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = data.get("format", {})
    if video is None:
        raise MediaError(f"no video stream in {path}")
    fps_str = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    if fps_str in ("0/0", "0/1"):
        fps_str = video.get("r_frame_rate") or "0/1"
    try:
        fps = float(Fraction(fps_str))
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    dur = video.get("duration") or fmt.get("duration") or 0.0
    nb = video.get("nb_frames")
    tags = dict(fmt.get("tags", {}))
    tags.update({f"video:{k}": v for k, v in video.get("tags", {}).items()})
    return MediaInfo(
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        fps=fps,
        fps_str=fps_str,
        duration=float(dur),
        video_codec=video.get("codec_name"),
        pix_fmt=video.get("pix_fmt"),
        audio_streams=len(audio),
        nb_frames=int(nb) if nb not in (None, "N/A") else None,
        tags=tags,
    )


def count_audio_streams(path: Path | str) -> int:
    """Number of audio streams ffprobe finds (works for files with no video too)."""
    cmd = [ffprobe_bin(), "-v", "error", "-select_streams", "a", "-show_entries",
           "stream=index", "-of", "csv=p=0", str(path)]  # fmt: skip
    proc = _run(cmd, timeout=60)
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed on {path}: {proc.stderr.decode(errors='replace')}")
    return len([ln for ln in proc.stdout.decode().splitlines() if ln.strip()])


def has_audio(path: Path | str) -> bool:
    return count_audio_streams(path) > 0


def mp4_faststart(path: Path | str) -> bool:
    """True when the MP4 ``moov`` atom precedes ``mdat`` (``-movflags +faststart``)."""
    with open(path, "rb") as fh:
        while True:
            head = fh.read(8)
            if len(head) < 8:
                return False
            size, kind = struct.unpack(">I4s", head)
            if size == 1:
                size = struct.unpack(">Q", fh.read(8))[0]
                body = size - 16
            elif size == 0:
                return False
            else:
                body = size - 8
            if kind == b"moov":
                return True
            if kind == b"mdat":
                return False
            fh.seek(body, 1)


def iter_frames(path: Path | str) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield ``(index, t_seconds, bgr_frame)`` for every decoded frame."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise MediaError(f"cannot open video {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if i > 0 and t <= 0 and fps > 0:
                t = i / fps
            yield i, t, frame
            i += 1
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# Polygon rasters
# ---------------------------------------------------------------------------


def scale_polygons(
    polygons: Sequence[Polygon], size: tuple[int, int], ref_size: tuple[int, int] | None
) -> list[np.ndarray]:
    """Polygons in ``ref_size`` pixels -> int32 arrays in ``size`` (w, h) pixels."""
    w, h = size
    sx, sy = (1.0, 1.0) if ref_size is None else (w / ref_size[0], h / ref_size[1])
    out = []
    for poly in polygons:
        pts = np.asarray(poly, dtype=np.float64).reshape(-1, 2) * (sx, sy)
        out.append(np.round(pts).astype(np.int32))
    return out


def polygon_mask(
    size: tuple[int, int],
    polygons: Sequence[Polygon],
    ref_size: tuple[int, int] | None = None,
    margin_px: int = 0,
) -> np.ndarray:
    """Boolean HxW mask: True on every pixel inside (or on the edge of) any polygon.

    ``size`` and ``ref_size`` are (width, height); polygons are given in ``ref_size`` pixels
    (default: already in ``size`` pixels). ``margin_px`` dilates with a disc of that radius.
    """
    w, h = size
    mask = np.zeros((h, w), np.uint8)
    pts = [p for p in scale_polygons(polygons, size, ref_size) if len(p) >= 3]
    if pts:
        cv2.fillPoly(mask, pts, 255)
    if margin_px > 0 and pts:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin_px + 1, 2 * margin_px + 1))
        mask = cv2.dilate(mask, k)
    return mask > 0


def even(n: int) -> int:
    return max(2, n - (n % 2))


def fit_width(w: int, h: int, max_width: int) -> tuple[int, int]:
    """Keep aspect, width at most ``max_width``, both dimensions even."""
    if w > max_width:
        h = round(h * max_width / w)
        w = max_width
    return even(w), even(h)


# ---------------------------------------------------------------------------
# Masked transcode
# ---------------------------------------------------------------------------


def transcode_masked(
    src: Path | str,
    dst: Path | str,
    *,
    out_size: tuple[int, int],
    mask: np.ndarray | None,
    fps: float | None = None,
    start_s: float | None = None,
    duration_s: float | None = None,
    crf: int = 20,
    preset: str = "veryfast",
) -> int:
    """Decode ``src`` to raw YUV 4:2:0 at ``out_size``, blank ``mask`` (super-black luma,
    neutral chroma), and encode H.264 MP4 with +faststart, no audio, no metadata.

    ``fps`` resamples (ffmpeg ``fps`` filter); ``start_s``/``duration_s`` trim with accurate
    seeking. Returns the number of frames written. Raises :class:`MediaError`.
    """
    w, h = out_size
    if w % 2 or h % 2:
        raise ValueError(f"out_size must be even, got {w}x{h}")
    if mask is not None and mask.shape != (h, w):
        raise ValueError(f"mask shape {mask.shape} != {(h, w)}")
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_info = probe(src)
    out_fps = fps if fps is not None else (src_info.fps or 25.0)
    rate = str(out_fps) if fps is not None else (src_info.fps_str or "25")

    filters = []
    if fps is not None:
        filters.append(f"fps={fps}")
    filters.append(f"scale={w}:{h}:flags=area")
    filters.append("format=yuv420p")

    dec = [ffmpeg_bin(), "-hide_banner", "-v", "error", "-nostdin", "-noautorotate"]
    if start_s is not None and start_s > 0:
        dec += ["-ss", f"{start_s:.6f}"]
    dec += ["-i", str(src)]
    if duration_s is not None:
        dec += ["-t", f"{duration_s:.6f}"]
    dec += ["-map", "0:v:0", "-vf", ",".join(filters), "-f", "rawvideo", "-pix_fmt",
            "yuv420p", "-"]  # fmt: skip

    enc = [ffmpeg_bin(), "-hide_banner", "-v", "error", "-y", "-f", "rawvideo",
           "-pix_fmt", "yuv420p", "-s", f"{w}x{h}", "-r", rate, "-i", "-",
           "-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-color_range", "tv", "-movflags", "+faststart",
           str(dst)]  # fmt: skip

    ysz = w * h
    csz = (w // 2) * (h // 2)
    fsz = ysz + 2 * csz
    cmask = None
    if mask is not None and mask.any():
        cmask = mask.reshape(h // 2, 2, w // 2, 2).any(axis=(1, 3))
    else:
        mask = None

    frames = 0
    with tempfile.TemporaryFile() as dec_err, tempfile.TemporaryFile() as enc_err:
        dproc = subprocess.Popen(dec, stdout=subprocess.PIPE, stderr=dec_err)
        eproc = subprocess.Popen(
            enc, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=enc_err
        )
        if dproc.stdout is None or eproc.stdin is None:  # pragma: no cover
            raise MediaError("ffmpeg pipes not available")
        try:
            while True:
                buf = dproc.stdout.read(fsz)
                if len(buf) < fsz:
                    break
                if mask is not None and cmask is not None:
                    a = np.frombuffer(buf, np.uint8).copy()
                    a[:ysz].reshape(h, w)[mask] = MASK_LUMA
                    a[ysz : ysz + csz].reshape(h // 2, w // 2)[cmask] = NEUTRAL_CHROMA
                    a[ysz + csz :].reshape(h // 2, w // 2)[cmask] = NEUTRAL_CHROMA
                    buf = a.tobytes()
                eproc.stdin.write(buf)
                frames += 1
        except BrokenPipeError:
            pass
        finally:
            with contextlib.suppress(BrokenPipeError):
                eproc.stdin.close()
            dproc.stdout.close()
            drc = dproc.wait()
            erc = eproc.wait()
        if drc != 0 or erc != 0 or frames == 0:
            dec_err.seek(0)
            enc_err.seek(0)
            msg = (dec_err.read() + enc_err.read()).decode(errors="replace").strip()
            dst.unlink(missing_ok=True)
            raise MediaError(f"masked transcode of {src} failed ({frames} frames): {msg}")
    return frames
