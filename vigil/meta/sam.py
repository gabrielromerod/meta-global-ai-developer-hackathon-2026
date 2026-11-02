"""SAM 3.1 concept tracking and point prompts via the Responses API (FR-006)."""

from __future__ import annotations

from pathlib import Path

from vigil.models import SamObject, Window


def track_concept(c, w: Window, phrase: str) -> list[SamObject]:
    """Stub."""
    raise NotImplementedError("FR-006 not implemented")


def segment_point(c, still: Path, x: int, y: int) -> dict:
    """Stub."""
    raise NotImplementedError("FR-006 not implemented")
