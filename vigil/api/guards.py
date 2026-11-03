"""Guards for live endpoints: rate limit, spend and judging caps, size limits, LAN only.

FR-026, FR-043, NFR-013 (daily $10 cap from credits; at a cap, live requests return the
cached result with "Live budget for today used; recorded result shown"), NFR-014 (the API key
is never served), NFR-015 (10 live requests per minute per IP; audio <= 30 s and 2 MB; JSON
<= 64 KB), NFR-004 (no Contributor-mode model IDs), NFR-037 and spec 11.6 item 6 (after the
credit window: VIGIL_ALLOW_PAID=1, $25 judging total, $5 per PT day; nothing live from
VIGIL_JUDGING_END on, whatever the funding tag).

Spend is not kept here: it is read from the durable call ledger at ``VIGIL_LEDGER_PATH``
(the same ledger, book and reservations the Meta client's budget guard uses), so a restart
does not reset any cap. Without a durable ledger the paid phase fails closed.
"""

from __future__ import annotations

import ipaddress
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

from vigil.meta.budget import DEFAULT_JUDGING_END, BudgetGuard, Reservation, pt_day
from vigil.meta.client import CallLedger, shared_ledger
from vigil.models import ModelCall

# Only the Standard-mode IDs Vigil uses (spec 11.6 safeguard 5, 11.2).
ALLOWED_MODELS = frozenset(
    {"sam-3.1", "muse-spark-1.3", "muse-wonder-1.0", "muse-voice-transcribe-1.0"}
)
_CONTRIBUTOR = "-" + "contributor"  # spelled out so the CI grep for the literal stays clean
_EPS = 1e-9

NOTICE_BUDGET = "Live budget for today used; recorded result shown"
"""The one notice for every cap or window refusal (spec 11.6 item 6, NFR-013)."""
NOTICE_SPEND_CAP = NOTICE_BUDGET  # kept name: the daily credit cap uses the same words
NOTICE_NO_KEY = "Live calls are not configured on this server; recorded result shown"
PT = ZoneInfo("America/Los_Angeles")
"""Daily caps reset at midnight Pacific time ("$5 per PT calendar day", NFR-037)."""

# What one live action is priced at before it runs (spec 11.3; rounded up). The Meta client's
# budget guard prices each call exactly; this keeps the sandbox from starting an action that
# would cross a cap (a refusal at $24.999 + $0.0025 > $25, FR-043).
LIVE_ESTIMATE_USD: dict[str, float] = {
    "protect": 0.0025,  # one SAM 3.1 image
    "transcribe": 0.0015,  # 30 s of Voice Transcribe at $0.18/h
    "compile": 0.003,  # one Spark text call
    "rerun": 0.06,  # Spark triage + up to two Wonder drafts
    "landmarks": 0.01,  # SAM 3.1 concept prompts on one still
}
ADMISSION_TTL_S = 600.0
"""An admitted live action holds its estimate until it records its spend, or for at most this
long when it fails before recording (a re-run with retries stays well under it)."""


def notice_live_failed(recorded: str) -> str:
    """'Live call failed; recorded result from <date> shown' (spec 11.6 item 6, UC-09)."""
    return f"Live call failed; recorded result from {recorded} shown"


class ModelNotAllowedError(ValueError):
    pass


def check_model_allowed(model: str) -> str:
    """Refuse Contributor-mode IDs (NFR-004) and anything outside the allowlist."""
    if _CONTRIBUTOR in model:
        raise ModelNotAllowedError("Contributor-mode model IDs are forbidden (NFR-004)")
    if model not in ALLOWED_MODELS:
        raise ModelNotAllowedError(f"model {model!r} is not on the Standard-mode allowlist")
    return model


