"""MetaClient: retries, cache, budget guard and ledger for every model call (FR-023)."""

from __future__ import annotations

from pathlib import Path


class MetaClient:
    """Stub."""

    def upload(self, path: Path) -> str:
        raise NotImplementedError("FR-023 not implemented")

    def responses(
        self,
        model: str,
        body: dict,
        purpose: str,
        visit_id: str | None = None,
        stream: bool = False,
    ) -> dict:
        raise NotImplementedError("FR-023 not implemented")
