"""FR-010: see docs/spec/vigil-spec.md section 9.4."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import TopologyEdge


def transit_ok(edge: TopologyEdge, gap_s: float) -> bool:
    """Stub."""
    raise NotImplementedError("FR-010 not implemented")
