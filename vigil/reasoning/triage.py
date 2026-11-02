"""FR-013: see docs/spec/vigil-spec.md section 9.4."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import TriageDecision, VisitSummary


def forced_escalation(summary: VisitSummary) -> TriageDecision | None:
    """Stub."""
    raise NotImplementedError("FR-013 not implemented")
