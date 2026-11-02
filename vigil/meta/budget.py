"""Budget guard: price first; total, feature, daily caps; window end (FR-043)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import CostEstimate


def estimate(model: str, feature: str, **units: float) -> CostEstimate:
    """Stub."""
    raise NotImplementedError("FR-043 not implemented")
