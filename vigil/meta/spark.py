"""Muse Spark: appearance notes, rule compile, triage fallback (FR-009, FR-021)."""

from __future__ import annotations

from pathlib import Path

from vigil.models import Appearance, Rule


def appearance_notes(c, tagged_clip: Path, tags: list[str]) -> dict[str, Appearance]:
    """Stub."""
    raise NotImplementedError("FR-009/FR-021 not implemented")


def compile_rule(c, text: str, catalog: dict) -> Rule:
    """Stub."""
    raise NotImplementedError("FR-009/FR-021 not implemented")
