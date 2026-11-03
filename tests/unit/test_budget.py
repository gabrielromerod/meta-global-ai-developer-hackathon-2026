"""Budget guard (FR-043, NFR-036, NFR-037, spec 11.3 to 11.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from vigil.meta.budget import (
    ALLOWED_MODELS,
    CONFIRM_THRESHOLD_USD,
    FEATURE_CAPS,
    BudgetExceeded,
    BudgetGuard,
    ConfirmRequired,
    PaidCallsDisabled,
    estimate,
    feature_for,
    preflight,
)
from vigil.models import CostEstimate, ModelCall
from vigil.settings import Settings

NOW = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _guard(**kw) -> BudgetGuard:
    settings = kw.pop("settings", None) or _settings()
    return BudgetGuard(settings, clock=lambda: NOW, **kw)


def _est(usd: float, feature: str = "story", model: str = "muse-wonder-1.0") -> CostEstimate:
    return CostEstimate(model=model, feature=feature, usd=usd)


# --- prices (spec 11.3) ------------------------------------------------------------------


def test_allowlist_is_exactly_the_four_standard_models():
    assert set(ALLOWED_MODELS) == {
        "sam-3.1",
        "muse-spark-1.3",
        "muse-wonder-1.0",
        "muse-voice-transcribe-1.0",
    }


def test_sam_video_price_and_50_frame_minimum():
    assert estimate("sam-3.1", "perception_demo", frames=100).usd == pytest.approx(0.02)
    # A 10-frame request is billed as 50 frames.
    small = estimate("sam-3.1", "perception_demo", frames=10)
    assert small.frames == 50
    assert small.usd == pytest.approx(50 * 0.20 / 1000)
    assert estimate("sam-3.1", "perception_demo", frames=50).usd == pytest.approx(0.01)


def test_sam_image_price():
    assert estimate("sam-3.1", "rule_compile", images=1).usd == pytest.approx(0.0025)


def test_token_prices():
    spark = estimate("muse-spark-1.3", "appearance", in_tokens=1_000_000, out_tokens=1_000_000)
    assert spark.usd == pytest.approx(1.25 + 4.25)
    wonder = estimate("muse-wonder-1.0", "story", in_tokens=6000, out_tokens=800)
    assert wonder.usd == pytest.approx(6000 * 4 / 1e6 + 800 * 20 / 1e6)


def test_voice_price_whole_seconds_rounded_down():
    est = estimate("muse-voice-transcribe-1.0", "voice", audio_s=3600.9)
    assert est.audio_s == 3600
    assert est.usd == pytest.approx(0.18)


def test_estimate_refuses_unknown_and_contributor_models():
    with pytest.raises(ValueError, match="allowlist"):
        estimate("muse-spark-1.3-contributor", "appearance", in_tokens=10)
    with pytest.raises(ValueError, match="allowlist"):
        estimate("muse-image-1.0", "appearance", images=1)


def test_feature_caps_encode_spec_11_4():
    assert FEATURE_CAPS["perception_demo"] == 8.0  # 11.4 volume: 36,000 frames = $7.20
    assert FEATURE_CAPS["perception_all"] == 22.0
    assert FEATURE_CAPS["appearance"] == 16.0
    assert FEATURE_CAPS["story"] == 4.0
    assert FEATURE_CAPS["sandbox"] == 20.0
    assert feature_for("story") == "story"
    assert feature_for("appearance_notes") == "appearance"
    assert feature_for("rule_compile") == "rule_compile"
    assert feature_for("something_new") == "other"


# --- caps (test_spend_cap) ---------------------------------------------------------------


def test_spend_cap():
    """Refusal at each cap: total, feature and daily (spec section 3, FR-043)."""
    # Total cap: $140 by default; a call that would cross it is refused, naming the cap.
    g = _guard(feature_caps={"story": 1000.0}, daily_cap=1000.0)
    g.record(139.99, "story")
    with pytest.raises(BudgetExceeded) as exc:
        g.check(_est(0.02))
    assert exc.value.cap == "total"
    assert exc.value.fallback is True
    g.check(_est(0.01))  # reaching the cap exactly is allowed

    # Feature cap: story is $4.
    g = _guard(daily_cap=1000.0)
    g.record(3.99, "story")
    with pytest.raises(BudgetExceeded) as exc:
        g.check(_est(0.02))
    assert exc.value.cap == "feature:story"
    assert "story" in str(exc.value)
    g.check(_est(0.02, feature="appearance", model="muse-spark-1.3"))

    # Daily cap: $10 in the sandbox; yesterday's spend does not count today.
    g = _guard(feature_caps={"sandbox": 1000.0})
    g.record(9.5, "sandbox", when=NOW - timedelta(days=1))
    g.record(9.5, "sandbox")
    g.check(_est(0.5, feature="sandbox"))
    with pytest.raises(BudgetExceeded) as exc:
        g.check(_est(0.6, feature="sandbox"))
    assert exc.value.cap == "daily"


def test_spend_cap_counts_seeded_ledger_rows():
    rows = [
        ModelCall(id=f"c{i}", model="muse-wonder-1.0", purpose="story", req_hash="h", cost_usd=1.0)
        for i in range(4)
    ]
    g = _guard(spent=rows)
    assert g.spent_total == pytest.approx(4.0)
    with pytest.raises(BudgetExceeded):
        g.check(_est(0.01))


def test_warning_thresholds_once_each():
    g = _guard(total_cap=100.0, feature_caps={"story": 1000.0}, daily_cap=1000.0)
    assert g.record(49.0, "story") == []
    first = g.record(2.0, "story")
    assert any("50%" in w and "total" in w for w in first)
    assert g.record(1.0, "story") == []  # still between 50 and 75: no repeat
    jump = g.record(40.0, "story")  # 92%: crosses 75 and 90 together
    assert any("75%" in w for w in jump)
    assert any("90%" in w for w in jump)
    assert g.record(1.0, "story") == []
    assert len([w for w in g.warnings if "total" in w]) == 3


def test_window_end_switch():
    """NFR-037: after the credit window, paid calls are refused unless allow_paid."""
    end = NOW - timedelta(hours=1)
    g = _guard(settings=_settings(credit_window_end=end))
    with pytest.raises(PaidCallsDisabled) as exc:
        g.check(_est(0.01))
    assert exc.value.cap == "credit_window"
    assert isinstance(exc.value, BudgetExceeded)

    approved = _guard(settings=_settings(credit_window_end=end, allow_paid=True))
    approved.check(_est(0.01))

    before = _guard(settings=_settings(credit_window_end=NOW + timedelta(hours=1)))
    before.check(_est(0.01))


def test_window_end_naive_datetime_is_treated_as_utc():
    g = _guard(settings=_settings(credit_window_end=datetime(2026, 11, 2, 17, 0)))
    with pytest.raises(PaidCallsDisabled):
        g.check(_est(0.01))


def test_remaining_reports_tightest_cap():
    g = _guard()
    g.record(3.0, "story")
    assert g.remaining("story") == pytest.approx(1.0)


# --- pre-flight (spec 11.6 item 3) -------------------------------------------------------


def test_preflight_requires_confirm_above_threshold():
    assert CONFIRM_THRESHOLD_USD == 5.0
    small = [estimate("sam-3.1", "perception_demo", frames=100) for _ in range(10)]
    summary = preflight(small)
    assert summary.usd == pytest.approx(0.2)
    assert summary.frames == 1000
    assert summary.calls == 10
    big = [estimate("muse-spark-1.3", "appearance", in_tokens=1_000_000)] * 5
    with pytest.raises(ConfirmRequired, match="--confirm"):
        preflight(big)
    assert preflight(big, confirm=True).usd == pytest.approx(6.25)


def test_preflight_checks_caps_with_guard():
    g = _guard()
    batch = [estimate("muse-wonder-1.0", "story", in_tokens=1_000_000)] * 2  # $8 > $4 story cap
    with pytest.raises(BudgetExceeded) as exc:
        preflight(batch, confirm=True, guard=g)
    assert exc.value.cap == "feature:story"


# --- funding tags and the judging cap (FR-043, NFR-036, NFR-037) ---------------------------

PT = ZoneInfo("America/Los_Angeles")
WINDOW_END = datetime(2026, 11, 5, 5, 59, tzinfo=PT)
JUDGING_END = datetime(2026, 11, 10, 23, 59, tzinfo=PT)
JUDGING_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=PT)


def _judging_guard(now: datetime = JUDGING_NOW, **settings_kw) -> BudgetGuard:
    settings_kw.setdefault("credit_window_end", WINDOW_END)
    settings_kw.setdefault("allow_paid", True)
    settings_kw.setdefault("judging_end", JUDGING_END)
    return BudgetGuard(_settings(**settings_kw), clock=lambda: now)


def _row(cost: float, funding: str, when: datetime, i: int = 0) -> ModelCall:
    return ModelCall(
        id=f"r{funding}{i}",
        model="muse-spark-1.3",
        purpose="sandbox_compile",
        feature="sandbox",
        req_hash="h",
        cost_usd=cost,
        funding=funding,
        created_at=when,
    )


def test_funding_tag_is_credit_before_window_end_and_paid_after():
    g = _judging_guard()
    assert g.funding_at(WINDOW_END - timedelta(seconds=1)) == "credit"
    assert g.funding_at(WINDOW_END) == "paid"
    assert g.funding_now() == "paid"
    assert _guard().funding_now() == "credit"  # no window end configured: credits


def test_credit_cap_counts_credit_funded_spend_only():
    """NFR-036: paid (post-window) spend never counts toward the $140 credit cap."""
    rows = [_row(139.0, "credit", WINDOW_END - timedelta(days=1))]
    rows += [_row(1.0, "paid", JUDGING_NOW, i) for i in range(3)]
    g = BudgetGuard(
        _settings(credit_window_end=WINDOW_END),
        clock=lambda: NOW,
        spent=rows,
        feature_caps={"sandbox": 1000.0},
    )
    assert g.spent_total == pytest.approx(139.0)
    assert g.spent_paid == pytest.approx(3.0)
    g.check(_est(0.5, feature="sandbox"))  # 139.5 credit <= 140


def test_judging_cap_refuses_a_call_that_would_cross_25_total():
    days = [JUDGING_NOW - timedelta(days=d) for d in range(5)]  # Nov 2..6, all post-window ok
    rows = [_row(5.0, "paid", d, i) for i, d in enumerate(days[:4])]  # $20 over 4 PT days
    rows.append(_row(4.99, "paid", JUDGING_NOW - timedelta(hours=1), 9))  # today: $4.99
    g = BudgetGuard(
        _settings(credit_window_end=WINDOW_END, allow_paid=True, judging_end=JUDGING_END),
        clock=lambda: JUDGING_NOW + timedelta(days=1),  # a fresh PT day: daily cap has room
        spent=rows,
    )
    assert g.spent_paid == pytest.approx(24.99)
    g.check(_est(0.01, feature="sandbox"))  # reaching $25 exactly is allowed
    with pytest.raises(BudgetExceeded) as exc:
        g.check(_est(0.02, feature="sandbox"))
    assert exc.value.cap == "judging"
    assert "judging cap" in str(exc.value)
    assert "25.00" in str(exc.value)
    assert exc.value.fallback is True


def test_judging_daily_cap_uses_pacific_calendar_days():
    """$5 per PT calendar day; 23:30 PT and 00:30 PT the next day are different days."""
    late = datetime(2026, 11, 6, 23, 30, tzinfo=PT)  # 07:30 UTC on Nov 7
    g = _judging_guard(now=late)
    g.record(4.99, "sandbox")
    with pytest.raises(BudgetExceeded) as exc:
        g.check(_est(0.02, feature="sandbox"))
    assert exc.value.cap == "judging_daily"
    assert "judging daily cap" in str(exc.value)
    assert "5.00" in str(exc.value)
    # Same UTC day (Nov 7), but a new PT day: the daily cap has room again.
    next_day = _judging_guard(now=datetime(2026, 11, 7, 0, 30, tzinfo=PT))
    next_day.record(4.99, "sandbox", when=late)
    assert next_day.spent_paid_today() == pytest.approx(0.0)
    next_day.check(_est(0.02, feature="sandbox"))


def test_judging_end_refuses_paid_calls_even_with_allow_paid():
    at_end = _judging_guard(now=JUDGING_END)
    with pytest.raises(BudgetExceeded) as exc:
        at_end.check(_est(0.01, feature="sandbox"))
    assert exc.value.cap == "judging_end"
    assert "VIGIL_JUDGING_END" in str(exc.value)
    _judging_guard(now=JUDGING_END - timedelta(minutes=1)).check(_est(0.01, feature="sandbox"))


def test_judging_end_defaults_to_nov_10_2359_pt_when_unset():
    g = _judging_guard(now=datetime(2026, 11, 11, 0, 1, tzinfo=PT), judging_end=None)
    assert g.judging_end == JUDGING_END
    with pytest.raises(BudgetExceeded) as exc:
        g.check(_est(0.01, feature="sandbox"))
    assert exc.value.cap == "judging_end"


def test_window_end_without_allow_paid_refuses_and_names_the_flag():
    g = _judging_guard(allow_paid=False)
    with pytest.raises(PaidCallsDisabled) as exc:
        g.check(_est(0.01, feature="sandbox"))
    assert exc.value.cap == "credit_window"
    assert "VIGIL_ALLOW_PAID" in str(exc.value)


def test_post_window_spend_is_judged_by_the_judging_cap_not_credit_caps():
    """After the window, the judging caps apply instead of the credit, feature and daily caps."""
    rows = [_row(140.0, "credit", WINDOW_END - timedelta(days=1))]
    g = BudgetGuard(
        _settings(credit_window_end=WINDOW_END, allow_paid=True, judging_end=JUDGING_END),
        clock=lambda: JUDGING_NOW,
        spent=rows,
    )
    g.check(_est(4.5, feature="story"))  # story feature cap is $4, credit cap is spent
    assert g.remaining("story") == pytest.approx(5.0)
    assert g.judging_remaining() == pytest.approx(5.0)


def test_record_tags_spend_by_funding_and_warns_on_the_judging_cap():
    g = _judging_guard()
    warnings = g.record(13.0, "sandbox")
    assert g.spent_paid == pytest.approx(13.0)
    assert g.spent_total == pytest.approx(0.0)
    assert any("judging" in w and "50%" in w for w in warnings)
    assert g.spent_today() == pytest.approx(13.0)


def test_check_batch_applies_the_judging_caps():
    g = _judging_guard()
    with pytest.raises(BudgetExceeded) as exc:
        g.check_batch([_est(3.0, feature="sandbox"), _est(3.0, feature="sandbox")])
    assert exc.value.cap == "judging_daily"
    ended = _judging_guard(now=JUDGING_END + timedelta(minutes=1))
    with pytest.raises(BudgetExceeded) as exc:
        ended.check_batch([_est(0.01, feature="sandbox")])
    assert exc.value.cap == "judging_end"


def test_credit_daily_cap_uses_pacific_calendar_days():
    late = datetime(2026, 11, 2, 23, 30, tzinfo=PT)  # 07:30 UTC on Nov 3
    g = BudgetGuard(_settings(), clock=lambda: datetime(2026, 11, 3, 0, 30, tzinfo=PT),
                    feature_caps={"sandbox": 1000.0})  # fmt: skip
    g.record(9.99, "sandbox", when=late)
    g.check(_est(1.0, feature="sandbox"))  # new PT day although the same UTC day
