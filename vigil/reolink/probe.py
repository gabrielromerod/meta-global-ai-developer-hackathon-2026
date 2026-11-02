"""Reolink probe: model, firmware, RTSP/FLV, AI-event support (FR-030)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import CameraCfg


async def probe(cam: CameraCfg) -> dict:
    """Stub."""
    raise NotImplementedError("FR-030 not implemented")