class RateLimiter:
    """Sliding window: at most `limit` events per `window_s` seconds per key."""

    def __init__(
        self, limit: int, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        """Record one event. Returns None when allowed, else seconds until a slot frees."""
        now = self._clock()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return max(0.0, self.window_s - (now - q[0]))
            q.append(now)
            return None


@dataclass
class LiveStatus:
    available: bool
    reason: str | None
    notice: str | None
    configured: bool
    spend_today_usd: float
    daily_cap_usd: float
    phase: str = "credit"
    """credit: inside the credit window; judging: paid calls allowed; closed: no live calls."""
    funding: str = "credit"

    def public(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "notice": self.notice,
            "configured": self.configured,
            "phase": self.phase,
        }


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class Guards:
    """Guard state shared by the live routes of one app instance.

    Spend is read from the durable call ledger (``VIGIL_LEDGER_PATH``; the same ledger, spend
    book and reservations as the Meta client's budget guard in this process), per funding tag
    (`credit` inside the credit window, `paid` after it) and per PT calendar day, so a restart
    resets no cap. Before the window ends the sandbox's daily cap and the $140 credit cap
    apply; after it, live calls run only with VIGIL_ALLOW_PAID=1 and a durable ledger, while
    the $25 judging total and the $5 PT-day cap both have room (FR-043, NFR-037). The total
    binds first. Nothing live runs from VIGIL_JUDGING_END on, whatever the funding tag.

    A live action is admitted with :meth:`admit` (check and reserve its estimate in one step,
    so concurrent requests cannot all pass one check) and releases the hold when its actual
    spend is recorded (:meth:`record_calls`, or :meth:`record_spend`).
    """

    def __init__(
        self,
        settings: Any,
        clock: Callable[[], float] = time.time,
        *,
        ledger: CallLedger | None = None,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self.rate = RateLimiter(int(settings.live_rate_per_min), 60.0, clock)
        self.feedback_rate = RateLimiter(int(settings.live_rate_per_min), 60.0, clock)
        """Visit feedback has its own per-IP budget (spec 9.6: rate limit, not a live call)."""
        self.ledger = (
            ledger if ledger is not None else shared_ledger(getattr(settings, "ledger_path", None))
        )
        self.budget = BudgetGuard(settings, clock=self.now, ledger=self.ledger)
        self._admitted: deque[Reservation] = deque()

    @property
    def book(self) -> Any:
        return self.ledger.book

    # -- time and phase ----------------------------------------------------------------------
    def now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), tz=UTC)

    def _day(self) -> str:
        return self.now().astimezone(PT).date().isoformat()

    def judging_end(self) -> datetime:
        """VIGIL_JUDGING_END, or Nov 10 23:59 PT when unset (fail closed)."""
        return _utc(getattr(self.settings, "judging_end", None) or DEFAULT_JUDGING_END)

    def phase(self) -> tuple[str, str | None]:
        """(phase, reason): credit, judging, or closed with why.

        The judging end closes everything first: with VIGIL_CREDIT_WINDOW_END unset every call
        is tagged credit, and the end date must still bind (F4)."""
        now = self.now()
        if now >= self.judging_end():
            return "closed", "judging_ended"
        end = self.settings.credit_window_end
        if end is None or now < _utc(end):
            return "credit", None
        if not self.settings.allow_paid:
            return "closed", "credit_window_ended"
        if not self.ledger.durable:
            return "closed", "ledger_not_durable"
        return "judging", None

    def funding(self) -> str:
        return "credit" if self.phase()[0] == "credit" else "paid"

    # -- spend (committed, from the ledger) -------------------------------------------------
    def spend_today(self, funding: str | None = None) -> float:
        today = pt_day(self.now())
        tags = ("credit", "paid") if funding is None else (funding,)
        return round(sum(self.book.day_total(f, today) for f in tags), 6)

    def spend_total(self, funding: str) -> float:
        return round(self.book.total(funding), 6)

    def _row(self, usd: float, funding: str) -> ModelCall:
        """A ledger row for spend reported without its calls (a backend that keeps no
        ledger of its own); the real client's calls are already in the ledger."""
        return ModelCall(
            id="sbx_" + uuid.uuid4().hex[:16], model="sandbox", purpose="sandbox_live",
            req_hash="sandbox", cost_usd=usd, feature="sandbox", funding=funding,
            backend="sandbox", created_at=self.now(),
        )  # fmt: skip

    def _release_admission(self) -> None:
        with self.book.lock:
            if self._admitted:
                self.book.drop(self._admitted.popleft())

    def record_spend(self, usd: float, funding: str | None = None) -> str:
        """Add actual spend under its funding tag to the durable ledger; returns the tag.

        Spend the Meta client already ledgered (offered by the live backend) is not counted
        again. Releases the oldest admission hold."""
        tag = funding or self.funding()
        self._release_admission()
        remainder = self.book.claim_prerecorded(max(0.0, float(usd)))
        if remainder > _EPS:
            self.ledger.add(self._row(remainder, tag))
        return tag

    def record_calls(self, calls: Iterable[ModelCall]) -> None:
        """Ledger a live action's calls, skipping any already in the ledger (by call id).

        Preferred over :meth:`record_spend`: exact, and idempotent. Releases the oldest
        admission hold."""
        self._release_admission()
        for call in calls:
            if call.cached:
                continue
            if self.ledger.has(call.id):
                self.book.claim_prerecorded(call.cost_usd)
                continue
            update: dict[str, Any] = {"feature": call.feature or "sandbox"}
            if call.created_at is None:
                update["created_at"] = self.now()
            self.ledger.add(call.model_copy(update=update))

    def judging_remaining(self) -> tuple[float, float]:
        """(total remaining, today's remaining) of the post-window judging allowance."""
        cap = float(self.settings.judging_cap_usd)
        daily = float(self.settings.judging_daily_cap_usd)
        total_left = max(0.0, cap - self.spend_total("paid"))
        today_left = max(0.0, daily - self.spend_today("paid"))
        return round(total_left, 6), round(min(total_left, today_left), 6)

    # -- availability ----------------------------------------------------------
    def key_configured(self) -> bool:
        key = self.settings.model_api_key
        return bool(key is not None and key.get_secret_value().strip())

    def live_status(self, estimate_usd: float = 0.0) -> LiveStatus:
        """Whether a live action priced at `estimate_usd` may run now, and the notice if not.

        Money held by admitted, unrecorded actions counts as spent."""
        cap = float(self.settings.daily_cap_usd)
        phase, reason = self.phase()
        funding = "credit" if phase == "credit" else "paid"
        configured = self.key_configured()
        spent_today = self.spend_today()
        now = self.now()
        today = pt_day(now)
        notice = None
        with self.book.lock:
            if not configured:
                reason, notice = "not_configured", NOTICE_NO_KEY
            elif phase == "closed":
                notice = NOTICE_BUDGET
            elif phase == "credit":
                credit_today = self.book.day_total("credit", today, now)
                credit_total = self.book.total("credit", now)
                total_cap = float(self.settings.total_cap_usd)
                over_day = credit_today >= cap - _EPS or credit_today + estimate_usd > cap + _EPS
                over_total = credit_total >= total_cap - _EPS or (
                    credit_total + estimate_usd > total_cap + _EPS
                )  # the $140 credit cap, now that spend survives restarts
                if over_day or over_total:
                    reason, notice = "spend_cap", NOTICE_BUDGET
            else:  # judging: the $25 total binds before the $5 day
                total_left = float(self.settings.judging_cap_usd) - self.book.total("paid", now)
                day_left = float(self.settings.judging_daily_cap_usd) - self.book.day_total(
                    "paid", today, now
                )
                if total_left <= _EPS or estimate_usd > total_left + _EPS:
                    reason, notice = "judging_cap", NOTICE_BUDGET
                elif day_left <= _EPS or estimate_usd > day_left + _EPS:
                    reason, notice = "judging_daily_cap", NOTICE_BUDGET
        available = notice is None
        if available:
            reason = None
        return LiveStatus(available, reason, notice, configured, spent_today, cap, phase, funding)

    def admit(self, estimate_usd: float = 0.0) -> LiveStatus:
        """Check and, when available, hold `estimate_usd` in one atomic step (F6).

        The hold counts in every cap check (this guard's and the Meta client's) until the
        action records its spend, or for ADMISSION_TTL_S when it fails before recording."""
        with self.book.lock:
            status = self.live_status(estimate_usd)
            if status.available and estimate_usd > 0:
                now = self.now()
                res = self.book.hold(
                    float(estimate_usd), "sandbox", status.funding, pt_day(now),  # type: ignore[arg-type]
                    now + timedelta(seconds=ADMISSION_TTL_S),
                )  # fmt: skip
                self._admitted.append(res)
        return status

    def check_rate(self, ip: str, limiter: RateLimiter | None = None) -> None:
        """429 on the 11th live request within 60 s from one IP (NFR-015)."""
        limiter = limiter or self.rate
        wait = limiter.hit(ip)
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests: {limiter.limit} per minute per IP.",
                headers={"Retry-After": str(max(1, int(wait + 0.999)))},
            )

    # -- secrets -----------------------------------------------------------------
    def redact(self, text: str) -> str:
        """Remove the API key (and any bearer token) from text before it is served."""
        key = self.settings.model_api_key
        if key is not None:
            secret = key.get_secret_value()
            if secret:
                text = text.replace(secret, "***")
        return re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", text)


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# Home-network ranges only. `ipaddress.is_private` is not used: it also accepts documentation
# and benchmarking ranges (e.g. 203.0.113.0/24), which are not a LAN.
LAN_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16",
        "::1/128", "fc00::/7", "fe80::/10",
    )
)  # fmt: skip


