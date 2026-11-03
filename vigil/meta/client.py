"""MetaClient: retries, cache, budget guard and ledger for every model call (FR-023).

Every Meta Model API call in Vigil goes through :class:`MetaClient`, in this order:

1. model allowlist (exactly the four Standard-mode IDs; Contributor IDs refused, NFR-004);
2. cache lookup by request hash (a hit costs $0 and is ledgered as cached);
3. budget guard pre-flight price, reserved atomically (pending money counts in every check,
   so concurrent calls cannot both pass a check only one fits): credit, feature and daily
   caps inside the credit window; after it, VIGIL_ALLOW_PAID, a durable ledger and the $25 /
   $5-per-PT-day judging caps; no call at all from VIGIL_JUDGING_END on (FR-043, NFR-036,
   NFR-037);
4. send, with 2 retries on 429, 5xx, timeouts, network errors and malformed bodies,
   exponential backoff with jitter (``Retry-After`` honoured); any other 4xx is raised at
   once with its body (NFR-010, spec section 3 ``test_client_retry``). Every billed attempt
   (a 2xx whose body was malformed or failed) is charged at the estimate, and the budget is
   re-checked before each retry, so a retry can never cross a cap;
5. one ledger row per call (vigil.models.ModelCall), tagged with its budget ``feature`` and
   its ``funding`` (``credit`` or ``paid``, spec 9.3). With ``VIGIL_LEDGER_PATH`` the ledger
   is a SQLite file (WAL) shared by every guard in the process, so caps survive a restart.

Wire format (https://dev.meta.ai/docs/models, /docs/api-reference/responses/schemas):
base ``https://api.meta.ai/v1``, ``Authorization: Bearer $MODEL_API_KEY``,
``POST /files`` (multipart, ``purpose=user_data``) -> ``{"id": "file-..."}``,
``POST /responses`` -> Response with ``output[]`` and ``usage.input_tokens`` /
``output_tokens`` / ``input_tokens_details.cached_tokens``; streamed as SSE ``data:`` lines
(``response.output_text.delta`` ... ``response.completed``).

The API key is read only from ``settings.model_api_key`` and is scrubbed from every error,
ledger row and repr.
"""

from __future__ import annotations

import contextlib
import json
import logging
import mimetypes
import random
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from vigil.meta.budget import (
    SAM,
    SPARK_VIDEO_CLIP_TOKENS,
    TOKEN_PRICES,
    VOICE,
    BudgetExceeded,
    BudgetGuard,
    Reservation,
    SpendBook,
    check_model,
    estimate,
    feature_for,
)
from vigil.meta.cache import ResponseCache, file_hash, request_hash
from vigil.models import CostEstimate, Funding, ModelCall
from vigil.settings import REPO_ROOT, Settings, get_settings

log = logging.getLogger(__name__)

RawResponse = dict[str, Any]

DEFAULT_SAM_WINDOW_FRAMES = 100
"""Pre-flight frame count for one SAM video request when the caller gives none (10 s, 10 fps)."""
DEFAULT_IMAGE_TOKENS = 1_500
DEFAULT_OUT_TOKENS = 2_000
RETRYABLE_ERROR_CODES = frozenset({"server_error", "rate_limit_exceeded"})
SCHEMA_SQL = REPO_ROOT / "vigil" / "store" / "schema.sql"


# ---------------------------------------------------------------------------
# Errors. ``fallback`` tells callers whether to serve the cached/template path.
# ---------------------------------------------------------------------------


class MetaError(RuntimeError):
    fallback: bool = True
    billed_attempts: int = 0
    """Attempts that may have been billed (a 2xx with a malformed or failed body)."""


class ModelNotAllowed(MetaError, ValueError):
    """Model ID outside the Standard-mode allowlist (NFR-004). Never sent."""

    fallback = False


class MetaHTTPError(MetaError):
    """A non-retryable HTTP error (4xx other than 429). Not retried; body included."""

    fallback = False

    def __init__(self, status: int, body: str, message: str | None = None):
        self.status = status
        self.body = body
        super().__init__(message or f"Meta API HTTP {status}: {body}")


class MetaAuthError(MetaHTTPError):
    """No API key configured, or the key was rejected."""


