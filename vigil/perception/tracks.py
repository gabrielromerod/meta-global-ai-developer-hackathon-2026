"""Stitch SAM object ids across overlapping windows by IoU (FR-007)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import SamObject, Track


def stitch(objs: list[SamObject]) -> list[Track]:
    """Stub."""
    raise NotImplementedError("FR-007 not implemented")
