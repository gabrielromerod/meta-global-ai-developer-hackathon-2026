"""Motion gate: frame differencing outside masked areas (FR-005)."""

from __future__ import annotations

from pathlib import Path

from vigil.models import Polygon


def motion_score(path: Path, polygons: list[Polygon]) -> float:
    """Stub."""
    raise NotImplementedError("FR-005 not implemented")