class MetaUnavailable(MetaError):
    """Retries exhausted (429, 5xx, timeout, network). Callers fall back to cached results."""

    fallback = True

    def __init__(self, message: str, status: int | None = None, attempts: int = 0):
        self.status = status
        self.attempts = attempts
        super().__init__(message)


class MalformedResponse(MetaUnavailable):
    """The response body was not the JSON or event stream the API documents."""


class MetaResponseFailed(MetaError):
    """The API returned a response with status ``failed`` and a non-retryable error code."""

    fallback = True


class CacheMiss(MetaError):
    """Cache-only mode and nothing cached for this request: no live call is made."""

    fallback = True


class _Retryable(Exception):
    def __init__(
        self,
        kind: str,
        detail: str,
        status: int | None = None,
        retry_after: float | None = None,
        billed: bool = False,
    ):
        self.kind = kind
        self.detail = detail
        self.status = status
        self.retry_after = retry_after
        self.billed = billed
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

_FALLBACK_DDL = """CREATE TABLE IF NOT EXISTS model_calls(id TEXT PRIMARY KEY, model TEXT,
  purpose TEXT, visit_id TEXT, req_hash TEXT, latency_ms INT, in_tokens INT, out_tokens INT,
  units REAL, cost_usd REAL, cached INT, ok INT, error TEXT, backend TEXT, gpu_s REAL,
  feature TEXT, funding TEXT, created_at TEXT)"""
_ADDED_COLUMNS = {"feature": "TEXT", "funding": "TEXT"}
"""Columns added after the first schema; an older database gains them when opened."""


def _model_calls_ddl() -> str:
    """The model_calls table exactly as vigil/store/schema.sql defines it."""
    try:
        sql = SCHEMA_SQL.read_text(encoding="utf-8")
    except OSError:
        return _FALLBACK_DDL
    m = re.search(r"CREATE TABLE model_calls\s*\((.*?)\);", sql, flags=re.S | re.I)
    if not m:
        return _FALLBACK_DDL
    return f"CREATE TABLE IF NOT EXISTS model_calls({m.group(1)})"


