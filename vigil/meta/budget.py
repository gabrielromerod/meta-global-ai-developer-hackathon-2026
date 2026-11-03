"""Budget guard: price first; credit, feature, daily and judging caps (FR-043).

Every live call is priced from the spec 11.3 table (confirmed against
https://dev.meta.ai/docs/pricing-rate-limits on 2026-11-02) before it is sent. Spend is
tagged ``credit`` or ``paid`` (paid = from ``VIGIL_CREDIT_WINDOW_END`` on, spec 9.3).

* Credit-funded calls are refused when they *would* cross the $140 credit cap (credit spend
  only, NFR-036), their feature budget (spec 11.4) or the daily cap.
* After the window, paid calls are refused unless the owner set ``VIGIL_ALLOW_PAID=1``,
  refused without a durable ledger (``VIGIL_LEDGER_PATH``, fail closed), and refused when
  they would cross the judging cap ($25 in total) or its daily cap ($5 per PT calendar day)
  (NFR-037).
* No live call of any funding is admitted from ``VIGIL_JUDGING_END`` (Nov 10, 23:59 PT) on.

Spend is read from a :class:`SpendBook` that indexes the durable call ledger, so caps survive
a restart. A call reserves its estimate before it is sent (pending money counts in every
check) and settles to its actual cost after. Every refusal names the cap. Warnings fire once
each at 50, 75 and 90% of every cap.
"""

from __future__ import annotations

import itertools
import logging
import math
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from vigil.models import CostEstimate, Funding, ModelCall
from vigil.settings import Settings, get_settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Price table (spec 11.3, Standard mode)
# ---------------------------------------------------------------------------

SAM = "sam-3.1"
SPARK = "muse-spark-1.3"
WONDER = "muse-wonder-1.0"
VOICE = "muse-voice-transcribe-1.0"

ALLOWED_MODELS: frozenset[str] = frozenset({SAM, SPARK, WONDER, VOICE})
"""The only model IDs Vigil may call (spec 11.6 item 5, NFR-004)."""

SAM_USD_PER_FRAME = 0.20 / 1000
SAM_USD_PER_IMAGE = 2.50 / 1000
SAM_MIN_FRAMES_PER_REQUEST = 50
VOICE_USD_PER_HOUR = 0.18


@dataclass(frozen=True)
class TokenPrice:
    input_per_m: float
    output_per_m: float
    cached_input_per_m: float


TOKEN_PRICES: dict[str, TokenPrice] = {
    SPARK: TokenPrice(input_per_m=1.25, output_per_m=4.25, cached_input_per_m=0.15),
    WONDER: TokenPrice(input_per_m=4.00, output_per_m=20.00, cached_input_per_m=0.20),
}

SPARK_VIDEO_CLIP_TOKENS = 30_000
"""Planning assumption for one 10 s clip sent to Spark until T-03 measures it (spec 11.3)."""

# ---------------------------------------------------------------------------
# Feature budgets (spec 11.4 and 11.5)
# ---------------------------------------------------------------------------

FEATURE_CAPS: dict[str, float] = {
    "smoke": 1.0,  # smoke tests, T-03
    "perception_demo": 8.0,  # SAM video, 5 demo scenarios (11.4: 36,000 frames = $7.20)
    "perception_all": 22.0,  # SAM video for all 12 scenarios, only if H-02 fails
    "appearance": 16.0,  # Spark appearance notes
    "story": 4.0,  # Wonder stories
    "triage": 1.0,  # Spark triage fallback
    "rule_compile": 1.0,  # rule compile and tap-to-protect tests (Spark text, SAM image)
    "baseline": 3.0,  # naive baseline, Spark video
    "voice": 0.10,  # voice rules, P2
    "sandbox": 20.0,  # hosted sandbox live buttons until the window ends
    "video": 2.0,  # live calls while recording the video
    "live_home": 15.0,  # live home testing through the API, only if H-02 fails (11.5)
    "other": 1.0,  # not in 11.4: catch-all so an unattributed call is still capped
}

