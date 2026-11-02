"""FR-010/FR-011: see docs/spec/vigil-spec.md section 9.4."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import Config, Event, Position, Track, Visit


def assemble_visits(
    events: list[Event], tracks: list[Track], notes: dict, positions: list[Position], cfg: Config
) -> list[Visit]:
    """Stub."""
    raise NotImplementedError("FR-010/FR-011 not implemented")