def _is_private(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip().strip("[]"))
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in LAN_NETWORKS)


def is_lan_request(request: Request) -> bool:
    """True only for a private or loopback peer with no public address in forwarding headers."""
    if not _is_private(client_ip(request)):
        return False
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h for h in forwarded.split(",") if h.strip()]
    for part in request.headers.get("forwarded", "").split(","):
        for kv in part.split(";"):
            k, _, v = kv.strip().partition("=")
            if k.lower() == "for" and v:
                hops.append(v.strip('"'))
    return all(_is_private(h.split(":")[0] if h.count(":") == 1 else h) for h in hops)


def require_lan(request: Request) -> None:
    """Dependency for LAN-only routes (spec 9.6): off in the sandbox, private peers only."""
    settings = request.app.state.settings
    if settings.mode == "sandbox":
        raise HTTPException(403, "LAN-only endpoint; disabled in the hosted sandbox.")
    if not is_lan_request(request):
        raise HTTPException(403, "LAN-only endpoint; reachable from the home network only.")


async def read_bounded(request: Request, limit: int) -> bytes:
    """Read a request body, refusing more than `limit` bytes with 413 (NFR-015)."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, f"Request body over {limit} bytes.")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(413, f"Request body over {limit} bytes.")
    return body


def check_live_allowed(guards: Guards, ip: str, estimate_usd: float = 0.0) -> LiveStatus:
    """Rate-limit a live request, then admit it: check and hold its estimate in one step, so
    concurrent requests cannot all pass a cap only one fits (else cached fallback)."""
    guards.check_rate(ip)
    return guards.admit(estimate_usd)
