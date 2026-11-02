"""Foot point ray-cast to the ground with a 95% radius (FR-039)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import Calibration, Position, TrackFrame


def locate(frame: TrackFrame, cam: Calibration, ground: object, rng: object) -> Position | None:
    """Stub."""
    raise NotImplementedError("FR-039 not implemented")
