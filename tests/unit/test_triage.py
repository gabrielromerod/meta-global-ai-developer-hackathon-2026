"""Triage: code forces escalation; otherwise the injected model decides (FR-013)."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest

from vigil.models import Event, Gap, RuleHit, RuleResult, Track, TriageDecision, Visit, VisitSummary
from vigil.reasoning.rules import evaluate_rules
from vigil.reasoning.triage import decide, forced_escalation, summarize


def summary(**kw) -> VisitSummary:
    base = {
        "visit_id": "v1",
        "cameras": ["front"],
        "event_types": ["enter", "exit"],
        "rule_fired": False,
        "protected_touched": False,
        "unresolved_gap": False,
        "duration_s": 30.0,
    }
    return VisitSummary(**{**base, **kw})


class Model:
    def __init__(self, decision: TriageDecision | Exception) -> None:
        self.decision = decision
        self.calls = 0

    def __call__(self, s: VisitSummary) -> TriageDecision:
        self.calls += 1
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision


ROUTINE = TriageDecision(escalate=False, forced=False, reason="routine", source="spark")


@pytest.mark.parametrize(
    ("rule", "touched", "gap"),
    [c for c in itertools.product([False, True], repeat=3) if any(c)],
)
def test_forced_cases_always_escalate(rule: bool, touched: bool, gap: bool) -> None:
    s = summary(rule_fired=rule, protected_touched=touched, unresolved_gap=gap)
    forced = forced_escalation(s)
    assert forced is not None
    assert (forced.escalate, forced.forced, forced.source) == (True, True, "code")
    model = Model(ROUTINE)  # the model would say "routine"; code overrides it
    d = decide(s, model)
    assert d.escalate
    assert d.forced
    assert model.calls == 0


def test_unforced_case_asks_the_model() -> None:
    s = summary()
    assert forced_escalation(s) is None
    model = Model(ROUTINE)
    assert decide(s, model) == ROUTINE
    assert model.calls == 1
    yes = TriageDecision(escalate=True, forced=False, reason="new object", source="glimmer")
    assert decide(s, Model(yes)).escalate


def test_model_cannot_claim_forced() -> None:
    sneaky = TriageDecision(escalate=False, forced=True, reason="x", source="code")
    d = decide(summary(), Model(sneaky))
    assert d.forced is False
    assert d.source == "spark"


@pytest.mark.parametrize("new_object", [False, True])
def test_model_failure_falls_back_to_code_heuristic(new_object: bool) -> None:
    d = decide(summary(new_object=new_object), Model(RuntimeError("api down")))
    assert d.source == "code"
    assert d.forced is False
    assert d.escalate is new_object
    d = decide(summary(new_object=new_object), None)
    assert d.escalate is new_object


def test_summarize_from_visit() -> None:
    visit = Visit(id="v3", t0=100, t1=160, event_ids=["e1", "e2", "e3"], gap_ids=["g1"])
    events = [
        Event(id="e1", visit_id="v3", camera_id="side_left", track_id="t1", type="enter",
              t0=100, t1=101, clip_t0=100, clip_t1=101),
        Event(id="e2", visit_id="v3", camera_id="side_left", track_id="t1", type="touch",
              t0=110, t1=111, target="po_side_gate", clip_t0=110, clip_t1=111),
        Event(id="e3", visit_id="v3", camera_id="front", track_id="p1", type="enter",
              t0=150, t1=151, clip_t0=150, clip_t1=151),
    ]  # fmt: skip
    gaps = [Gap(id="g1", visit_id="v3", kind="blind_spot", t0=120, t1=300, resolved=False)]
    rr = RuleResult(hits=[RuleHit(rule_id="r7", visit_id="v3", event_id="e2")], floor="normal")
    tracks = [Track(id="p1", camera_id="front", cls="package", t_first=150, t_last=400)]
    s = summarize(visit, events, gaps, rr, tracks=tracks)
    assert s.cameras == ["front", "side_left"]
    assert s.event_types == ["enter", "touch", "enter"]
    assert s.rule_fired
    assert s.protected_touched
    assert s.unresolved_gap
    assert s.new_object
    assert s.duration_s == 60


# --- FR-013: only a 9.4 case-2 household touch is exempt from forced escalation ---------


def _touch(eid: str, t0: float, role: str | None, target: str = "po_side_gate") -> Event:
    return Event(
        id=eid,
        visit_id="v1",
        camera_id="side_left",
        track_id="t1",
        type="touch",
        t0=t0,
        t1=t0 + 1,
        target=target,
        clip_t0=t0,
        clip_t1=t0 + 1,
        actor_role=role,
    )


R7_START = datetime(2026, 11, 2, 0, 0, tzinfo=timezone(timedelta(hours=-8)))
EVENING = 18 * 3600.0  # 18:00, inside r7's 17:30-06:00 window
NOON = 12 * 3600.0  # outside it: r7 is not in force


@pytest.mark.parametrize(
    ("role", "t0", "forced"),
    [
        ("household_insider", EVENING, False),  # case 2: scoped out by the owner's rule
        ("household_insider", NOON, True),  # no rule in force: case 3 touch, forced
        ("expected_visitor", EVENING, True),  # r7 fires on non-household
        ("external_visitor", EVENING, True),
        ("unknown", EVENING, True),
        (None, EVENING, True),
    ],
)
def test_case_2_household_touch_is_the_only_exemption(rule_r7, role, t0, forced) -> None:
    e = _touch("e1", t0, role)
    visit = Visit(id="v1", t0=t0, t1=t0 + 1, event_ids=["e1"])
    rr = evaluate_rules(visit, [e], [rule_r7], "America/Los_Angeles", R7_START)
    s = summarize(visit, [e], [], rr)
    assert (forced_escalation(s) is not None) is forced
    model = Model(ROUTINE)
    d = decide(s, model)
    assert d.forced is forced
    assert model.calls == (0 if forced else 1)


def test_other_touch_in_the_same_visit_still_forces(rule_r7) -> None:
    hh = _touch("e1", EVENING, "household_insider")
    bin_touch = _touch("e2", EVENING + 5, "household_insider", target="po_bin")  # no rule
    visit = Visit(id="v1", t0=EVENING, t1=EVENING + 6, event_ids=["e1", "e2"])
    rr = evaluate_rules(visit, [hh, bin_touch], [rule_r7], "America/Los_Angeles", R7_START)
    assert summarize(visit, [hh, bin_touch], [], rr).protected_touched


def test_exempt_ids_can_be_passed_explicitly() -> None:
    e = _touch("e1", EVENING, "household_insider")
    visit = Visit(id="v1", t0=EVENING, t1=EVENING + 1, event_ids=["e1"])
    plain = RuleResult(floor="normal")
    assert summarize(visit, [e], [], plain).protected_touched
    assert not summarize(visit, [e], [], plain, exempt_event_ids={"e1"}).protected_touched


def test_plain_rule_result_scoped_out_is_the_case_2_exemption() -> None:
    """RuleResult (vigil.models) carries scoped_out itself, not only RuleOutcome."""
    e = _touch("e1", EVENING, "household_insider")
    visit = Visit(id="v1", t0=EVENING, t1=EVENING + 1, event_ids=["e1"])
    plain = RuleResult(floor="normal", scoped_out=["e1"])
    s = summarize(visit, [e], [], plain)
    assert not s.protected_touched
    assert forced_escalation(s) is None
