"""FR-015: see docs/spec/vigil-spec.md section 9.4."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import StoryDraft, ValidationResult, VisitLedger


def validate(draft: StoryDraft, ledger: VisitLedger) -> ValidationResult:
    """Stub."""
    raise NotImplementedError("FR-015 not implemented")
