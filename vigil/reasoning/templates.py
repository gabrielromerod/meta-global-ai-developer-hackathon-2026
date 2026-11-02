"""FR-014: see docs/spec/vigil-spec.md section 9.4."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import StorySentence, VisitLedger


def template_story(ledger: VisitLedger) -> list[StorySentence]:
    """Stub."""
    raise NotImplementedError("FR-014 not implemented")
