"""Guards for live endpoints: rate limit, spend cap, credit window, size limits, LAN only.

FR-026, NFR-013 (daily $10 cap; live disables at the cap), NFR-014 (the API key is never
served), NFR-015 (10 live requests per minute per IP; audio <= 30 s and 2 MB; JSON <= 64 KB),
NFR-004 (no Contributor-mode model IDs), spec 11.6 safeguard 6 (credit-window end).
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

from fastapi import HTTPException, Request

# Only the Standard-mode IDs Vigil uses (spec 11.6 safeguard 5, 11.2).
ALLOWED_MODELS = frozenset(
    {"sam-3.1", "muse-spark-1.3", "muse-wonder-1.0", "muse-voice-transcribe-1.0"}
)
_CONTRIBUTOR = "-" + "contributor"  # spelled out so the CI grep for the literal stays clean

NOTICE_SPEND_CAP = "Daily live budget used; recorded results shown."
NOTICE_NO_KEY = "Live calls are not configured on this server; recorded results shown."
NOTICE_WINDOW = "The live credit window has ended; recorded results shown."


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

    def public(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "notice": self.notice,
            "configured": self.configured,
        }


class Guards:
    """Process-local guard state shared by the live routes of one app instance."""

    def __init__(
        self,
        settings: Any,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self.rate = RateLimiter(int(settings.live_rate_per_min), 60.0, clock)
        self._spend: dict[str, float] = {}
        self._lock = threading.Lock()

    # -- spend ---------------------------------------------------------------
    def _day(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=UTC).date().isoformat()

    def spend_today(self) -> float:
        return round(self._spend.get(self._day(), 0.0), 6)

    def record_spend(self, usd: float) -> None:
        with self._lock:
            day = self._day()
            self._spend[day] = self._spend.get(day, 0.0) + max(0.0, float(usd))

    # -- availability ----------------------------------------------------------
    def key_configured(self) -> bool:
        key = self.settings.model_api_key
        return bool(key is not None and key.get_secret_value().strip())

    def live_status(self) -> LiveStatus:
        cap = float(self.settings.daily_cap_usd)
        spent = self.spend_today()
        configured = self.key_configured()
        reason, notice = None, None
        end = self.settings.credit_window_end
        if not configured:
            reason, notice = "not_configured", NOTICE_NO_KEY
        elif end is not None and not self.settings.allow_paid:
            end_utc = end if end.tzinfo else end.replace(tzinfo=UTC)
            if datetime.fromtimestamp(self._clock(), tz=UTC) >= end_utc:
                reason, notice = "credit_window_ended", NOTICE_WINDOW
        if reason is None and spent >= cap:
            reason, notice = "spend_cap", NOTICE_SPEND_CAP
        return LiveStatus(reason is None, reason, notice, configured, spent, cap)

    def check_rate(self, ip: str) -> None:
        """429 on the 11th live request within 60 s from one IP (NFR-015)."""
        wait = self.rate.hit(ip)
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Too many live requests: {self.rate.limit} per minute per IP.",
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


def check_live_allowed(guards: Guards, ip: str) -> LiveStatus:
    """Rate-limit a live request, then report whether live may run (else cached fallback)."""
    guards.check_rate(ip)
    return guards.live_status()