_PURPOSE_FEATURES: tuple[tuple[str, str], ...] = (
    ("smoke", "smoke"),
    ("baseline", "baseline"),
    ("appearance", "appearance"),
    ("notes", "appearance"),
    ("story", "story"),
    ("wonder", "story"),
    ("triage", "triage"),
    ("rule", "rule_compile"),
    ("compile", "rule_compile"),
    ("protect", "rule_compile"),
    ("segment_point", "rule_compile"),
    ("tap", "rule_compile"),
    ("landmark", "rule_compile"),  # SAM image calls on a still (FR-037), like tap-to-protect
    ("voice", "voice"),
    ("transcribe", "voice"),
    ("asr", "voice"),
    ("sandbox", "sandbox"),
    ("live", "sandbox"),
    ("track", "perception_demo"),
    ("sam", "perception_demo"),
    ("perception", "perception_demo"),
)

CONFIRM_THRESHOLD_USD = 5.0
"""Batch commands need --confirm above this estimate (spec 11.6 item 3)."""

WARN_AT: tuple[int, ...] = (50, 75, 90)
_EPS = 1e-9


def feature_for(purpose: str) -> str:
    """Map a call purpose to its spec 11.4 feature budget ("other" when unknown)."""
    p = purpose.lower()
    if p in FEATURE_CAPS:
        return p
    for needle, feature in _PURPOSE_FEATURES:
        if needle in p:
            return feature
    return "other"


def check_model(model: str) -> None:
    """Refuse anything outside the Standard-mode allowlist (NFR-004)."""
    if "contributor" in model.lower():
        raise ValueError(
            f"model {model!r} is a Contributor-mode ID: refused, not on the allowlist (NFR-004)"
        )
    if model not in ALLOWED_MODELS:
        raise ValueError(f"model {model!r} is not on the allowlist {sorted(ALLOWED_MODELS)}")


def estimate(
    model: str,
    feature: str,
    *,
    in_tokens: int = 0,
    out_tokens: int = 0,
    cached_in_tokens: int = 0,
    frames: int = 0,
    images: int = 0,
    audio_s: float = 0.0,
) -> CostEstimate:
    """Price one request from the spec 11.3 table.

    ``frames`` are the video frames of one SAM request (billed at least 50 when > 0);
    ``cached_in_tokens`` is the part of ``in_tokens`` billed at the cached-input rate;
    ``audio_s`` is metered in whole seconds, rounded down.
    """
    check_model(model)
    usd = 0.0
    billed_frames = 0
    billed_audio = 0.0
    if model == SAM:
        if frames > 0:
            billed_frames = max(int(frames), SAM_MIN_FRAMES_PER_REQUEST)
        usd = billed_frames * SAM_USD_PER_FRAME + images * SAM_USD_PER_IMAGE
    elif model == VOICE:
        billed_audio = float(math.floor(audio_s))
        usd = billed_audio / 3600.0 * VOICE_USD_PER_HOUR
    else:
        price = TOKEN_PRICES[model]
        cached = min(cached_in_tokens, in_tokens)
        usd = (
            (in_tokens - cached) * price.input_per_m
            + cached * price.cached_input_per_m
            + out_tokens * price.output_per_m
        ) / 1e6
    return CostEstimate(
        model=model,
        feature=feature,
        usd=usd,
        in_tokens=in_tokens,
        out_tokens=out_tokens,
        frames=billed_frames,
        images=images,
        audio_s=billed_audio,
    )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

CAP_LABELS: dict[str, str] = {
    "total": "credit cap (credit-funded spend only)",
    "daily": "daily cap",
    "judging": "judging cap (VIGIL_JUDGING_CAP_USD, post-window paid spend)",
    "judging_daily": "judging daily cap (paid spend per PT calendar day)",
    "ledger": "durable spend ledger (VIGIL_LEDGER_PATH)",
}
"""Human names used in refusal messages, so every refusal names the cap it hit."""


def cap_label(cap: str) -> str:
    if cap.startswith("feature:"):
        return f"feature budget {cap.split(':', 1)[1]!r} (spec 11.4)"
    return CAP_LABELS.get(cap, cap)


