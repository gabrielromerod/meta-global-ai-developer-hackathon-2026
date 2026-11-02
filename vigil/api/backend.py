"""Live model calls behind one injectable interface (FR-019, FR-021, FR-022, FR-026).

The sandbox makes only three kinds of live call (spec 5.2): tap-to-protect, rule compile
and story re-run. Routes never touch the Meta client directly: they call a `LiveBackend`.
Tests inject fakes; production uses `MetaLiveBackend`, which imports `vigil.meta` lazily so
the sandbox starts (and every cached flow works) even when those modules or the API are
unavailable (NFR-009). Any exception from a backend becomes a cached fallback with a notice.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from vigil.models import ModelCall, VisitLedger


class LiveResult(BaseModel):
    """What a live call produced, plus every model call it made (for the ledger)."""

    payload: dict[str, Any]
    calls: list[ModelCall] = Field(default_factory=list)


class LiveUnavailableError(RuntimeError):
    """The live path cannot run (module missing, not configured, upstream failure)."""


class LiveBackend(Protocol):
    def protect(
        self, camera_id: str, frame_ts: float | None, x: float, y: float, label: str | None
    ) -> LiveResult: ...

    def compile_rule(self, text: str, catalog: dict[str, Any]) -> LiveResult: ...

    def transcribe(self, audio: bytes, content_type: str) -> LiveResult: ...

    def rerun_story(self, ledger: VisitLedger) -> LiveResult: ...


def _ledger(client: Any) -> Any:
    """The client's call ledger: MetaClient's ``CallLedger`` (len/iter/since) or a list.

    An empty ``CallLedger`` is falsy (it has ``__len__``), so test for presence, not truth.
    """
    ledger = getattr(client, "ledger", None)
    return ledger if ledger is not None else getattr(client, "calls", None)


def _ledger_len(client: Any) -> int:
    ledger = _ledger(client)
    try:
        return len(ledger) if ledger is not None else 0
    except TypeError:
        return 0


def _calls_since(client: Any, before: int) -> list[ModelCall]:
    """Ledger rows the Meta client recorded during one live action, if it exposes them."""
    ledger = _ledger(client)
    if ledger is None:
        return []
    if callable(getattr(ledger, "since", None)):
        rows = list(ledger.since(before))
    elif isinstance(ledger, list):
        rows = ledger[before:]
    else:
        return []
    return [row if isinstance(row, ModelCall) else ModelCall.model_validate(row) for row in rows]


class MetaLiveBackend:
    """Adapter over vigil.meta (B1). Imports lazily; every failure is LiveUnavailableError."""

    def __init__(self, settings: Any, stills_dir: Any = None) -> None:
        self._settings = settings
        self._stills_dir = stills_dir
        self._client: Any = None

    def _meta_client(self) -> Any:
        if self._client is None:
            try:
                from vigil.meta.client import MetaClient
            except ImportError as exc:  # pragma: no cover - module always present in repo
                raise LiveUnavailableError("Meta client module unavailable") from exc
            try:
                self._client = MetaClient(settings=self._settings)
            except TypeError:
                self._client = MetaClient()
        return self._client

    def _ledger_len(self, client: Any) -> int:
        return _ledger_len(client)

    def protect(
        self, camera_id: str, frame_ts: float | None, x: float, y: float, label: str | None
    ) -> LiveResult:
        from vigil.meta.sam import segment_point

        if self._stills_dir is None:
            raise LiveUnavailableError("no still frames in this bundle for a live point prompt")
        still = self._stills_dir / f"{camera_id}.jpg"
        if not still.exists():
            raise LiveUnavailableError(f"no still frame for camera {camera_id}")
        client = self._meta_client()
        before = self._ledger_len(client)
        mask = segment_point(client, still, int(x), int(y))
        payload = mask.model_dump() if hasattr(mask, "model_dump") else dict(mask)
        return LiveResult(payload={"mask": payload}, calls=_calls_since(client, before))

    def compile_rule(self, text: str, catalog: dict[str, Any]) -> LiveResult:
        from vigil.meta.spark import compile_rule

        client = self._meta_client()
        before = self._ledger_len(client)
        draft = compile_rule(client, text, catalog)
        payload = draft.model_dump() if hasattr(draft, "model_dump") else dict(draft)
        if "rule" not in payload:
            payload = {"rule": payload}
        return LiveResult(payload=payload, calls=_calls_since(client, before))

    def transcribe(self, audio: bytes, content_type: str) -> LiveResult:
        import tempfile
        from pathlib import Path

        from vigil.meta.asr import transcribe

        client = self._meta_client()
        before = self._ledger_len(client)
        suffix = ".wav" if "wav" in content_type else ".webm"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"rule{suffix}"
            path.write_bytes(audio)
            text = transcribe(client, path)
        return LiveResult(payload={"transcript": text}, calls=_calls_since(client, before))

    def rerun_story(self, ledger: VisitLedger) -> LiveResult:
        from vigil.meta.wonder import write_story
        from vigil.reasoning.validator import validate

        client = self._meta_client()
        before = self._ledger_len(client)
        draft = write_story(client, ledger)
        result = validate(draft, ledger)
        if not result.passed:
            failures = [f.detail for f in result.failures]
            draft = write_story(client, ledger, failures)
            result = validate(draft, ledger)
            result.attempt = 2
        payload = {
            "story": [s.model_dump() for s in draft.sentences],
            "proposal": draft.verdict_proposal,
            "validation": result.model_dump(),
        }
        return LiveResult(payload=payload, calls=_calls_since(client, before))
