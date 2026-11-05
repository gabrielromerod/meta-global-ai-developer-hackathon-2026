"""Rules engine truth tables, including windows across midnight (FR-012, spec 9.4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vigil.models import APPLIES_TO_ROLES, ActiveWindow, Event, Rule, RuleTarget, Visit, Watch
from vigil.reasoning.rules import (
    DEFAULT_RULES_PATH,
    RuleOutcome,
    evaluate_rules,
    in_force,
    in_window,
    load_rules,
)

PST = timezone(timedelta(hours=-8))
START = datetime(2026, 11, 3, 0, 0, tzinfo=PST)  # session t=0 is local midnight
TZ = "America/Los_Angeles"


def at(hh: int, mm: int, ss: int = 0, day: int = 0) -> float:
    return day * 86400 + hh * 3600 + mm * 60 + ss


def ev(
    eid: str,
    typ: str,
    t0: float,
    target: str | None,
    dur: float = 1.0,
    cam="side_left",
    role: str | None = None,
):
    return Event(
        id=eid,
        visit_id="v1",
        camera_id=cam,
        track_id="t1",
        type=typ,
        t0=t0,
        t1=t0 + dur,
        target=target,
        clip_t0=t0,
        clip_t1=t0 + dur,
        actor_role=role,
    )


def visit(*events: Event) -> Visit:
    return Visit(
        id="v1",
        t0=min(e.t0 for e in events),
        t1=max(e.t1 for e in events),
        event_ids=[e.id for e in events],
    )


def run(rules: list[Rule], *events: Event, **kw):
    return evaluate_rules(visit(*events), list(events), rules, TZ, START, **kw)


# ---------------------------------------------------------------------------
# Active windows
# ---------------------------------------------------------------------------

NIGHT = ActiveWindow(start="22:00", end="06:00")
DAY = ActiveWindow(start="09:00", end="17:00")


@pytest.mark.parametrize(
    ("window", "hh", "mm", "expected"),
    [
        (NIGHT, 21, 59, False),
        (NIGHT, 22, 0, True),
        (NIGHT, 23, 59, True),
        (NIGHT, 0, 0, True),
        (NIGHT, 5, 59, True),
        (NIGHT, 6, 0, False),
        (NIGHT, 12, 0, False),
        (DAY, 8, 59, False),
        (DAY, 9, 0, True),
        (DAY, 16, 59, True),
        (DAY, 17, 0, False),
        (None, 3, 0, True),
        (ActiveWindow(start="00:00", end="00:00"), 13, 0, True),
    ],
)
def test_in_window_truth_table(window, hh: int, mm: int, expected: bool) -> None:
    assert in_window(window, datetime(2026, 11, 3, hh, mm, tzinfo=PST).timetz()) is expected


# ---------------------------------------------------------------------------
# Rule r7 (touch side gate 17:30-06:00, non_household, needs_attention; spec 9.4, Nov 2)
# ---------------------------------------------------------------------------


# Revised spec (Nov 2): r7 moved from 22:00-06:00 to 17:30-06:00 because scenario C is filmed
# at about 18:00. These events carry no actor_role, which counts as unknown: r7
# (non_household) fires on them (fail closed).
@pytest.mark.parametrize(
    ("t0", "fires", "floor"),
    [
        (at(22, 14), True, "needs_attention"),
        (at(18, 0), True, "needs_attention"),  # scenario C, filmed at about 18:00
        (at(17, 30), True, "needs_attention"),
        (at(21, 59, 59), True, "needs_attention"),  # was outside the old 22:00 window
        (at(17, 29, 59), False, "noteworthy"),  # protected touch, no rule -> noteworthy
        (at(12, 0), False, "noteworthy"),
        (at(0, 30, day=1), True, "needs_attention"),  # after midnight, next day
        (at(5, 59, 59, day=1), True, "needs_attention"),
        (at(6, 0, day=1), False, "noteworthy"),
        (at(3, 0), True, "needs_attention"),  # early morning of the session day
    ],
)
def test_r7_truth_table(rule_r7: Rule, t0: float, fires: bool, floor: str) -> None:
    res = run([rule_r7], ev("e17", "touch", t0, "po_side_gate"))
    assert bool(res.hits) is fires
    assert res.floor == floor
    if fires:
        assert res.hits[0].model_dump() == {"rule_id": "r7", "visit_id": "v1", "event_id": "e17"}


def test_rule_must_be_active(rule_r7: Rule) -> None:
    for state in ("draft", "disabled", "discarded"):
        r = rule_r7.model_copy(update={"state": state})
        res = run([r], ev("e17", "touch", at(22, 14), "po_side_gate"))
        assert res.hits == []
        assert res.floor == "noteworthy"


def test_wrong_target_or_trigger_does_not_fire(rule_r7: Rule) -> None:
    res = run([rule_r7], ev("e1", "touch", at(22, 14), "po_bin"))
    assert res.hits == []
    assert res.floor == "noteworthy"  # still a protected-object touch
    res = run([rule_r7], ev("e1", "cross", at(22, 14), "po_side_gate"))
    assert res.hits == []
    assert res.floor == "normal"


def test_events_outside_the_visit_are_ignored(rule_r7: Rule) -> None:
    inside = ev("e1", "enter", at(22, 10), None)
    other = ev("e2", "touch", at(22, 14), "po_side_gate").model_copy(update={"visit_id": "v9"})
    res = evaluate_rules(visit(inside), [inside, other], [rule_r7], TZ, START)
    assert res.hits == []
    assert res.floor == "normal"


def test_protected_ids_override_prefix_heuristic() -> None:
    res = run([], ev("e1", "touch", at(12, 0), "gate"), protected_ids={"gate"})
    assert res.floor == "noteworthy"
    res = run([], ev("e1", "touch", at(12, 0), "gate"))
    assert res.floor == "normal"


@pytest.mark.parametrize(("dur", "fires"), [(20.0, False), (29.9, False), (30.0, True)])
def test_min_dwell(dur: float, fires: bool) -> None:
    r = Rule(
        id="r3",
        name="Lingering on the porch",
        target=RuleTarget(kind="zone", id="porch"),
        trigger="dwell",
        min_dwell_s=30,
        severity="noteworthy",
    )
    res = run([r], ev("e1", "dwell", at(14, 0), "porch", dur=dur, cam="front"))
    assert bool(res.hits) is fires
    assert res.floor == ("noteworthy" if fires else "normal")


def test_floor_is_max_severity_of_fired_rules(rule_r7: Rule) -> None:
    soft = Rule(
        id="r9",
        name="Side yard",
        target=RuleTarget(kind="zone", id="side_yard"),
        trigger="enter",
        severity="noteworthy",
    )
    res = run(
        [soft, rule_r7],
        ev("e1", "enter", at(22, 10), "side_yard"),
        ev("e2", "touch", at(22, 14), "po_side_gate"),
    )
    assert [h.rule_id for h in res.hits] == ["r9", "r7"]
    assert res.floor == "needs_attention"


def test_no_events_no_rules_is_normal() -> None:
    v = Visit(id="v1", t0=0, t1=1)
    assert evaluate_rules(v, [], [], TZ, START).floor == "normal"


def test_window_without_session_start_raises(rule_r7: Rule) -> None:
    e = ev("e17", "touch", at(22, 14), "po_side_gate")
    with pytest.raises(ValueError, match="session_start"):
        evaluate_rules(visit(e), [e], [rule_r7], TZ, None)


# ---------------------------------------------------------------------------
# Default rules (config/rules.default.json)
# ---------------------------------------------------------------------------


def test_default_rules_load() -> None:
    rules = load_rules(DEFAULT_RULES_PATH)
    assert [r.trigger for r in rules] == ["removed", "enter", "carry"]
    # revised spec (FR-012, Nov 2): every default rule applies to non-household subjects
    assert all(r.state == "active" and r.applies_to == "non_household" for r in rules)
    assert [r.name for r in rules] == [
        "Watched package removed",
        "Non-household person in the backyard 11 PM to 5 AM",
        "Possible knife or gun carried by a non-household person",  # Nov 4
    ]


@pytest.mark.parametrize(
    ("t0", "fires"),
    [
        (at(22, 59), False),
        (at(23, 0), True),
        (at(2, 0, day=1), True),
        (at(4, 59, 59, day=1), True),
        (at(5, 0, day=1), False),
        (at(13, 0), False),
    ],
)
def test_default_backyard_night_rule(t0: float, fires: bool) -> None:
    rules = load_rules(DEFAULT_RULES_PATH)
    res = run(rules, ev("e1", "enter", t0, "backyard", cam="backyard"))
    assert bool(res.hits) is fires
    assert res.floor == ("needs_attention" if fires else "normal")


@pytest.mark.parametrize("hh", [3, 12, 22])
def test_default_package_removed_rule_any_time(hh: int) -> None:
    rules = load_rules(DEFAULT_RULES_PATH)
    watch = Watch(id="w2", camera_id="front", phrase="package", origin="wonder", status="watching")
    res = run(rules, ev("e41", "removed", at(hh, 0), "w2", cam="front"), watches=[watch])
    assert [h.rule_id for h in res.hits] == ["r_package_removed"]
    assert res.floor == "needs_attention"


def test_removed_non_package_watch_does_not_fire_package_rule() -> None:
    rules = load_rules(DEFAULT_RULES_PATH)
    watch = Watch(id="w3", camera_id="front", phrase="bicycle", origin="owner", status="watching")
    res = run(rules, ev("e41", "removed", at(12, 0), "w3", cam="front"), watches=[watch])
    assert res.hits == []


@pytest.mark.parametrize("role", ["household_insider", "expected_visitor", "external_visitor"])
def test_default_rules_by_role(role: str) -> None:
    rules = load_rules(DEFAULT_RULES_PATH)
    res = run(rules, ev("e1", "enter", at(23, 30), "backyard", cam="backyard", role=role))
    assert bool(res.hits) is (role != "household_insider")
    watch = Watch(id="w2", camera_id="front", phrase="package", origin="wonder", status="watching")
    res = run(rules, ev("e41", "removed", at(12, 0), "w2", cam="front", role=role), watches=[watch])
    assert bool(res.hits) is (role != "household_insider")


# ---------------------------------------------------------------------------
# applies_to x actor_role (spec 9.4 table; unknown always fails closed)
# ---------------------------------------------------------------------------

# Written out by hand from the spec 9.4 table, not computed from APPLIES_TO_ROLES.
APPLIES: dict[tuple[str, str | None], bool] = {
    ("anyone", "household_insider"): True,
    ("anyone", "expected_visitor"): True,
    ("anyone", "external_visitor"): True,
    ("anyone", "unknown"): True,
    ("anyone", None): True,
    ("non_household", "household_insider"): False,
    ("non_household", "expected_visitor"): True,
    ("non_household", "external_visitor"): True,
    ("non_household", "unknown"): True,
    ("non_household", None): True,  # no role assigned yet counts as unknown
    ("external_visitor_only", "household_insider"): False,
    ("external_visitor_only", "expected_visitor"): False,
    ("external_visitor_only", "external_visitor"): True,
    ("external_visitor_only", "unknown"): True,
    ("external_visitor_only", None): True,
}


@pytest.mark.parametrize(("applies_to", "role"), list(APPLIES))
def test_applies_to_by_actor_role(rule_r7: Rule, applies_to: str, role: str | None) -> None:
    rule = rule_r7.model_copy(update={"applies_to": applies_to})
    res = run([rule], ev("e17", "touch", at(18, 0), "po_side_gate", role=role))
    assert bool(res.hits) is APPLIES[(applies_to, role)]


def test_contract_table_matches_spec() -> None:
    for (applies_to, role), fires in APPLIES.items():
        if role is not None:
            assert (role in APPLIES_TO_ROLES[applies_to]) is fires


# ---------------------------------------------------------------------------
# Protected-object floor (spec 9.4 cases 1 to 3) and "in force"
# ---------------------------------------------------------------------------


def test_scenario_a_prime_vs_c_same_touch_opposite_outcomes(rule_r7: Rule) -> None:
    """Section 4: the same gate touch after dark, decided only by where the person came from."""
    hh = ev("e5", "touch", at(18, 5), "po_side_gate", role="household_insider")
    household = run([rule_r7], hh)
    assert household.hits == []
    assert household.floor == "normal"  # case 2: the owner scoped the rule
    assert isinstance(household, RuleOutcome)
    assert household.scoped_out == ["e5"]
    ext = ev("e17", "touch", at(18, 5), "po_side_gate", role="external_visitor")
    external = run([rule_r7], ext)
    assert [h.rule_id for h in external.hits] == ["r7"]
    assert external.floor == "needs_attention"  # case 1
    assert external.scoped_out == []


@pytest.mark.parametrize(
    ("role", "applies_to", "t0", "state", "floor"),
    [
        ("household_insider", "non_household", at(18, 5), "active", "normal"),  # case 2
        ("household_insider", "non_household", at(12, 0), "active", "noteworthy"),  # not in force
        ("household_insider", "non_household", at(18, 5), "disabled", "noteworthy"),
        ("household_insider", "external_visitor_only", at(18, 5), "active", "normal"),  # case 2
        ("expected_visitor", "external_visitor_only", at(18, 5), "active", "noteworthy"),  # 3
        ("external_visitor", "external_visitor_only", at(18, 5), "active", "needs_attention"),
        ("unknown", "external_visitor_only", at(18, 5), "active", "needs_attention"),
        ("external_visitor", "non_household", at(12, 0), "active", "noteworthy"),  # no rule
    ],
)
def test_touch_floor_cases(
    rule_r7: Rule, role: str, applies_to: str, t0: float, state: str, floor: str
) -> None:
    rule = rule_r7.model_copy(update={"applies_to": applies_to, "state": state})
    res = run([rule], ev("e1", "touch", t0, "po_side_gate", role=role))
    assert res.floor == floor
    assert res.scoped_out == (["e1"] if floor == "normal" else [])


def test_case_2_needs_every_in_force_rule_to_exclude(rule_r7: Rule) -> None:
    anyone = rule_r7.model_copy(
        update={"id": "r8", "applies_to": "anyone", "severity": "noteworthy"}
    )
    e = ev("e1", "touch", at(18, 5), "po_side_gate", role="household_insider")
    res = run([rule_r7, anyone], e)
    assert [h.rule_id for h in res.hits] == ["r8"]
    assert res.floor == "noteworthy"
    assert res.scoped_out == []


def test_removed_by_expected_visitor_is_noteworthy() -> None:
    """UC-08 alternative: an external_visitor_only package rule and an expected visitor."""
    rule = Rule(
        id="r_pkg",
        name="Watched package removed",
        target=RuleTarget(kind="watch", id="package"),
        trigger="removed",
        severity="needs_attention",
        applies_to="external_visitor_only",
    )
    watch = Watch(id="w2", camera_id="front", phrase="package", origin="wonder", status="watching")
    e = ev("e41", "removed", at(14, 0), "w2", cam="front", role="expected_visitor")
    res = run([rule], e, watches=[watch])
    assert res.hits == []
    assert res.floor == "noteworthy"
    e = e.model_copy(update={"actor_role": "household_insider"})
    res = run([rule], e, watches=[watch])
    assert res.floor == "normal"  # case 2 also covers removed
    assert res.scoped_out == ["e41"]


def test_visit_floor_is_the_max_over_events(rule_r7: Rule) -> None:
    res = run(
        [rule_r7],
        ev("e1", "touch", at(18, 0), "po_side_gate", role="household_insider"),
        ev("e2", "touch", at(18, 1), "po_side_gate", role="unknown"),
    )
    assert [h.event_id for h in res.hits] == ["e2"]
    assert res.floor == "needs_attention"
    res = run(
        [rule_r7],
        ev("e1", "touch", at(18, 0), "po_side_gate", role="household_insider"),
        ev("e2", "touch", at(18, 1), "po_bin", role="household_insider"),  # no rule on the bin
    )
    assert res.floor == "noteworthy"
    assert res.scoped_out == ["e1"]


def test_in_force_ignores_applies_to(rule_r7: Rule) -> None:
    e = ev("e1", "touch", at(18, 0), "po_side_gate", role="household_insider")
    assert in_force(rule_r7, e, TZ, START)
    assert not in_force(rule_r7, e.model_copy(update={"t0": at(12, 0)}), TZ, START)
    assert not in_force(rule_r7.model_copy(update={"state": "draft"}), e, TZ, START)
    assert not in_force(rule_r7, e.model_copy(update={"target": "po_bin"}), TZ, START)
    assert not in_force(rule_r7, e.model_copy(update={"type": "cross"}), TZ, START)
