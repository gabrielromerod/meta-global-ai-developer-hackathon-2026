"""Local SAM 3.1 backend on the RTX 3090, chunked video (FR-042)."""

from __future__ import annotations

from pathlib import Path  # noqa: F401

from vigil.models import SamObject, Window


def track_concept_local(w: Window, phrase: str) -> list[SamObject]:
    """Stub."""
    raise NotImplementedError("blocked: needs gpu group and SAM 3.1 weights (H-02)")
