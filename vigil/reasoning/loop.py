"""FR-020: see docs/spec/vigil-spec.md section 9.4."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import Watch, WatchProposal


def accept_watches(
    proposals: list[WatchProposal], cameras: set[str], allowlist: set[str], active: list[Watch]
) -> list[Watch]:
    """Stub."""
    raise NotImplementedError("FR-020 not implemented")
