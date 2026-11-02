"""Muse Glimmer 30B triage through a local llama.cpp server (FR-028)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import TriageDecision, VisitSummary


def triage_glimmer(summary: VisitSummary) -> TriageDecision:
    """Stub."""
    raise NotImplementedError("blocked: needs Glimmer GGUF on the 3090 (H-03)")