class BudgetExceeded(RuntimeError):
    """A live call was refused because it would cross a cap. Cached mode continues."""

    fallback = True

    def __init__(self, cap: str, limit: float, spent: float, requested: float, msg: str = ""):
        self.cap = cap
        self.limit = limit
        self.spent = spent
        self.requested = requested
        super().__init__(
            msg
            or (
                f"budget cap {cap!r} ({cap_label(cap)}) would be crossed: spent ${spent:.4f} + "
                f"${requested:.4f} > ${limit:.2f}; live call refused, cached mode continues"
            )
        )


class PaidCallsDisabled(BudgetExceeded):
    """The credit window has ended and VIGIL_ALLOW_PAID is not set (NFR-037)."""

    def __init__(self, window_end: datetime, requested: float):
        super().__init__(
            "credit_window",
            0.0,
            0.0,
            requested,
            f"credit window ended at {window_end.isoformat()}; paid calls are disabled "
            "unless the owner sets VIGIL_ALLOW_PAID=1 (NFR-037); cached mode continues",
        )
        self.window_end = window_end


class JudgingEnded(BudgetExceeded):
    """VIGIL_JUDGING_END has passed: no live call after it, whatever the funding tag or
    VIGIL_ALLOW_PAID say (F4: with the window end unset, every call is tagged credit)."""

    def __init__(self, judging_end: datetime, requested: float):
        super().__init__(
            "judging_end",
            0.0,
            0.0,
            requested,
            f"VIGIL_JUDGING_END ({judging_end.isoformat()}) has passed; no live call (paid or "
            "credit) after it (NFR-037); cached mode continues",
        )
        self.judging_end = judging_end


class LedgerNotDurable(BudgetExceeded):
    """No durable spend ledger (VIGIL_LEDGER_PATH unset or not writable): paid calls are
    refused, because a restart would forget their spend (NFR-037, fail closed)."""

    def __init__(self, requested: float):
        super().__init__(
            "ledger",
            0.0,
            0.0,
            requested,
            "no durable spend ledger (VIGIL_LEDGER_PATH unset or not writable): paid live "
            "calls are refused so a restart cannot reset the caps (NFR-037); cached mode "
            "continues",
        )


class ConfirmRequired(RuntimeError):
    """A batch estimate is above the --confirm threshold (spec 11.6 item 3)."""

    def __init__(self, usd: float, threshold: float):
        self.usd = usd
        self.threshold = threshold
        super().__init__(
            f"estimated batch cost ${usd:.2f} is above ${threshold:.2f}; re-run with --confirm"
        )


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

BUDGET_TZ = ZoneInfo("America/Los_Angeles")
"""Daily caps reset at midnight Pacific time (NFR-013, NFR-037: "per PT calendar day")."""

DEFAULT_JUDGING_END = datetime(2026, 11, 10, 23, 59, tzinfo=BUDGET_TZ)
"""Spec 11.6 item 6: no paid call after Nov 10, 23:59 PT. Used when VIGIL_JUDGING_END is unset,
so a missing setting fails closed rather than leaving paid calls open-ended."""


