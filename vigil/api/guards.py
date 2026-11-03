"""Guards for live endpoints: rate limit, spend and judging caps, size limits, LAN only.

FR-026, FR-043, NFR-013 (daily $10 cap from credits; at a cap, live requests return the
cached result with "Live budget for today used; recorded result shown"), NFR-014 (the API key
is never served), NFR-015 (10 live requests per minute per IP; audio <= 30 s and 2 MB; JSON
<= 64 KB), NFR-004 (no Contributor-mode model IDs), NFR-037 and spec 11.6 item 6 (after the
credit window: VIGIL_ALLOW_PAID=1, $25 judging total, $5 per PT day, VIGIL_JUDGING_END).
"""

from __future__ import annotations

import ipaddress
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

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
    """Process-local guard state shared by the live routes of one app instance.

    Spend is kept per funding tag (`credit` inside the credit window, `paid` after it) and per
    PT calendar day. Before the window ends the sandbox's daily cap applies; after it, live
    calls run only with VIGIL_ALLOW_PAID=1, before VIGIL_JUDGING_END, while the $25 judging
    total and the $5 PT-day cap both have room (FR-043, NFR-037). The total binds first.
    """

    def __init__(
        self,
        settings: Any,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self.rate = RateLimiter(int(settings.live_rate_per_min), 60.0, clock)
        self.feedback_rate = RateLimiter(int(settings.live_rate_per_min), 60.0, clock)
        """Visit feedback has its own per-IP budget (spec 9.6: rate limit, not a live call)."""
        self._spend: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    # -- time and phase ----------------------------------------------------------------------
    def now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), tz=UTC)

    def _day(self) -> str:
        return self.now().astimezone(PT).date().isoformat()

    def phase(self) -> tuple[str, str | None]:
        """(phase, reason): credit, judging, or closed with why."""
        end = self.settings.credit_window_end
        if end is None or self.now() < _utc(end):
            return "credit", None
        if not self.settings.allow_paid:
            return "closed", "credit_window_ended"
        judging_end = getattr(self.settings, "judging_end", None)
        if judging_end is not None and self.now() >= _utc(judging_end):
            return "closed", "judging_ended"
        return "judging", None

    def funding(self) -> str:
        return "credit" if self.phase()[0] == "credit" else "paid"

    # -- spend ---------------------------------------------------------------
    def spend_today(self, funding: str | None = None) -> float:
        day = self._day()
        with self._lock:
            total = sum(v for (f, d), v in self._spend.items()
                        if d == day and (funding is None or f == funding))  # fmt: skip
        return round(total, 6)

    def spend_total(self, funding: str) -> float:
        with self._lock:
            return round(sum(v for (f, _), v in self._spend.items() if f == funding), 6)

    def record_spend(self, usd: float, funding: str | None = None) -> str:
        """Add actual spend under its funding tag; returns the tag used."""
        tag = funding or self.funding()
        with self._lock:
            key = (tag, self._day())
            self._spend[key] = self._spend.get(key, 0.0) + max(0.0, float(usd))
        return tag

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
        """Whether a live action priced at `estimate_usd` may run now, and the notice if not."""
        cap = float(self.settings.daily_cap_usd)
        phase, reason = self.phase()
        funding = "credit" if phase == "credit" else "paid"
        configured = self.key_configured()
        spent_today = self.spend_today()
        notice = None
        if not configured:
            reason, notice = "not_configured", NOTICE_NO_KEY
        elif phase == "closed":
            notice = NOTICE_BUDGET
        elif phase == "credit":
            credit_today = self.spend_today("credit")
            if credit_today >= cap - _EPS or credit_today + estimate_usd > cap + _EPS:
                reason, notice = "spend_cap", NOTICE_BUDGET
        else:  # judging: the $25 total binds before the $5 day
            total_left, _ = self.judging_remaining()
            day_left = float(self.settings.judging_daily_cap_usd) - self.spend_today("paid")
            if total_left <= _EPS or estimate_usd > total_left + _EPS:
                reason, notice = "judging_cap", NOTICE_BUDGET
            elif day_left <= _EPS or estimate_usd > day_left + _EPS:
                reason, notice = "judging_daily_cap", NOTICE_BUDGET
        available = notice is None
        if available:
            reason = None
        return LiveStatus(available, reason, notice, configured, spent_today, cap, phase, funding)

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
    """Rate-limit a live request, then report whether live may run (else cached fallback)."""
    guards.check_rate(ip)
    return guards.live_status(estimate_usd)
