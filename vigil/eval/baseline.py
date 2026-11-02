"""Naive baseline: one Spark call per motion window (FR-025)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import Window


def run_baseline(windows: list[Window]) -> dict:
    """Stub."""
    raise NotImplementedError("blocked: FR-025 live runs need credits")