def _utc(dt: datetime) -> datetime:
    """Naive datetimes are read as UTC (the settings convention); aware ones are converted."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def pt_day(when: datetime) -> date:
    """The Pacific calendar day of an instant (naive instants are UTC)."""
    return _utc(when).astimezone(BUDGET_TZ).date()


@dataclass
class Reservation:
    """Money held for a call that is admitted but not yet settled (F6).

    Every cap check counts pending reservations, so two concurrent calls cannot both pass a
    check that only one of them fits. ``expires`` (UTC) lets an admission that never settles
    (its caller failed before recording) stop holding the money.
    """

    id: int
    usd: float
    feature: str
    funding: Funding
    day: date
    expires: datetime | None = None


class SpendBook:
    """Committed spend by funding tag, PT day and feature, plus pending reservations.

    One book indexes one call ledger: every non-cached ledger row with a cost is committed
    here (``add_row``), so every guard built over the same ledger (the Meta client's and the
    sandbox's) reads the same totals. ``durable`` is True only while the ledger persists to
    SQLite; paid calls are refused otherwise (fail closed, NFR-037). ``lock`` is re-entrant
    and makes check-and-reserve one step.
    """

    def __init__(self, durable: bool = False) -> None:
        self.lock = threading.RLock()
        self.durable = durable
        self._total: dict[str, float] = {"credit": 0.0, "paid": 0.0}
        self._by_day: dict[tuple[str, date], float] = {}
        self._by_feature: dict[str, float] = {}  # credit-funded only (spec 11.4 budgets)
        self._pending: dict[int, Reservation] = {}
        self._ids = itertools.count(1)
        self._prerecorded = 0.0

    # -- committed -----------------------------------------------------------------------

    def commit(self, usd: float, feature: str, funding: Funding, day: date | None) -> None:
        """Add actual spend. ``day`` None (a row without a timestamp) counts in totals only."""
        if usd <= 0:
            return
        with self.lock:
            self._total[funding] = self._total.get(funding, 0.0) + usd
            if day is not None:
                self._by_day[(funding, day)] = self._by_day.get((funding, day), 0.0) + usd
            if funding == "credit":
                self._by_feature[feature] = self._by_feature.get(feature, 0.0) + usd

    def add_row(self, row: ModelCall, feature: str | None = None) -> None:
        """Commit one ledger row (cached rows and zero-cost rows spend nothing)."""
        if row.cached or not row.cost_usd:
            return
        day = pt_day(row.created_at) if row.created_at is not None else None
        feature = feature or row.feature or feature_for(row.purpose)
        self.commit(row.cost_usd, feature, row.funding, day)

    # -- pending -------------------------------------------------------------------------

    def live(self, now: datetime | None) -> list[Reservation]:
        """Pending reservations, dropping those expired at ``now``."""
        with self.lock:
            if now is not None:
                gone = [r.id for r in self._pending.values() if r.expires and r.expires <= now]
                for rid in gone:
                    del self._pending[rid]
            return list(self._pending.values())

    def hold(
        self, usd: float, feature: str, funding: Funding, day: date, expires: datetime | None
    ) -> Reservation:
        with self.lock:
            res = Reservation(next(self._ids), usd, feature, funding, day, expires)
            self._pending[res.id] = res
            return res

    def drop(self, res: Reservation | None) -> None:
        if res is not None:
            with self.lock:
                self._pending.pop(res.id, None)

    # -- queries: ``now`` given -> reservations still live at ``now`` are included ------

    def total(self, funding: Funding, now: datetime | None = None) -> float:
        with self.lock:
            out = self._total.get(funding, 0.0)
            if now is not None:
                out += sum(r.usd for r in self.live(now) if r.funding == funding)
            return out

    def day_total(self, funding: Funding, day: date, now: datetime | None = None) -> float:
        with self.lock:
            out = self._by_day.get((funding, day), 0.0)
            if now is not None:
                out += sum(r.usd for r in self.live(now) if r.funding == funding and r.day == day)
            return out

    def feature_total(self, feature: str, now: datetime | None = None) -> float:
        with self.lock:
            out = self._by_feature.get(feature, 0.0)
            if now is not None:
                out += sum(
                    r.usd for r in self.live(now) if r.funding == "credit" and r.feature == feature
                )
            return out

    # -- spend the Meta client has ledgered that a caller reports again ------------------

    def offer_prerecorded(self, usd: float) -> None:
        """Spend already in the ledger that a caller will report again: the sandbox route
        records a live result's cost after the client has ledgered each of its calls."""
        if usd > 0:
            with self.lock:
                self._prerecorded += usd

    def claim_prerecorded(self, usd: float) -> float:
        """Consume up to ``usd`` of pre-recorded spend; return the part still unrecorded."""
        with self.lock:
            taken = min(max(0.0, usd), self._prerecorded)
            self._prerecorded -= taken
            return max(0.0, usd - taken)


class BudgetGuard:
    """Prices, admits and reserves live calls; reads spend from a shared book. Thread-safe.

    Two regimes (NFR-036, NFR-037):

    * **credit** (before ``VIGIL_CREDIT_WINDOW_END``, or when it is unset): the $140 credit
      cap, the spec 11.4 feature budgets and the $10 daily cap, over credit-tagged spend only.
    * **paid** (from the window end): refused unless ``VIGIL_ALLOW_PAID=1``; refused without a
      durable ledger; otherwise only the judging caps apply ($25 in total and $5 per PT
      calendar day of paid spend). Paid spend never counts toward the $140.

    Whatever the funding tag, no live call is admitted from ``VIGIL_JUDGING_END`` on (F4: with
    the window end unset every call is tagged credit, and the end date must still bind).

    Spend lives in a :class:`SpendBook`: ``book`` when given, else the ``ledger``'s book (so
    totals are derived from the durable ledger on start and shared with every guard over it),
    else a private in-memory one. ``spent`` seeds extra rows; each is counted under its own
    ``funding`` tag and ``feature`` (else one derived from the purpose). Days are Pacific
    calendar days.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        total_cap: float | None = None,
        daily_cap: float | None = None,
        feature_caps: dict[str, float] | None = None,
        judging_cap: float | None = None,
        judging_daily_cap: float | None = None,
        clock: Callable[[], datetime] | None = None,
        spent: Iterable[ModelCall] | None = None,
        ledger: Any = None,
        book: SpendBook | None = None,
    ):
        s = settings or get_settings()
        self.total_cap = s.total_cap_usd if total_cap is None else total_cap
        self.daily_cap = s.daily_cap_usd if daily_cap is None else daily_cap
        self.feature_caps = {**FEATURE_CAPS, **(feature_caps or {})}
        self.judging_cap = s.judging_cap_usd if judging_cap is None else judging_cap
        self.judging_daily_cap = (
            s.judging_daily_cap_usd if judging_daily_cap is None else judging_daily_cap
        )
        self.window_end = _utc(s.credit_window_end) if s.credit_window_end else None
        self.judging_end = _utc(getattr(s, "judging_end", None) or DEFAULT_JUDGING_END)
        self.allow_paid = s.allow_paid
        self._clock = clock or _now
        ledger_book = getattr(ledger, "book", None) if ledger is not None else None
        self.book: SpendBook = book or ledger_book or SpendBook()
        self._warned: set[tuple[str, int]] = set()
        self.warnings: list[str] = []
        for row in spent or ():
            if row.cost_usd and not row.cached:
                feature = row.feature or feature_for(row.purpose)
                self._commit(row.cost_usd, feature, row.created_at, row.funding)

    # -- state ---------------------------------------------------------------------------

    @property
    def durable(self) -> bool:
        """Spend is persisted (a restart keeps it); paid calls need this."""
        return self.book.durable

    def now(self) -> datetime:
        return _utc(self._clock())

    def _today(self) -> date:
        return pt_day(self._clock())

    def funding_at(self, when: datetime) -> Funding:
        """``paid`` from the credit window end on, else ``credit`` (ledger tag, spec 9.3)."""
        if self.window_end is not None and _utc(when) >= self.window_end:
            return "paid"
        return "credit"

    def funding_now(self) -> Funding:
        return self.funding_at(self._clock())

    @property
    def spent_total(self) -> float:
        """Credit-funded spend (the $140 cap counts only this, NFR-036)."""
        return self.book.total("credit")

    @property
    def spent_paid(self) -> float:
        """Post-window paid spend (the $25 judging cap, NFR-037)."""
        return self.book.total("paid")

    def spent_feature(self, feature: str) -> float:
        return self.book.feature_total(feature)

    def spent_credit_today(self) -> float:
        return self.book.day_total("credit", self._today())

    def spent_paid_today(self) -> float:
        return self.book.day_total("paid", self._today())

    def spent_today(self) -> float:
        """All spend today (credit and paid), for the health endpoint and telemetry panel."""
        return self.spent_credit_today() + self.spent_paid_today()

    def pending(self, funding: Funding | None = None) -> float:
        """Money held by admitted, unsettled calls (every cap check counts it)."""
        live = self.book.live(self.now())
        return sum(r.usd for r in live if funding is None or r.funding == funding)

    def judging_remaining(self) -> float:
        """Room left for paid calls now: the tighter of the $25 total and today's $5."""
        return max(
            0.0,
            min(
                self.judging_cap - self.spent_paid,
                self.judging_daily_cap - self.spent_paid_today(),
            ),
        )

    def _caps_for(
        self, feature: str, funding: Funding, *, pending: bool = True
    ) -> list[tuple[str, float, float]]:
        """(name, limit, spent) for every cap that applies to a call of this feature.

        ``pending`` counts money held by admitted calls (admission); warnings pass False.
        """
        now = self.now() if pending else None
        today = self._today()
        if funding == "paid":
            return [
                ("judging", self.judging_cap, self.book.total("paid", now)),
                ("judging_daily", self.judging_daily_cap, self.book.day_total("paid", today, now)),
            ]
        return [
            ("total", self.total_cap, self.book.total("credit", now)),
            (
                f"feature:{feature}",
                self.feature_caps.get(feature, self.feature_caps["other"]),
                self.book.feature_total(feature, now),
            ),
            ("daily", self.daily_cap, self.book.day_total("credit", today, now)),
        ]

    def remaining(self, feature: str) -> float:
        caps = self._caps_for(feature, self.funding_now())
        return max(0.0, min(limit - spent for _, limit, spent in caps))

    @property
    def paid_disabled(self) -> bool:
        return self.funding_now() == "paid" and not self.allow_paid

    @property
    def judging_over(self) -> bool:
        """VIGIL_JUDGING_END has passed: no live call of any funding (F4)."""
        return self.now() >= self.judging_end

    # -- admission -----------------------------------------------------------------------

    def _admit(self, usd: float, funding: Funding) -> None:
        """Refusals that do not depend on spend: judging end, the paid switch, durability."""
        if self.judging_over:
            raise JudgingEnded(self.judging_end, usd)
        if funding == "paid":
            if not self.allow_paid:
                assert self.window_end is not None
                raise PaidCallsDisabled(self.window_end, usd)
            if not self.book.durable:
                raise LedgerNotDurable(usd)

    def _check_locked(self, usd: float, feature: str, funding: Funding) -> None:
        self._admit(usd, funding)
        for name, limit, spent in self._caps_for(feature, funding):
            if spent + usd > limit + _EPS:
                raise BudgetExceeded(name, limit, spent, usd)

    def check(self, est: CostEstimate) -> None:
        """Raise if this live call would cross any cap that applies to it now.

        Pending reservations count as spent. Callers that send should :meth:`reserve`
        instead, so a concurrent call cannot pass the same check (F6).
        """
        with self.book.lock:
            self._check_locked(est.usd, est.feature, self.funding_now())

    def reserve(self, est: CostEstimate, ttl_s: float | None = None) -> Reservation:
        """Check and hold ``est.usd`` in one atomic step; settle or release it afterwards."""
        with self.book.lock:
            funding = self.funding_now()
            self._check_locked(est.usd, est.feature, funding)
            expires = self.now() + timedelta(seconds=ttl_s) if ttl_s else None
            return self.book.hold(est.usd, est.feature, funding, self._today(), expires)

    def extend(self, res: Reservation, usd: float) -> None:
        """Hold ``usd`` more on a reservation (a retry after a billed attempt), re-checking
        every cap first, so a retry never crosses one (F5). Raises without changing ``res``."""
        with self.book.lock:
            self._check_locked(usd, res.feature, res.funding)
            res.usd += usd

    def release(self, res: Reservation | None) -> None:
        """Stop holding a reservation (its spend, if any, is committed by its ledger row)."""
        self.book.drop(res)

    def settle(self, res: Reservation, usd: float, when: datetime | None = None) -> list[str]:
        """Commit the actual cost of a reserved call to the book and release the hold.

        Use this when no ledger row commits the spend (a guard without a ledger)."""
        with self.book.lock:
            self.book.drop(res)
            return self.record(usd, res.feature, when, res.funding)

    def check_batch(self, estimates: Iterable[CostEstimate]) -> None:
        """Pre-flight: would the whole batch fit under every cap?"""
        ests = list(estimates)
        if not ests:
            return
        with self.book.lock:
            total = sum(e.usd for e in ests)
            funding = self.funding_now()
            self._admit(total, funding)
            now = self.now()
            today = self._today()
            if funding == "paid":
                checks = [
                    ("judging", self.judging_cap, self.book.total("paid", now), total),
                    (
                        "judging_daily",
                        self.judging_daily_cap,
                        self.book.day_total("paid", today, now),
                        total,
                    ),
                ]
            else:
                per_feature: dict[str, float] = {}
                for e in ests:
                    per_feature[e.feature] = per_feature.get(e.feature, 0.0) + e.usd
                checks = [("total", self.total_cap, self.book.total("credit", now), total)]
                checks += [
                    (
                        f"feature:{f}",
                        self.feature_caps.get(f, self.feature_caps["other"]),
                        self.book.feature_total(f, now),
                        usd,
                    )
                    for f, usd in per_feature.items()
                ]
                checks.append(
                    ("daily", self.daily_cap, self.book.day_total("credit", today, now), total)
                )
            for name, limit, spent, usd in checks:
                if spent + usd > limit + _EPS:
                    raise BudgetExceeded(name, limit, spent, usd)

    # -- recording -----------------------------------------------------------------------

    def _commit(
        self, usd: float, feature: str, when: datetime | None, funding: Funding | None = None
    ) -> Funding:
        when = when or self._clock()
        funding = funding or self.funding_at(when)
        self.book.commit(usd, feature, funding, pt_day(when))
        return funding

    def warn(self, feature: str, funding: Funding) -> list[str]:
        """The 50/75/90% warnings newly crossed by committed spend (once each)."""
        new: list[str] = []
        with self.book.lock:
            for name, limit, spent in self._caps_for(feature, funding, pending=False):
                if limit <= 0:
                    continue
                pct = spent / limit * 100.0
                for level in WARN_AT:
                    if pct + _EPS >= level and (name, level) not in self._warned:
                        self._warned.add((name, level))
                        new.append(
                            f"Budget warning: {name} spend at {level}% "
                            f"(${spent:.2f} of ${limit:.2f})"
                        )
            self.warnings.extend(new)
        for w in new:
            log.warning(w)
        return new

    def record(
        self,
        usd: float,
        feature: str,
        when: datetime | None = None,
        funding: Funding | None = None,
    ) -> list[str]:
        """Add actual spend to the book; return the warnings newly crossed (once each).

        ``funding`` defaults to the tag for ``when`` (now when omitted). A guard over a call
        ledger does not need this for ledgered calls: adding the ledger row commits it.
        """
        with self.book.lock:
            funding = self._commit(usd, feature, when, funding)
            return self.warn(feature, funding)


# ---------------------------------------------------------------------------
# Batch pre-flight
# ---------------------------------------------------------------------------


class BatchEstimate(BaseModel):
    """What a batch command prints before it runs (spec 11.6 item 3)."""

    calls: int = 0
    usd: float = 0.0
    frames: int = 0
    images: int = 0
    in_tokens: int = 0
    out_tokens: int = 0
    audio_s: float = 0.0
    by_feature: dict[str, float] = Field(default_factory=dict)

    def lines(self) -> list[str]:
        out = [
            f"calls: {self.calls}",
            f"frames: {self.frames}  images: {self.images}",
            f"tokens: {self.in_tokens} in / {self.out_tokens} out",
            f"estimated cost: ${self.usd:.2f}",
        ]
        out += [f"  {f}: ${usd:.2f}" for f, usd in sorted(self.by_feature.items())]
        return out


def preflight(
    estimates: Iterable[CostEstimate],
    *,
    confirm: bool = False,
    guard: BudgetGuard | None = None,
    threshold: float = CONFIRM_THRESHOLD_USD,
) -> BatchEstimate:
    """Sum a batch; refuse it above the threshold without --confirm or over any cap."""
    ests = list(estimates)
    summary = BatchEstimate(calls=len(ests))
    for e in ests:
        summary.usd += e.usd
        summary.frames += e.frames
        summary.images += e.images
        summary.in_tokens += e.in_tokens
        summary.out_tokens += e.out_tokens
        summary.audio_s += e.audio_s
        summary.by_feature[e.feature] = summary.by_feature.get(e.feature, 0.0) + e.usd
    if guard is not None:
        guard.check_batch(ests)
    if summary.usd > threshold + _EPS and not confirm:
        raise ConfirmRequired(summary.usd, threshold)
    return summary
