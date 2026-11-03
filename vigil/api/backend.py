"""Live model calls behind one injectable interface (FR-019, FR-021, FR-022, FR-026, FR-037).

The sandbox makes four kinds of live call (spec 5.2): tap-to-protect, voice transcription,
rule compile and story re-run; the LAN calibration tool adds SAM landmark proposals. Routes
never touch the Meta client directly: they call a `LiveBackend`.
Tests inject fakes; production uses `MetaLiveBackend`, which imports `vigil.meta` lazily so
the sandbox starts (and every cached flow works) even when those modules or the API are
unavailable (NFR-009). Any exception from a backend becomes a cached fallback with a notice.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol

from pydantic import BaseModel, Field

from vigil.models import ModelCall, VisitLedger


class LiveResult(BaseModel):
    """What a live call produced, plus every model call it made (for the ledger)."""

    payload: dict[str, Any]
    calls: list[ModelCall] = Field(default_factory=list)


class LiveUnavailableError(RuntimeError):
    """The live path cannot run (module missing, not configured, upstream failure)."""


class LandmarksBlockedError(LiveUnavailableError):
    """SAM landmark proposals (FR-037) are not built yet by the spatial workstream."""


class LiveBackend(Protocol):
    def protect(
        self, camera_id: str, frame_ts: float | None, x: float, y: float, label: str | None
    ) -> LiveResult: ...

    def compile_rule(self, text: str, catalog: dict[str, Any]) -> LiveResult: ...

    def transcribe(self, audio: bytes, content_type: str) -> LiveResult: ...

    def rerun_story(self, ledger: VisitLedger) -> LiveResult: ...

    def propose_landmarks(self, camera_id: str) -> LiveResult: ...


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
    """Ledger rows the Meta client recorded during one live action, if it exposes them.

    When the client's ledger keeps a spend book (MetaClient's ``CallLedger``), their cost is
    offered to it as already recorded: the sandbox route reports the action's spend again,
    and the shared durable ledger must not count it twice.
    """
    ledger = _ledger(client)
    if ledger is None:
        return []
    if callable(getattr(ledger, "since", None)):
        rows = list(ledger.since(before))
    elif isinstance(ledger, list):
        rows = ledger[before:]
    else:
        return []
    calls = [row if isinstance(row, ModelCall) else ModelCall.model_validate(row) for row in rows]
    book = getattr(ledger, "book", None)
    offer = getattr(book, "offer_prerecorded", None)
    if callable(offer):
        offer(sum(c.cost_usd for c in calls if not c.cached))
    return calls


class MetaLiveBackend:
    """Adapter over vigil.meta (B1). Imports lazily; every failure is LiveUnavailableError.

    The client is built from settings, so with ``VIGIL_LEDGER_PATH`` it uses the process's
    shared durable ledger, the same one the sandbox guards read (one source of truth for the
    caps; paid calls fail closed without it).
    """

    def __init__(self, settings: Any, stills_dir: Any = None, *, ledger: Any = None) -> None:
        self._settings = settings
        self._stills_dir = stills_dir
        self._ledger = ledger
        """The sandbox guards' ledger, so both keep one book even without a ledger path."""
        self._client: Any = None

    def _meta_client(self) -> Any:
        if self._client is None:
            try:
                from vigil.meta.client import MetaClient
            except ImportError as exc:  # pragma: no cover - module always present in repo
                raise LiveUnavailableError("Meta client module unavailable") from exc
            try:
                if self._ledger is not None:
                    self._client = MetaClient(settings=self._settings, ledger=self._ledger)
                else:
                    self._client = MetaClient(settings=self._settings)
            except TypeError:
                self._client = MetaClient()
        return self._client

    def _ledger_len(self, client: Any) -> int:
        return _ledger_len(client)

    def protect(
        self, camera_id: str, frame_ts: float | None, x: float, y: float, label: str | None
    ) -> LiveResult:
        from vigil.ingest.config import load_config, privacy_polygons
        from vigil.ingest.media import probe
        from vigil.ingest.review import require_privacy_review
        from vigil.meta.sam import segment_point

        if self._stills_dir is None:
            raise LiveUnavailableError("no still frames in this bundle for a live point prompt")
        still = self._stills_dir / f"{camera_id}.png"
        if not still.exists():
            still = self._stills_dir / f"{camera_id}.jpg"
        if not still.exists():
            raise LiveUnavailableError(f"no still frame for camera {camera_id}")
        cfg = load_config(self._settings.config_path)
        try:
            camera = cfg.camera(camera_id)
        except KeyError:
            raise LiveUnavailableError("camera privacy context is not configured") from None
        polygons = privacy_polygons(cfg, camera_id, self._settings.config_path.parent / "privacy")
        require_privacy_review(camera, polygons)
        info = probe(still)
        client = self._meta_client()
        before = self._ledger_len(client)
        mask = segment_point(
            client,
            still,
            int(x * info.width / camera.width),
            int(y * info.height / camera.height),
            polygons=polygons,
            ref_size=(camera.width, camera.height),
        )
        payload = mask.model_dump() if hasattr(mask, "model_dump") else dict(mask)
        box = payload.get("box") or payload.get("bbox")
        if box:
            payload["bbox"] = {
                key: float(value)
                * (
                    camera.width / info.width
                    if key.startswith("x")
                    else camera.height / info.height
                )
                for key, value in box.items()
            }
        payload["width"], payload["height"] = camera.width, camera.height
        return LiveResult(payload={"mask": payload}, calls=_calls_since(client, before))

    def compile_rule(self, text: str, catalog: dict[str, Any]) -> LiveResult:
        from vigil.meta.spark import compile_rule

        client = self._meta_client()
        before = self._ledger_len(client)
        draft = compile_rule(client, text, catalog)
        payload = draft.model_dump() if hasattr(draft, "model_dump") else dict(draft)
        if "rule" not in payload and "question" not in payload:
            payload = {"rule": payload}
        return LiveResult(payload=payload, calls=_calls_since(client, before))

    def transcribe(self, audio: bytes, content_type: str) -> LiveResult:
        """Send the WAV bytes as they are: speech never touches the disk (NFR-002)."""
        from vigil.meta import asr

        if "wav" not in content_type:
            raise LiveUnavailableError("voice rules take 16 kHz mono 16-bit PCM WAV only")
        client = self._meta_client()
        before = self._ledger_len(client)
        result = asr.transcribe_wav(client, bytes(audio))
        payload = {"transcript": result.text, "cached": bool(result.cached)}
        return LiveResult(payload=payload, calls=_calls_since(client, before))

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

    def propose_landmarks(self, camera_id: str) -> LiveResult:
        """SAM 3.1 landmark proposals on a camera still (FR-037), once the module exists.

        The spatial workstream's `vigil.spatial.landmarks.propose_landmarks` is imported lazily
        (it needs OpenCV); spec 9.5 also lists it under `vigil.meta`, so that is tried second.
        """
        propose: Any = None
        for module in ("vigil.spatial.landmarks", "vigil.meta.sam"):
            try:
                propose = getattr(importlib.import_module(module), "propose_landmarks", None)
            except ImportError:
                propose = None
            if callable(propose):
                break
        if not callable(propose):
            raise LandmarksBlockedError("SAM landmark proposals are not built yet")
        if self._stills_dir is None:
            raise LiveUnavailableError("no still frames in this bundle for landmark proposals")
        still = self._stills_dir / f"{camera_id}.jpg"
        if not still.exists():
            raise LiveUnavailableError(f"no still frame for camera {camera_id}")
        client = self._meta_client()
        before = self._ledger_len(client)
        proposals = propose(client, still, camera_id)
        rows = [p.model_dump() if hasattr(p, "model_dump") else dict(p) for p in proposals]
        return LiveResult(payload={"proposals": rows}, calls=_calls_since(client, before))
