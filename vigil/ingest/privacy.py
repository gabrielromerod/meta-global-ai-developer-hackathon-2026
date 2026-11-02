"""Privacy at source: black out polygons, strip audio (FR-003)."""

from __future__ import annotations

from pathlib import Path

from vigil.models import Polygon


def mask_clip(src: Path, dst: Path, polygons: list[Polygon]) -> Path:
    """Stub."""
    raise NotImplementedError("FR-003 not implemented")


def verify_clean(path: Path, polygons: list[Polygon]) -> bool:
    """Stub."""
    raise NotImplementedError("FR-003 not implemented")