class CallLedger:
    """Every model call, in memory and optionally in SQLite (``model_calls``, spec 9.3).

    ``total()`` is the sum of ``cost_usd`` over the rows, so the panel total always matches
    the ledger (FR-023). With ``db_path`` the rows persist (WAL journal, synchronous FULL,
    ``created_at`` stored in UTC) and opening an existing database loads them, so the spend
    caps survive a restart. ``book`` indexes the spend of every row for the budget guards.

    A path that cannot be opened or written never raises: the ledger stays in memory and
    ``durable`` is False, which makes the budget guards refuse paid calls (fail closed).
    """

    def __init__(self, db_path: Path | str | None = None):
        self._lock = threading.Lock()
        self._rows: list[ModelCall] = []
        self._ids: set[str] = set()
        self._features: dict[str, str] = {}
        self._con: sqlite3.Connection | None = None
        self._columns: list[str] = []
        self.path = Path(db_path) if db_path is not None else None
        self.book = SpendBook(durable=False)
        if db_path is not None:
            try:
                self._open(Path(db_path))
            except (OSError, sqlite3.Error) as exc:
                log.error(
                    "spend ledger %s is not writable (%s): kept in memory; paid live calls "
                    "are refused (fail closed)",
                    db_path,
                    type(exc).__name__,
                )
                self._close_quietly()
                self._rows, self._ids, self._features = [], set(), {}
                self.book = SpendBook(durable=False)

    def _open(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(path), check_same_thread=False)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=FULL")
        self._con.execute(_model_calls_ddl())
        self._columns = [r[1] for r in self._con.execute("PRAGMA table_info(model_calls)")]
        for col, sql_type in _ADDED_COLUMNS.items():
            if col not in self._columns:
                self._con.execute(f"ALTER TABLE model_calls ADD COLUMN {col} {sql_type}")
                self._columns.append(col)
        self._con.commit()
        for row in self._load():
            self._rows.append(row)
            self._ids.add(row.id)
            self.book.add_row(row)
        self.book.durable = True

    @property
    def durable(self) -> bool:
        """True while every row is persisted to SQLite (paid calls need this)."""
        return self.book.durable

    def _close_quietly(self) -> None:
        if self._con is not None:
            with contextlib.suppress(sqlite3.Error):
                self._con.close()
            self._con = None

    def _load(self) -> Iterator[ModelCall]:
        assert self._con is not None
        cur = self._con.execute("SELECT * FROM model_calls ORDER BY rowid")
        names = [d[0] for d in cur.description]
        fields = set(ModelCall.model_fields)
        for values in cur:
            raw = {k: v for k, v in zip(names, values, strict=True) if k in fields}
            raw = {k: v for k, v in raw.items() if v is not None}
            for flag in ("cached", "ok"):
                if flag in raw:
                    raw[flag] = bool(raw[flag])
            yield ModelCall.model_validate(raw)

    def add(self, row: ModelCall, feature: str | None = None) -> ModelCall:
        """Append (and persist) one row, then commit its spend to the book.

        The book's lock is never taken while the ledger's is held (no lock-order deadlock).
        A failed write keeps the row in memory and marks the ledger not durable.
        """
        feature = feature or row.feature or feature_for(row.purpose)
        with self._lock:
            self._rows.append(row)
            self._ids.add(row.id)
            self._features[row.id] = feature
            if self._con is not None:
                try:
                    self._persist(row)
                except sqlite3.Error as exc:
                    log.error(
                        "spend ledger write failed (%s): paid live calls are refused from now "
                        "on (fail closed)",
                        type(exc).__name__,
                    )
                    self._close_quietly()
                    self.book.durable = False
        self.book.add_row(row, feature)
        return row

    def _persist(self, row: ModelCall) -> None:
        assert self._con is not None
        data = row.model_dump()
        data["cached"] = int(row.cached)
        data["ok"] = int(row.ok)
        created = row.created_at
        if created is not None:
            created = created.replace(tzinfo=UTC) if created.tzinfo is None else created
            data["created_at"] = created.astimezone(UTC).isoformat()
        cols = [c for c in self._columns if c in data]
        self._con.execute(
            f"INSERT INTO model_calls({', '.join(cols)}) "  # noqa: S608 (fixed columns)
            f"VALUES ({', '.join('?' for _ in cols)})",
            [data[c] for c in cols],
        )
        self._con.commit()

    def has(self, call_id: str) -> bool:
        with self._lock:
            return call_id in self._ids

    def rows(self) -> list[ModelCall]:
        with self._lock:
            return list(self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self) -> Iterator[ModelCall]:
        return iter(self.rows())

    def __getitem__(self, index):  # int or slice, like the list of rows
        return self.rows()[index]

    def since(self, count: int) -> list[ModelCall]:
        """Rows added after the first ``count`` (calls made during one live action)."""
        return self.rows()[count:]

    def for_visit(self, visit_id: str) -> list[ModelCall]:
        return [r for r in self.rows() if r.visit_id == visit_id]

    def total(self) -> float:
        return sum(r.cost_usd for r in self.rows())

    def total_by_funding(self) -> dict[str, float]:
        """Spend by ledger tag: ``credit`` (the $140 cap) and ``paid`` (the judging cap)."""
        out: dict[str, float] = {"credit": 0.0, "paid": 0.0}
        for r in self.rows():
            out[r.funding] = out.get(r.funding, 0.0) + r.cost_usd
        return out

    def total_by_feature(self) -> dict[str, float]:
        out: dict[str, float] = {}
        with self._lock:
            for r in self._rows:
                f = self._features.get(r.id) or feature_for(r.purpose)
                out[f] = out.get(f, 0.0) + r.cost_usd
        return out

    def close(self) -> None:
        """Close the database. The ledger stays readable but is no longer durable."""
        with self._lock:
            if self._con is not None:
                self._close_quietly()
                self.book.durable = False


_SHARED: dict[str, CallLedger] = {}
_SHARED_LOCK = threading.Lock()


def shared_ledger(path: Path | str | None) -> CallLedger:
    """The process-wide ledger for ``path`` (``VIGIL_LEDGER_PATH``).

    Every client and guard in one process that names the same file gets the same ledger and
    so the same spend book: their caps, totals and reservations agree (single replica; see
    the Dockerfile). ``None`` gives a fresh in-memory ledger (tests, dev), which never admits
    paid calls.
    """
    if path is None:
        return CallLedger()
    try:
        key = str(Path(path).resolve())
    except OSError:
        key = str(path)
    with _SHARED_LOCK:
        ledger = _SHARED.get(key)
        if ledger is None:
            ledger = CallLedger(path)
            _SHARED[key] = ledger
        return ledger


