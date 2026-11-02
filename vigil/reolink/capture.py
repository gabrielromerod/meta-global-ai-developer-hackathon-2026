"""Continuous capture: 10 s stream-copy segments, no audio, 48 h ring (FR-031)."""

from __future__ import annotations

from pathlib import Path

from vigil.models import CameraCfg


async def run_capture(cams: list[CameraCfg], out_dir: Path, segment_s: int = 10) -> None:
    """Stub."""
    raise NotImplementedError("FR-031 not implemented")
