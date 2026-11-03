"""Budget guard: price first; credit, feature, daily and judging caps (FR-043).

Every live call is priced from the spec 11.3 table (confirmed against
https://dev.meta.ai/docs/pricing-rate-limits on 2026-11-02) before it is sent. Spend is
tagged ``credit`` or ``paid`` (paid = from ``VIGIL_CREDIT_WINDOW_END`` on, spec 9.3).

* Credit-funded calls are refused when they *would* cross the $140 credit cap (credit spend
  only, NFR-036), their feature budget (spec 11.4) or the daily cap.
* After the window, paid calls are refused unless the owner set ``VIGIL_ALLOW_PAID=1``,
  refused from ``VIGIL_JUDGING_END`` (Nov 10, 23:59 PT) on, and refused when they would
  cross the judging cap ($25 in total) or its daily cap ($5 per PT calendar day) (NFR-037).

Every refusal names the cap. Warnings fire once each at 50, 75 and 90% of every cap.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
    """VIGIL_JUDGING_END has passed: no paid call after it, whatever VIGIL_ALLOW_PAID says."""

    def __init__(self, judging_end: datetime, requested: float):
        super().__init__(
            "judging_end",
            0.0,
            0.0,
            requested,
            f"VIGIL_JUDGING_END ({judging_end.isoformat()}) has passed; no paid call after it "
            "(NFR-037); cached mode continues",
        )
        self.judging_end = judging_end


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


class BudgetGuard:
    """Prices and admits live calls; records actual spend by funding. Thread-safe.

    Two regimes (NFR-036, NFR-037):

    * **credit** (before ``VIGIL_CREDIT_WINDOW_END``, or when it is unset): the $140 credit
      cap, the spec 11.4 feature budgets and the $10 daily cap, over credit-tagged spend only.
    * **paid** (from the window end): refused unless ``VIGIL_ALLOW_PAID=1``; refused from
      ``VIGIL_JUDGING_END`` on; otherwise only the judging caps apply ($25 in total and $5 per
      PT calendar day of paid spend). Paid spend never counts toward the $140.

    Days are Pacific calendar days. ``spent`` seeds the guard from existing ledger rows; each
    row is counted under its own ``funding`` tag and ``feature`` (else one derived from the
    purpose).
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
        self.judging_end = _utc(s.judging_end or DEFAULT_JUDGING_END)
        self.allow_paid = s.allow_paid
        self._clock = clock or _now
        self._lock = threading.Lock()
        self._total = 0.0
        self._by_feature: dict[str, float] = {}
        self._by_day: dict[date, float] = {}
        self._paid_total = 0.0
        self._paid_by_day: dict[date, float] = {}
        self._warned: set[tuple[str, int]] = set()
        self.warnings: list[str] = []
        for row in spent or ():
            if row.cost_usd and not row.cached:
                feature = row.feature or feature_for(row.purpose)
                self._add(row.cost_usd, feature, row.created_at, row.funding)

    # -- state ---------------------------------------------------------------------------

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
        return self._total

    @property
    def spent_paid(self) -> float:
        """Post-window paid spend (the $25 judging cap, NFR-037)."""
        return self._paid_total

    def spent_feature(self, feature: str) -> float:
        return self._by_feature.get(feature, 0.0)

    def spent_credit_today(self) -> float:
        return self._by_day.get(self._today(), 0.0)

    def spent_paid_today(self) -> float:
        return self._paid_by_day.get(self._today(), 0.0)

    def spent_today(self) -> float:
        """All spend today (credit and paid), for the health endpoint and telemetry panel."""
        return self.spent_credit_today() + self.spent_paid_today()

    def judging_remaining(self) -> float:
        """Room left for paid calls now: the tighter of the $25 total and today's $5."""
        return max(
            0.0,
            min(
                self.judging_cap - self._paid_total,
                self.judging_daily_cap - self.spent_paid_today(),
            ),
        )

    def _caps_for(self, feature: str, funding: Funding) -> list[tuple[str, float, float]]:
        """(name, limit, spent) for every cap that applies to a call of this feature."""
        if funding == "paid":
            return [
                ("judging", self.judging_cap, self._paid_total),
                ("judging_daily", self.judging_daily_cap, self.spent_paid_today()),
            ]
        return [
            ("total", self.total_cap, self._total),
            (
                f"feature:{feature}",
                self.feature_caps.get(feature, self.feature_caps["other"]),
                self.spent_feature(feature),
            ),
            ("daily", self.daily_cap, self.spent_credit_today()),
        ]

    def remaining(self, feature: str) -> float:
        caps = self._caps_for(feature, self.funding_now())
        return max(0.0, min(limit - spent for _, limit, spent in caps))

    @property
    def paid_disabled(self) -> bool:
        return self.funding_now() == "paid" and not self.allow_paid

    @property
    def judging_over(self) -> bool:
        return self.funding_now() == "paid" and _utc(self._clock()) >= self.judging_end

    # -- admission -----------------------------------------------------------------------

    def _admit_paid(self, usd: float) -> None:
        if self.paid_disabled:
            assert self.window_end is not None
            raise PaidCallsDisabled(self.window_end, usd)
        if self.judging_over:
            raise JudgingEnded(self.judging_end, usd)

    def check(self, est: CostEstimate) -> None:
        """Raise if this live call would cross any cap that applies to it now."""
        with self._lock:
            funding = self.funding_now()
            if funding == "paid":
                self._admit_paid(est.usd)
            for name, limit, spent in self._caps_for(est.feature, funding):
                if spent + est.usd > limit + _EPS:
                    raise BudgetExceeded(name, limit, spent, est.usd)

    def check_batch(self, estimates: Iterable[CostEstimate]) -> None:
        """Pre-flight: would the whole batch fit under every cap?"""
        ests = list(estimates)
        if not ests:
            return
        with self._lock:
            total = sum(e.usd for e in ests)
            if self.funding_now() == "paid":
                self._admit_paid(total)
                checks = [
                    ("judging", self.judging_cap, self._paid_total, total),
                    ("judging_daily", self.judging_daily_cap, self.spent_paid_today(), total),
                ]
            else:
                per_feature: dict[str, float] = {}
                for e in ests:
                    per_feature[e.feature] = per_feature.get(e.feature, 0.0) + e.usd
                checks = [("total", self.total_cap, self._total, total)]
                checks += [
                    (
                        f"feature:{f}",
                        self.feature_caps.get(f, self.feature_caps["other"]),
                        self.spent_feature(f),
                        usd,
                    )
                    for f, usd in per_feature.items()
                ]
                checks.append(("daily", self.daily_cap, self.spent_credit_today(), total))
            for name, limit, spent, usd in checks:
                if spent + usd > limit + _EPS:
                    raise BudgetExceeded(name, limit, spent, usd)

    # -- recording -----------------------------------------------------------------------

    def _add(
        self, usd: float, feature: str, when: datetime | None, funding: Funding | None = None
    ) -> Funding:
        when = when or self._clock()
        funding = funding or self.funding_at(when)
        day = pt_day(when)
        if funding == "paid":
            self._paid_total += usd
            self._paid_by_day[day] = self._paid_by_day.get(day, 0.0) + usd
        else:
            self._total += usd
            self._by_feature[feature] = self._by_feature.get(feature, 0.0) + usd
            self._by_day[day] = self._by_day.get(day, 0.0) + usd
        return funding

    def record(
        self,
        usd: float,
        feature: str,
        when: datetime | None = None,
        funding: Funding | None = None,
    ) -> list[str]:
        """Add actual spend; return the warnings newly crossed by this call (once each).

        ``funding`` defaults to the tag for ``when`` (now when omitted).
        """
        new: list[str] = []
        with self._lock:
            funding = self._add(usd, feature, when, funding)
            for name, limit, spent in self._caps_for(feature, funding):
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