def reset_shared_ledgers() -> None:
    """Close and forget every shared ledger (a process restart, in tests)."""
    with _SHARED_LOCK:
        ledgers = list(_SHARED.values())
        _SHARED.clear()
    for ledger in ledgers:
        ledger.close()


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def extract_text(resp: RawResponse) -> str:
    """The model's text: ``output_text`` when present, else the ``output_text`` parts."""
    text = resp.get("output_text")
    if isinstance(text, str):
        return text
    parts: list[str] = []
    for item in resp.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                parts.append(str(part.get("text", "")))
    return "".join(parts)


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S | re.I)


def load_json_text(text: str) -> Any:
    """Parse model JSON output, tolerating a Markdown code fence (plain JSON mode).

    Raises ``ValueError`` (``json.JSONDecodeError``) when the text is not JSON.
    """
    m = _FENCE.match(text)
    return json.loads(m.group(1) if m else text)


def _iter_parts(body: Any) -> Iterator[dict]:
    if isinstance(body, dict):
        if "type" in body:
            yield body
        for v in body.values():
            yield from _iter_parts(v)
    elif isinstance(body, list):
        for v in body:
            yield from _iter_parts(v)


def estimate_request(
    model: str, feature: str, body: dict, units: dict[str, float] | None = None
) -> CostEstimate:
    """Pre-flight price of one Responses request. Explicit ``units`` override the guesses.

    Guesses: SAM bills ``DEFAULT_SAM_WINDOW_FRAMES`` per video part and one image per image
    part; text models count ~1 token per 3 characters of JSON, ``SPARK_VIDEO_CLIP_TOKENS``
    per video and ``DEFAULT_IMAGE_TOKENS`` per image, and ``max_output_tokens`` (or
    ``DEFAULT_OUT_TOKENS``) out. Over-estimating is the safe direction for a cap.
    """
    parts = list(_iter_parts(body))
    videos = sum(1 for p in parts if p.get("type") == "input_video")
    images = sum(1 for p in parts if p.get("type") == "input_image")
    guess: dict[str, float] = {}
    if model == SAM:
        guess = {"frames": DEFAULT_SAM_WINDOW_FRAMES if videos else 0, "images": images}
    elif model in TOKEN_PRICES:
        text_tokens = len(json.dumps(body, ensure_ascii=False)) // 3
        guess = {
            "in_tokens": text_tokens
            + videos * SPARK_VIDEO_CLIP_TOKENS
            + images * DEFAULT_IMAGE_TOKENS,
            "out_tokens": int(body.get("max_output_tokens") or DEFAULT_OUT_TOKENS),
        }
    guess.update(units or {})
    ints = {"in_tokens", "out_tokens", "cached_in_tokens", "frames", "images"}
    kwargs = {k: (int(v) if k in ints else float(v)) for k, v in guess.items()}
    return estimate(model, feature, **kwargs)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class MetaClient:
    """The only path to the Meta Model API (see the module docstring for the order)."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        ledger: CallLedger | None = None,
        cache: ResponseCache | None = None,
        budget: BudgetGuard | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        *,
        rng: random.Random | None = None,
        max_retries: int = 2,
        backoff_base_s: float = 0.5,
        backoff_cap_s: float = 20.0,
        timeout_s: float = 20.0,
        cache_only: bool = False,
        use_cache: bool = True,
    ):
        self.settings = settings or get_settings()
        self.ledger = (
            ledger
            if ledger is not None
            else shared_ledger(getattr(self.settings, "ledger_path", None))
        )
        self.cache = cache if cache is not None else ResponseCache(self.settings.cache_dir / "meta")
        self._clock = clock or (lambda: datetime.now(UTC))
        # The default guard reads its spent totals from the ledger's book (durable when the
        # ledger is): one source of truth, shared with every guard over the same ledger.
        self.budget = (
            budget
            if budget is not None
            else BudgetGuard(self.settings, clock=self._clock, ledger=self.ledger)
        )
        self._sleep = sleep or time.sleep
        self._rng = rng or random.Random()  # noqa: S311 (jitter, not crypto)
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.cache_only = cache_only
        self.use_cache = use_cache
        self._http = httpx.Client(
            base_url=self.settings.meta_base_url,
            transport=transport,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
        )

    def __repr__(self) -> str:
        return (
            f"MetaClient(base_url={self.settings.meta_base_url!r}, "
            f"key={'set' if self.settings.model_api_key else 'missing'}, "
            f"cache_only={self.cache_only})"
        )

    __str__ = __repr__

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> MetaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- secrets -------------------------------------------------------------------------

    def _key(self) -> str:
        secret = self.settings.model_api_key
        key = secret.get_secret_value() if secret is not None else ""
        if not key:
            raise MetaAuthError(401, "", "MODEL_API_KEY is not set; live calls are unavailable")
        return key

    def _scrub(self, text: str) -> str:
        secret = self.settings.model_api_key
        key = secret.get_secret_value() if secret is not None else ""
        if key and key in text:
            text = text.replace(key, "***")
        return re.sub(r"(?i)bearer\s+\S+", "Bearer ***", text)

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key()}", "Accept": accept}

    # -- public API ----------------------------------------------------------------------

    def upload(self, path: Path) -> str:
        """Upload a file once (``POST /files``, purpose ``user_data``) and return its id.

        Uploads are not billed; the id is cached by file content so a window is uploaded once.
        """
        path = Path(path)
        key = "upload-" + file_hash(path)
        if self.use_cache:
            hit = self.cache.get(key)
            if hit and isinstance(hit.get("id"), str):
                return hit["id"]
        if self.cache_only:
            raise CacheMiss(f"cache-only mode: {path.name} was never uploaded")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        content = path.read_bytes()

        def send() -> dict:
            files = {"file": (path.name, content, mime)}
            return self._send_json("POST", "/files", files=files, data={"purpose": "user_data"})

        try:
            data, _ = self._with_retries(send)
        except MetaError as exc:
            log.warning("upload of %s failed: %s", path.name, exc)
            raise
        file_id = data.get("id")
        if not isinstance(file_id, str) or not file_id:
            raise MalformedResponse("upload response has no file id")
        if self.use_cache:
            self.cache.put(key, {"id": file_id, "filename": path.name})
        return file_id

    def responses(
        self,
        model: str,
        body: dict,
        purpose: str,
        visit_id: str | None = None,
        stream: bool = False,
        feature: str | None = None,
        units: dict[str, float] | None = None,
    ) -> RawResponse:
        """``POST /responses`` through allowlist, cache, budget, retries and ledger.

        ``units`` gives billed units the body cannot show (SAM ``frames`` per request,
        ``images``; token guesses). The returned dict carries ``_vigil`` provenance
        (``call_id``, ``cached``, ``req_hash``, ``model``) for the UI badge (NFR-022).
        """
        try:
            check_model(model)
        except ValueError as exc:
            raise ModelNotAllowed(str(exc)) from None
        full = {**body, "model": model}
        if stream:
            full["stream"] = True
        else:
            full.pop("stream", None)
        feature = feature or feature_for(purpose)
        est = estimate_request(model, feature, full, units)

        if stream:

            def send() -> dict:
                return self._send_stream("/responses", full)
        else:

            def send() -> dict:
                data = self._send_json("POST", "/responses", json=full)
                self._check_status(data)
                return data

        return self._execute(
            model, purpose, visit_id, feature, request_hash(model, full), est, send
        )

    def post_multipart(
        self,
        path: str,
        model: str,
        purpose: str,
        *,
        request_json: dict,
        files: dict[str, tuple[str, bytes, str]],
        content_hash: str,
        units: dict[str, float],
        visit_id: str | None = None,
        feature: str | None = None,
        cache_key: str | None = None,
        cache_filter: Callable[[dict], dict] | None = None,
    ) -> RawResponse:
        """A multipart model call (Voice Transcribe) through the same pipeline.

        ``files`` are sent from memory and never written anywhere. ``cache_key`` replaces the
        request hash as the response-cache key (Voice Transcribe keys by the audio SHA-256),
        and ``cache_filter`` reduces the response to what may be cached (only the transcript,
        NFR-002). The request bytes are never cached.
        """
        try:
            check_model(model)
        except ValueError as exc:
            raise ModelNotAllowed(str(exc)) from None
        feature = feature or feature_for(purpose)
        est = estimate_request(model, feature, request_json, units)
        req_hash = request_hash(
            model, {"path": path, "request": request_json, "content": content_hash}
        )
        form = {"request": (None, json.dumps(request_json), "application/json"), **files}

        def send() -> dict:
            return self._send_json("POST", path, files=form)

        return self._execute(
            model, purpose, visit_id, feature, req_hash, est, send,
            cache_key=cache_key, cache_filter=cache_filter,
        )  # fmt: skip

    # -- pipeline ------------------------------------------------------------------------

    def _execute(
        self,
        model: str,
        purpose: str,
        visit_id: str | None,
        feature: str,
        req_hash: str,
        est: CostEstimate,
        send: Callable[[], dict],
        *,
        cache_key: str | None = None,
        cache_filter: Callable[[dict], dict] | None = None,
    ) -> RawResponse:
        key = cache_key or req_hash
        funding = self._funding()
        if self.use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                row = self._log(
                    model, purpose, visit_id, req_hash, feature, cached=True, funding=funding
                )
                return self._annotate(hit, row)
        if self.cache_only:
            raise CacheMiss(f"cache-only mode: no cached {model} response for {purpose}")
        try:
            res = self._reserve(est)
        except BudgetExceeded as exc:
            self._log(
                model, purpose, visit_id, req_hash, feature,
                ok=False, error=str(exc), funding=funding,
            )  # fmt: skip
            raise
        if res is not None:
            funding = res.funding

        def before_retry(previous_billed: bool) -> None:
            # The billed attempt's estimate stays held; the next attempt needs its own.
            self._extend(res, est, est.usd if previous_billed else 0.0)

        t0 = time.perf_counter()
        try:
            try:
                data, billed = self._with_retries(send, before_retry)
            except (MetaError, BudgetExceeded) as exc:
                latency = int((time.perf_counter() - t0) * 1000)
                billed = int(getattr(exc, "billed_attempts", 0) or 0)
                cost = billed * est.usd
                error = str(exc)
                if billed:
                    error += f" ({billed} billed attempt{'s' if billed > 1 else ''} charged)"
                self._log(
                    model, purpose, visit_id, req_hash, feature,
                    ok=False, error=error, latency_ms=latency, cost=cost,
                    units=self._units(model, est), funding=funding,
                )  # fmt: skip
                raise
            latency = int((time.perf_counter() - t0) * 1000)
            in_t, out_t, cost = self._actual_cost(model, feature, data, est)
            cost += billed * est.usd  # failed attempts before the success were billed too
            row = self._log(
                model, purpose, visit_id, req_hash, feature,
                latency_ms=latency, cost=cost, in_tokens=in_t, out_tokens=out_t,
                units=self._units(model, est), funding=funding,
            )  # fmt: skip
        finally:
            # The ledger row has committed the spend (if any): stop holding the estimate.
            self._release(res)
        if self.use_cache:
            self._cache_put(key, data, model, cache_filter)
        return self._annotate(data, row)

    # -- budget --------------------------------------------------------------------------

    def _shares_book(self) -> bool:
        """True when the guard reads the ledger's book (a ledger row commits the spend)."""
        return getattr(self.budget, "book", None) is self.ledger.book

    def _reserve(self, est: CostEstimate) -> Reservation | None:
        reserve = getattr(self.budget, "reserve", None)
        if callable(reserve):
            return reserve(est)
        self.budget.check(est)
        return None

    def _extend(self, res: Reservation | None, est: CostEstimate, usd: float) -> None:
        if res is not None:
            self.budget.extend(res, usd)
        else:
            self.budget.check(est)

    def _release(self, res: Reservation | None) -> None:
        if res is not None:
            self.budget.release(res)

    def _commit(self, row: ModelCall, feature: str) -> None:
        """Add the row to the ledger; a guard on another book is charged directly."""
        self.ledger.add(row, feature)
        if row.cached or not row.cost_usd:
            return
        if self._shares_book():
            warn = getattr(self.budget, "warn", None)
            if callable(warn):
                warn(feature, row.funding)
        else:
            self.budget.record(row.cost_usd, feature, when=row.created_at, funding=row.funding)

    def _funding(self) -> Funding:
        """The ledger tag for a call made now (``credit`` unless the guard says ``paid``)."""
        funding_now = getattr(self.budget, "funding_now", None)
        return funding_now() if callable(funding_now) else "credit"

    def _cache_put(
        self, key: str, data: dict, model: str, cache_filter: Callable[[dict], dict] | None
    ) -> None:
        if cache_filter is not None:
            try:
                data = cache_filter(data)
            except Exception as exc:  # a filter failure must not fail the call
                log.warning("response not cached: %s", self._scrub(str(exc)))
                return
        self.cache.put(key, data, model=model)

    @staticmethod
    def _units(model: str, est: CostEstimate) -> float | None:
        if model == SAM:
            return float(est.frames or est.images)
        if model == VOICE:
            return est.audio_s
        return None

    @staticmethod
    def _actual_cost(
        model: str, feature: str, data: dict, est: CostEstimate
    ) -> tuple[int | None, int | None, float]:
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        if model in TOKEN_PRICES and usage and "input_tokens" in usage:
            in_t = int(usage.get("input_tokens") or 0)
            out_t = int(usage.get("output_tokens") or 0)
            details = usage.get("input_tokens_details") or {}
            cached = int(details.get("cached_tokens") or 0) if isinstance(details, dict) else 0
            actual = estimate(
                model, feature, in_tokens=in_t, out_tokens=out_t, cached_in_tokens=cached
            )
            return in_t, out_t, actual.usd
        # SAM and Voice bill by frames/images/seconds, which the response does not echo.
        if model in TOKEN_PRICES:
            return est.in_tokens, est.out_tokens, est.usd
        return None, None, est.usd

    def _annotate(self, data: dict, row: ModelCall) -> RawResponse:
        out = dict(data)
        out["_vigil"] = {
            "call_id": row.id,
            "cached": row.cached,
            "req_hash": row.req_hash,
            "model": row.model,
            "cost_usd": row.cost_usd,
            "latency_ms": row.latency_ms,
        }
        return out

    def _log(
        self,
        model: str,
        purpose: str,
        visit_id: str | None,
        req_hash: str,
        feature: str,
        *,
        cached: bool = False,
        ok: bool = True,
        error: str | None = None,
        latency_ms: int | None = 0,
        cost: float = 0.0,
        in_tokens: int | None = None,
        out_tokens: int | None = None,
        units: float | None = None,
        funding: Funding = "credit",
    ) -> ModelCall:
        row = ModelCall(
            id="mc_" + uuid.uuid4().hex[:16],
            model=model,
            purpose=purpose,
            visit_id=visit_id,
            req_hash=req_hash,
            latency_ms=latency_ms,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            units=units,
            cost_usd=cost,
            cached=cached,
            ok=ok,
            error=self._scrub(error)[:2000] if error else None,
            backend="api",
            feature=feature,
            funding=funding,
            created_at=self._clock(),
        )
        self._commit(row, feature)
        return row

    # -- transport -----------------------------------------------------------------------

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        base = min(self.backoff_cap_s, self.backoff_base_s * (2**attempt))
        delay = base + self._rng.uniform(0, base / 2)
        if retry_after is not None:
            delay = max(delay, min(retry_after, self.backoff_cap_s * 3))
        return delay

    def _with_retries(
        self,
        send: Callable[[], dict],
        before_retry: Callable[[bool], None] | None = None,
    ) -> tuple[dict, int]:
        """Send with retries; return the body and the number of billed failed attempts.

        Every attempt whose 2xx body was malformed or failed counts as billed (F5).
        ``before_retry(previous_billed)`` runs before each retry and may raise
        ``BudgetExceeded`` to stop retrying before a cap is crossed. Every error raised
        carries ``billed_attempts``.
        """
        last: _Retryable | None = None
        attempts = 0
        billed = 0
        for attempt in range(self.max_retries + 1):
            if attempt and before_retry is not None:
                assert last is not None
                try:
                    before_retry(last.billed)
                except BudgetExceeded as exc:
                    exc.billed_attempts = billed  # type: ignore[attr-defined]
                    exc.attempts = attempts  # type: ignore[attr-defined]
                    log.warning("Meta call retry refused by the budget guard: %s", exc)
                    raise
            attempts += 1
            try:
                return send(), billed
            except _Retryable as exc:
                last = exc
                billed += int(exc.billed)
                log.info("Meta call attempt %d failed (%s)", attempts, self._scrub(exc.detail))
                if attempt < self.max_retries:
                    self._sleep(self._backoff(attempt, exc.retry_after))
            except MetaError as exc:
                # A failed 2xx response (non-retryable code) was billed; 4xx and auth were not.
                exc.billed_attempts = billed + int(isinstance(exc, MetaResponseFailed))
                raise
        assert last is not None
        msg = self._scrub(f"{last.kind} after {attempts} attempts: {last.detail}")
        cls = MalformedResponse if last.kind == "malformed" else MetaUnavailable
        err = cls(msg, status=last.status, attempts=attempts)
        err.billed = billed > 0  # type: ignore[attr-defined]
        err.billed_attempts = billed
        raise err

    def _raise_for_status(self, resp: httpx.Response) -> None:
        status = resp.status_code
        if status < 400:
            return
        body = self._scrub(resp.text[:4000])
        if status == 429 or status >= 500:
            raise _Retryable("http", f"HTTP {status}: {body[:300]}", status, _retry_after(resp))
        if status in (401, 403):
            raise MetaAuthError(status, body)
        raise MetaHTTPError(status, body)

    def _send_json(self, method: str, path: str, **kw: Any) -> dict:
        try:
            resp = self._http.request(method, path, headers=self._headers(), **kw)
        except httpx.TimeoutException as exc:
            raise _Retryable(
                "timeout",
                f"timeout: {type(exc).__name__}",
                billed=isinstance(exc, httpx.ReadTimeout | httpx.WriteTimeout),
            ) from None
        except httpx.TransportError as exc:
            raise _Retryable(
                "network",
                f"network error: {type(exc).__name__}",
                billed=isinstance(
                    exc, httpx.ReadError | httpx.WriteError | httpx.RemoteProtocolError
                ),
            ) from None
        self._raise_for_status(resp)
        try:
            data = resp.json()
        except ValueError:
            raise _Retryable(
                "malformed", "response body is not JSON", resp.status_code, billed=True
            ) from None
        if not isinstance(data, dict):
            raise _Retryable("malformed", "response JSON is not an object", billed=True)
        return data

    def _check_status(self, data: dict) -> None:
        if data.get("status") != "failed":
            return
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        code = str(error.get("code") or "")
        msg = self._scrub(str(error.get("message") or "")[:500])
        if code in RETRYABLE_ERROR_CODES:
            raise _Retryable("http", f"response failed: {code} {msg}", billed=True)
        raise MetaResponseFailed(f"response failed: {code or 'unknown'} {msg}".strip())

    def _send_stream(self, path: str, body: dict) -> dict:
        started = False
        try:
            with self._http.stream(
                "POST", path, json=body, headers=self._headers("text/event-stream")
            ) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    self._raise_for_status(resp)
                started = True
                return self._parse_sse(resp.iter_lines())
        except httpx.TimeoutException as exc:
            raise _Retryable(
                "timeout",
                f"timeout: {type(exc).__name__}",
                billed=isinstance(exc, httpx.ReadTimeout | httpx.WriteTimeout),
            ) from None
        except httpx.TransportError as exc:
            raise _Retryable(
                "network",
                f"network error: {type(exc).__name__}",
                billed=started
                or isinstance(exc, httpx.ReadError | httpx.WriteError | httpx.RemoteProtocolError),
            ) from None

    def _parse_sse(self, lines: Iterable[str]) -> dict:
        deltas: list[str] = []
        final: dict | None = None
        for line in lines:
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except ValueError:
                raise _Retryable("malformed", "stream event is not JSON", billed=True) from None
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "response.output_text.delta":
                deltas.append(str(event.get("delta", "")))
            elif kind == "error":
                code = str(event.get("code") or "")
                msg = self._scrub(str(event.get("message") or ""))
                if code in RETRYABLE_ERROR_CODES:
                    raise _Retryable("http", f"stream error: {code} {msg}", billed=True)
                raise MetaResponseFailed(f"stream error: {code or 'unknown'} {msg}".strip())
            elif kind in ("response.completed", "response.failed", "response.incomplete"):
                response = event.get("response")
                final = dict(response) if isinstance(response, dict) else {}
                final.setdefault("status", kind.split(".", 1)[1])
        if final is None:
            raise _Retryable("malformed", "stream ended before response.completed", billed=True)
        self._check_status(final)
        final["output_text"] = "".join(deltas) if deltas else extract_text(final)
        final["deltas"] = deltas
        return final
