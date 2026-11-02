"""Muse Wonder: story from the visit ledger JSON, never pixels (FR-014)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import StoryDraft, VisitLedger


def write_story(c, ledger: VisitLedger, failures: list[str] | None = None) -> StoryDraft:
    """Stub."""
    raise NotImplementedError("FR-014 not implemented")
