"""Event builder: enter, exit, cross, touch, removed, dwell (FR-008)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import Config, Event, ProtectedObject, Track, Watch


def build_events(
    tracks: list[Track], cfg: Config, protected: list[ProtectedObject], watches: list[Watch]
) -> list[Event]:
    """Stub."""
    raise NotImplementedError("FR-008 not implemented")
