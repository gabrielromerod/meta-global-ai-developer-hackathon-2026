"""10 s windows, 2 s overlap, H.264 MP4, 10 fps, <=1280 px, faststart (FR-004)."""

from __future__ import annotations

from pathlib import Path

from vigil.models import Window


def plan_windows(
    t0: float, t1: float, length_s: float = 10.0, overlap_s: float = 2.0
) -> list[tuple[float, float]]:
    """Stub."""
    raise NotImplementedError("FR-004 not implemented")


def cut_window(src: Path, dst: Path, t0: float, t1: float) -> Window:
    """Stub."""
    raise NotImplementedError("FR-004 not implemented")
