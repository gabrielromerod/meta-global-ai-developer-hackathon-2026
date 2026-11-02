"""FR-014: see docs/spec/vigil-spec.md section 9.4."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import StorySentence, VisitLedger


def run_story(ledger: VisitLedger, writer: object) -> list[StorySentence]:
    """Stub."""
    raise NotImplementedError("FR-014 not implemented")
