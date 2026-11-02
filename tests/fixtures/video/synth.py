"""Deterministic synthetic clips for ingest tests (FR-002 to FR-005).

Everything here is generated into a temporary directory at test time with numpy and
ffmpeg; no footage, faces, audio of people or metadata is involved. Each helper returns
the path it wrote.

- ``write_video``: frames from a callable ``frame(i) -> HxWx3 uint8 BGR``, optional audio.
- ``flash_clip``: a dim noisy scene with full-frame flashes (the sync clap) and optional
  audio clicks at given times.
- ``frame_index_clip``: each frame carries its index as big binary blocks, so a decoded
  frame tells which source frame it came from even after lossy re-encoding.
- ``texture_clip``: bright, high-contrast moving texture over the whole frame (worst case
  for codec bleed into masked polygons), optional audio tone.
- ``blob_clip``: static background plus a moving bright square (motion gate).
"""

from __future__ import annotations

import subprocess
import wave
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from vigil.settings import ffmpeg_bin

FrameFn = Callable[[int], np.ndarray]

INDEX_BITS = 12
INDEX_BLOCK = 32  # px per bit block; survives H.264 at default CRF easily


def write_wav(path: Path, samples: np.ndarray, rate: int = 16000) -> Path:
    """Write mono float samples in [-1, 1] as 16-bit PCM."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


def click_track(duration_s: float, click_times: Sequence[float], rate: int = 16000) -> np.ndarray:
    """Quiet noise floor with sharp clap-like bursts starting at ``click_times``."""
    rng = np.random.default_rng(7)
    n = round(duration_s * rate)
    audio = rng.normal(0.0, 0.003, n)
    burst_len = int(0.03 * rate)
    decay = np.exp(-np.linspace(0, 6, burst_len))
    for t in click_times:
        s = round(t * rate)
        e = min(n, s + burst_len)
        audio[s:e] += 0.8 * rng.uniform(-1, 1, e - s) * decay[: e - s]
    return audio


def tone_track(duration_s: float, rate: int = 16000, hz: float = 440.0) -> np.ndarray:
    t = np.arange(round(duration_s * rate)) / rate
    return 0.2 * np.sin(2 * np.pi * hz * t)


def write_video(
    path: Path,
    frame: FrameFn,
    n_frames: int,
    fps: float,
    size: tuple[int, int],
    audio: np.ndarray | None = None,
    audio_rate: int = 16000,
    crf: int = 16,
    pix_fmt: str = "yuv420p",
) -> Path:
    """Encode frames (BGR, ``size`` = (width, height)) to H.264 MP4, optionally with AAC audio.

    Odd sizes need ``pix_fmt="yuv444p"`` (4:2:0 requires even dimensions)."""
    w, h = size
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y"]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-"]
    wav: Path | None = None
    if audio is not None:
        wav = path.with_suffix(".src.wav")
        write_wav(wav, audio, audio_rate)
        cmd += ["-i", str(wav), "-c:a", "aac", "-b:a", "64k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", pix_fmt]
    cmd += [str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    for i in range(n_frames):
        img = frame(i)
        assert img.shape == (h, w, 3)
        assert img.dtype == np.uint8
        proc.stdin.write(img.tobytes())
    _, err = proc.communicate()
    if wav is not None:
        wav.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode(errors='replace')}")
    return path


def flash_clip(
    path: Path,
    duration_s: float,
    flash_times: Sequence[float],
    fps: float = 15.0,
    size: tuple[int, int] = (320, 180),
    flash_len_s: float = 0.2,
    click_times: Sequence[float] | None = None,
    seed: int = 0,
) -> Path:
    """Dim scene with mild noise; the frame is bright from each flash time for flash_len_s."""
    w, h = size
    rng = np.random.default_rng(seed)
    base = rng.integers(30, 60, size=(h, w, 3), dtype=np.uint8)
    n = round(duration_s * fps)

    def frame(i: int) -> np.ndarray:
        t = i / fps
        noise = rng.integers(0, 6, size=(h, w, 3), dtype=np.uint8)
        img = base + noise
        if any(ft <= t < ft + flash_len_s for ft in flash_times):
            img = np.full((h, w, 3), 235, np.uint8)
        return img

    audio = click_track(duration_s, click_times) if click_times is not None else None
    return write_video(path, frame, n, fps, size, audio=audio)


def draw_index(img: np.ndarray, idx: int) -> None:
    """Burn ``idx`` as INDEX_BITS black/white blocks along the top-left of ``img``."""
    for b in range(INDEX_BITS):
        bit = (idx >> b) & 1
        x0 = b * INDEX_BLOCK
        img[0:INDEX_BLOCK, x0 : x0 + INDEX_BLOCK] = 255 if bit else 0


def read_index(img: np.ndarray, scale: float = 1.0) -> int:
    """Inverse of draw_index on a decoded (possibly scaled) BGR frame."""
    blk = INDEX_BLOCK * scale
    idx = 0
    for b in range(INDEX_BITS):
        cx = int((b + 0.5) * blk)
        cy = int(0.5 * blk)
        r = max(1, int(blk / 4))
        v = float(img[cy - r : cy + r, cx - r : cx + r].mean())
        if v > 127:
            idx |= 1 << b
    return idx


def frame_index_clip(
    path: Path,
    duration_s: float,
    fps: float = 30.0,
    size: tuple[int, int] = (1920, 1080),
    audio: bool = True,
) -> Path:
    """Grey frames carrying their own index; a moving bar keeps the encoder honest."""
    w, h = size
    n = round(duration_s * fps)

    def frame(i: int) -> np.ndarray:
        img = np.full((h, w, 3), 90, np.uint8)
        x = (i * 7) % (w - 40)
        img[h // 2 : h // 2 + 40, x : x + 40] = (40, 200, 120)
        draw_index(img, i)
        return img

    return write_video(
        path, frame, n, fps, size, audio=tone_track(duration_s) if audio else None, crf=20
    )


def texture_clip(
    path: Path,
    duration_s: float,
    fps: float = 10.0,
    size: tuple[int, int] = (640, 360),
    audio: bool = True,
    seed: int = 1,
) -> Path:
    """Bright, saturated, moving high-frequency texture everywhere (codec bleed worst case)."""
    w, h = size
    rng = np.random.default_rng(seed)
    tex = rng.integers(0, 256, size=(h, w * 2, 3), dtype=np.uint8)
    tex[::7, :, :] = 255
    n = round(duration_s * fps)

    def frame(i: int) -> np.ndarray:
        x = (i * 5) % w
        return np.ascontiguousarray(tex[:, x : x + w])

    return write_video(
        path, frame, n, fps, size, audio=tone_track(duration_s) if audio else None, crf=23
    )


def blob_clip(
    path: Path,
    duration_s: float,
    fps: float = 10.0,
    size: tuple[int, int] = (640, 360),
    blob: tuple[int, int, int, int] | None = None,
    blob_size: int = 40,
    seed: int = 2,
) -> Path:
    """Static textured background; if ``blob`` = (x0, y0, x1, y1) a bright square moves
    from (x0, y0) to (x1, y1) over the clip. ``blob=None`` gives a static clip."""
    w, h = size
    rng = np.random.default_rng(seed)
    base = rng.integers(40, 90, size=(h, w, 3), dtype=np.uint8)
    n = round(duration_s * fps)

    def frame(i: int) -> np.ndarray:
        img = base.copy()
        if blob is not None:
            a = i / max(1, n - 1)
            x = int(blob[0] + a * (blob[2] - blob[0]))
            y = int(blob[1] + a * (blob[3] - blob[1]))
            img[y : y + blob_size, x : x + blob_size] = (230, 230, 230)
        return img

    return write_video(path, frame, n, fps, size)
