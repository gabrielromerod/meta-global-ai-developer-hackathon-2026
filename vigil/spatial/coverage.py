"""0.25 m ground visibility grid and blind regions (FR-038)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import Calibration


def coverage(model: object, cams: list[Calibration], cell_m: float = 0.25) -> dict:
    """Stub."""
    raise NotImplementedError("FR-038 not implemented")
