"""Golden pipeline (spec 12.1 "Integration: golden pipeline"; FR-004 to FR-016, FR-039, FR-044).

Recorded-style answers for the recorded evening (spec 4: A, A′, B, B′ and C) go through the
real modules: SAM wire text -> vigil.meta.sam -> stitch -> events and FR-008 origins ->
visits, gaps and FR-044 roles (with the owner's Expected Window for B′) -> rules with
``applies_to`` -> triage -> story and validator (check 7 against the visit's subjects) ->
verdict -> closed loop, plus locate for C. Offline and deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from tests.fixtures.scenarios.builders import (
    DELIVERY_WINDOW,
    GAP_C,
    SCENARIOS,
    Scenario,
    load_label,
    make_window,
    run_golden,
    scenario_b_prime,
)
from vigil.eval.metrics import compute_metrics
from vigil.models import (
    Appearance,
    Config,
    Event,
    Gap,
    ProtectedObject,
    Rule,
    StorySentence,
    Subject,
    Visit,
    VisitLedger,
    Watch,
)
from vigil.pipeline import run_scenario
from vigil.reasoning.rules import in_window, load_rules
from vigil.reasoning.validator import validate
from vigil.reasoning.visits import attribute_match

ALL = ["A", "A-prime", "B", "B-prime", "C"]
_RUNS: dict[tuple[str, bool], tuple[Scenario, dict[str, Any]]] = {}


@pytest.fixture
def golden(sample_config: Config, po_side_gate: ProtectedObject, rule_r7: Rule):
    """Run each scenario once per session (inputs are fixed) and hand out (scenario, result)."""

    def get(sid: str, spatial: bool = True) -> tuple[Scenario, dict[str, Any]]:
        key = (sid, spatial)
        if key not in _RUNS:
            sc = SCENARIOS[sid]()
            rules = [*load_rules(), rule_r7]
            _RUNS[key] = (sc, run_golden(sc, sample_config, rules, [po_side_gate], spatial=spatial))
        return _RUNS[key]

    return get


def only_visit(result: dict[str, Any]) -> dict[str, Any]:
    assert len(result["visits"]) == 1, [v["id"] for v in result["visits"]]
    return result["visits"][0]


def subject_of(v: dict[str, Any], track_id: str) -> dict[str, Any]:
    (s,) = [s for s in v["subjects"] if track_id in s["track_ids"]]
    return s


def local(sc: Scenario, t: float, tz: str = "America/Los_Angeles") -> datetime:
    from zoneinfo import ZoneInfo

    return (sc.session_start + timedelta(seconds=t)).astimezone(ZoneInfo(tz))


# ---------------------------------------------------------------------------
# Scenario A: routine, out of the front door
# ---------------------------------------------------------------------------


def test_golden_a_routine_is_normal_templated_not_escalated(golden) -> None:
    sc, result = golden("A")
    v = only_visit(result)
    assert v["verdict"] == "normal"
    assert v["escalated"] is False
    assert v["triage"] == {
        "escalate": False,
        "forced": False,
        "reason": "routine departure: a person and a car leave",
        "source": "spark",
    }
    assert v["story_source"] == "template"
    assert v["story"]
    assert all(s["source"] == "template" for s in v["story"])
    assert sc.writer is not None
    assert sc.writer.calls == 0
    assert v["gaps"] == []
    assert v["rule_hits"] == []
    assert v["rules_excluded"] == []
    assert v["floor"] == "normal"
    # the person and the car share one visit (same camera, overlapping in time)
    assert sorted(v["track_ids"]) == ["front-car-1", "front-person-1"]
    assert v["watches"] == {"accepted": [], "rejected": []}


def test_golden_a_person_out_of_the_front_door_is_household(golden) -> None:
    """FR-008 origin + FR-044 step 1: born in front_door_egress -> household_insider."""
    _, result = golden("A")
    v = only_visit(result)
    tracks = {t["id"]: t for t in result["tracks"]}
    assert tracks["front-person-1"]["origin_zone"] == "front_door_egress"
    person = subject_of(v, "front-person-1")
    assert person["actor_role"] == "household_insider"
    assert person["role_basis"] == "egress:front_door_egress"
    # the parked car was in view from the first frame: origin not observed -> unknown
    car = subject_of(v, "front-car-1")
    assert (car["actor_role"], car["role_basis"]) == ("unknown", "origin_null:front-car-1")
    for e in v["events"]:
        s = person if e["track_id"] == "front-person-1" else car
        assert (e["subject_id"], e["actor_role"]) == (s["id"], s["actor_role"])
    # the template introduces the household subject by its check-7 role phrase (egress basis)
    first_person = next(s for s in v["story"] if "vehicle" not in s["text"])
    assert first_person["text"].startswith("Someone who came out of the house ")


def test_golden_a_template_only_says_left_view_on_a_tracks_last_exit(golden) -> None:
    """Leaving a zone (porch) is not leaving the camera's view; only a track's last exit is."""
    _, result = golden("A")
    v = only_visit(result)
    events = {e["id"]: e for e in v["events"]}
    last_t = {}
    for e in v["events"]:
        last_t[e["track_id"]] = max(last_t.get(e["track_id"], e["t1"]), e["t1"])
    for s in v["story"]:
        (eid,) = s["event_ids"]
        e = events[eid]
        if e["type"] != "exit":
            continue
        if e["t1"] < last_t[e["track_id"]]:
            assert f"left the {e['target'].replace('_', ' ')} area" in s["text"], s["text"]
        else:
            assert "camera's view" in s["text"], s["text"]


# ---------------------------------------------------------------------------
# Scenario A′: same gate, after dark, household -> r7 excluded by applies_to
# ---------------------------------------------------------------------------


def test_golden_a_prime_household_touch_inside_r7_window_is_normal(golden, rule_r7) -> None:
    sc, result = golden("A-prime")
    v = only_visit(result)
    (touch,) = [e for e in v["events"] if e["type"] == "touch"]
    assert (touch["target"], touch["camera_id"]) == ("po_side_gate", "side_left")
    assert in_window(rule_r7.active, local(sc, touch["t0"]))  # 18:02, inside 17:30-06:00
    assert touch["actor_role"] == "household_insider"

    assert v["rule_hits"] == []
    assert v["floor"] == "normal"
    assert v["verdict"] == "normal"
    assert v["escalated"] is False
    assert v["triage"]["forced"] is False  # the case-2 touch does not force escalation
    assert v["summary"]["protected_touched"] is False
    assert v["story_source"] == "template"
    assert v["scoped_out"] == [touch["id"]]
    (excl,) = v["rules_excluded"]
    assert excl == {
        "rule_id": "r7",
        "event_id": touch["id"],
        "applies_to": "non_household",
        "actor_role": "household_insider",
        "subject_id": touch["subject_id"],
        "role_basis": "egress:front_door_egress",
    }


def test_golden_a_prime_role_carries_front_to_side_left_and_back(golden) -> None:
    """Unambiguous links on non-blind 2-20 s edges carry the egress role (FR-010, FR-044)."""
    _, result = golden("A-prime")
    v = only_visit(result)
    (s,) = v["subjects"]
    assert s["track_ids"] == ["front-person-1", "side_left-person-1", "front-person-2"]
    assert (s["actor_role"], s["role_basis"]) == (
        "household_insider",
        "egress:front_door_egress",
    )
    assert [(lk["from"]["camera_id"], lk["to"]["camera_id"]) for lk in v["links"]] == [
        ("front", "side_left"),
        ("side_left", "front"),
    ]
    assert all(not lk["blind"] and 2.0 <= lk["gap_s"] <= 20.0 for lk in v["links"])
    assert v["gaps"] == []
    assert {e["actor_role"] for e in v["events"]} == {"household_insider"}


def test_golden_a_prime_and_c_same_touch_opposite_outcomes(golden) -> None:
    """The Impact contrast (spec 4): same gate, after dark, decided only by where they came from."""
    _, a_prime = golden("A-prime")
    _, c = golden("C")
    va, vc = only_visit(a_prime), only_visit(c)
    assert (va["verdict"], vc["verdict"]) == ("normal", "needs_attention")
    assert {h["rule_id"] for h in vc["rule_hits"]} == {"r7"}
    assert [x["rule_id"] for x in va["rules_excluded"]] == ["r7"]
    assert {s["role_basis"] for s in va["subjects"]} == {"egress:front_door_egress"}
    assert {s["role_basis"] for s in vc["subjects"]} == {"perimeter:side_alley"}


# ---------------------------------------------------------------------------
# Scenario B: delivery and the closed loop
# ---------------------------------------------------------------------------


def test_golden_b_delivery_escalates_and_loop_accepts_package_watch(golden) -> None:
    sc, result = golden("B")
    v = only_visit(result)
    assert v["escalated"] is True
    assert v["triage"]["forced"] is False
    assert v["triage"]["source"] == "spark"
    assert v["story_source"] == "wonder"
    assert [x["passed"] for x in v["validations"]] == [True]
    assert v["proposal"] == "noteworthy"
    assert v["verdict"] == "noteworthy"
    accepted = v["watches"]["accepted"]
    assert len(accepted) == 1
    assert v["watches"]["rejected"] == []
    w = accepted[0]
    assert (w["camera_id"], w["phrase"], w["status"], w["origin"]) == (
        "front",
        "package",
        "watching",
        "wonder",
    )
    assert w["source_visit_id"] == v["id"]
    # expires 24 h after the visit ended (spec 5.10)
    expires = datetime.fromisoformat(w["expires_at"])
    assert expires - (sc.session_start + timedelta(seconds=v["t1"])) == timedelta(hours=24)
    assert result["watches"]["accepted"] == accepted


def test_golden_b_courier_from_driveway_entry_is_external(golden) -> None:
    _, result = golden("B")
    v = only_visit(result)
    (s,) = v["subjects"]
    assert (s["actor_role"], s["role_basis"]) == ("external_visitor", "perimeter:driveway_entry")
    assert result["tracks"][0]["origin_zone"] == "driveway_entry"
    # the shipped Wonder sentence states the role, backed by the ledger (check 7)
    assert v["story"][0]["text"].startswith("Someone who arrived from outside the property ")


def test_golden_b_accepted_watch_adds_package_prompt_to_next_windows(
    golden, sample_config: Config, po_side_gate: ProtectedObject, rule_r7: Rule
) -> None:
    """FR-020: the loop's watch adds its noun phrase to that camera's next SAM requests."""
    sc, result = golden("B")
    watches = [Watch.model_validate(w) for w in result["watches"]["accepted"]]
    asked: list[tuple[str, str]] = []

    def sam(window, phrase):
        asked.append((window.camera_id, phrase))
        return []

    later = [make_window("front", 30.0, 40.0), make_window("side_left", 30.0, 40.0)]
    run_scenario(
        {"scenario": "B-next", "windows": [w.model_dump() for w in later]},
        cfg=sample_config,
        rules=[*load_rules(), rule_r7],
        protected=[po_side_gate],
        watches=watches,
        session_start=sc.session_start,
        sam=sam,
    )
    assert sorted(asked) == [
        ("front", "car"),
        ("front", "package"),
        ("front", "person"),
        ("side_left", "car"),
        ("side_left", "person"),
    ]


# ---------------------------------------------------------------------------
# Scenario B′: inside the owner's delivery window (FR-029, FR-044 step 3)
# ---------------------------------------------------------------------------


def test_golden_b_prime_inside_delivery_window_is_expected_visitor(golden) -> None:
    sc, result = golden("B-prime")
    v = only_visit(result)
    (s,) = v["subjects"]
    assert (s["actor_role"], s["role_basis"]) == ("expected_visitor", "window:w3")
    assert {e["actor_role"] for e in v["events"]} == {"expected_visitor"}
    assert [w["id"] for w in result["expected_windows"]] == ["w3"]
    assert v["verdict"] == "normal"  # Wonder proposed normal; no rule, no protected object
    assert v["escalated"] is True
    assert v["story_source"] == "wonder"
    assert v["story"][0]["text"].startswith("An expected visitor ")
    arrived = local(sc, v["t0"])
    assert DELIVERY_WINDOW.start <= arrived < DELIVERY_WINDOW.end


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"end": datetime.fromisoformat("2026-11-02T16:20:04-08:00")}, "ended 1 s before"),
        ({"cameras": ["side_left"]}, "camera outside its scope"),
        ({"state": "cancelled"}, "cancelled"),
    ],
)
def test_golden_b_prime_outside_window_scope_is_external(
    change: dict[str, Any],
    why: str,
    sample_config: Config,
    po_side_gate: ProtectedObject,
    rule_r7: Rule,
) -> None:
    """FR-029 acceptance: 1 s after the window ends, or off its cameras -> external_visitor."""
    sc = scenario_b_prime(DELIVERY_WINDOW.model_copy(update=change))
    result = run_golden(sc, sample_config, [*load_rules(), rule_r7], [po_side_gate])
    (s,) = only_visit(result)["subjects"]
    assert (s["actor_role"], s["role_basis"]) == ("external_visitor", "perimeter:driveway_entry"), (
        why
    )


# ---------------------------------------------------------------------------
# Scenario C: after dark, side alley, rule r7, blind spot, rejected draft
# ---------------------------------------------------------------------------


def test_golden_c_rule_gap_and_verdict(golden) -> None:
    _, result = golden("C")
    v = only_visit(result)
    assert v["verdict"] == "needs_attention"
    assert v["floor"] == "needs_attention"
    assert v["escalated"] is True
    assert v["triage"]["forced"] is True
    assert v["triage"]["source"] == "code"
    assert v["rules_excluded"] == []
    assert v["scoped_out"] == []

    # r7 fires on the touch on the way in and again when they walk back past the gate
    hits = v["rule_hits"]
    assert {h["rule_id"] for h in hits} == {"r7"}
    assert len(hits) == 2
    by_id = {e["id"]: e for e in v["events"]}
    touches = sorted((by_id[h["event_id"]] for h in hits), key=lambda e: e["t0"])
    for touch in touches:
        assert (touch["type"], touch["target"], touch["camera_id"]) == (
            "touch",
            "po_side_gate",
            "side_left",
        )
        assert touch["actor_role"] == "external_visitor"
    assert touches[0]["t0"] < GAP_C[0] < GAP_C[1] < touches[1]["t0"]

    (gap,) = v["gaps"]
    assert gap["kind"] == "blind_spot"
    assert gap["region_id"] == "shed_back"
    assert gap["from_camera"] == "side_left"
    assert gap["to_camera"] == "side_left"
    assert gap["resolved"] is True
    assert abs((gap["t1"] - gap["t0"]) - 41.0) <= 1.0
    assert abs(gap["t0"] - GAP_C[0]) <= 1.0
    assert abs(gap["t1"] - GAP_C[1]) <= 1.0
    assert len(v["links"]) == 1
    assert v["links"][0]["region_id"] == "shed_back"


def test_golden_c_side_alley_role_carries_across_the_gap(golden) -> None:
    """FR-044: perimeter:side_alley, carried across the unambiguous 41 s re-link."""
    sc, result = golden("C")
    v = only_visit(result)
    tracks = {t["id"]: t for t in result["tracks"]}
    assert tracks["side_left-person-1"]["origin_zone"] == "side_alley"
    (s,) = v["subjects"]
    assert s["track_ids"] == ["side_left-person-1", "side_left-person-2"]
    assert (s["actor_role"], s["role_basis"]) == ("external_visitor", "perimeter:side_alley")
    (lk,) = v["links"]
    assert lk["blind"] is True
    # the re-link is unambiguous, and the fixture's notes agree on a known attribute
    a, b = (Appearance(tag=t, **{"class": "person"}, **sc.notes.person) for t in ("T1", "T2"))
    assert attribute_match(a, b)
    assert {e["subject_id"] for e in v["events"]} == {s["id"]}


def test_golden_c_touch_is_at_1814_pacific(golden) -> None:
    """Spec 4: C is filmed at about 18:00 PT (the earlier 22:14 label is retired)."""
    sc, result = golden("C")
    v = only_visit(result)
    touch = next(e for e in v["events"] if e["type"] == "touch")
    at = local(sc, touch["t0"])
    assert (at.hour, at.minute, at.second) == (18, 14, 5)


def test_golden_c_rejected_draft_then_valid_retry_with_code_gap_sentence(golden) -> None:
    sc, result = golden("C")
    v = only_visit(result)
    first, second = v["validations"]
    assert first["passed"] is False
    assert first["attempt"] == 1
    assert "uncited" in {f["check"] for f in first["failures"]}
    assert second["passed"] is True
    assert second["attempt"] == 2
    assert sc.writer is not None
    assert sc.writer.calls == 2
    retry_reasons = sc.writer.failures_seen[1] or []
    assert any(r.startswith("uncited") for r in retry_reasons)
    assert [d["passed"] for d in v["drafts"]] == [False, True]
    assert v["drafts"][0]["sentences"][1]["text"] == "They checked the shed door."

    assert v["story_source"] == "wonder"
    texts = [s["text"] for s in v["story"]]
    assert "They checked the shed door." not in texts
    assert texts[0].startswith("Someone who arrived from outside the property ")
    code = [s for s in v["story"] if s["source"] == "code"]
    assert len(code) == 1
    assert code[0]["text"] == "Vigil can't confirm what happened for 41 s behind the shed."
    assert code[0]["gap_id"] == v["gaps"][0]["id"]
    assert code[0]["event_ids"] == []
    # placed where the draft asked: after "They walked out of view ..." (sentence 2)
    assert v["story"][3] == code[0]


def test_golden_c_positions_never_inside_gap(golden) -> None:
    _, result = golden("C")
    v = only_visit(result)
    assert v["positions"], "a calibration and ground were given: C must have 3D positions"
    (gap,) = v["gaps"]
    assert all(not (gap["t0"] < p["t"] < gap["t1"]) for p in v["positions"])
    tracks = {p["track_id"] for p in v["positions"]}
    assert tracks == {"side_left-person-1", "side_left-person-2"}
    for p in v["positions"]:
        assert p["cameras"] == ["side_left"]
        assert p["method"] == "footpoint"
        assert abs(p["y"]) < 1e-6  # on the flat site-plan ground
        assert 0.0 < p["r95"] < 2.0
    # 2 Hz smoothing: estimates are on the half-second grid
    assert all(abs(p["t"] * 2 - round(p["t"] * 2)) < 1e-9 for p in v["positions"])


def test_golden_positions_only_with_calibration(golden) -> None:
    _, result = golden("C", spatial=False)
    assert result["positions"] == []
    assert only_visit(result)["verdict"] == "needs_attention"


def test_golden_c_sam_parser_in_path(golden) -> None:
    """The C tracks come from SAM wire text parsed by vigil.meta.sam (masks decoded)."""
    _, result = golden("C")
    tracks = {t["id"]: t for t in result["tracks"]}
    assert set(tracks) == {"side_left-person-1", "side_left-person-2"}
    t1 = tracks["side_left-person-1"]
    assert t1["phrase"] == "person"
    assert t1["masks"] == t1["n_frames"] > 0
    assert len(t1["window_ids"]) == 4  # one track stitched across four overlapping windows
    assert (t1["t_first"], t1["t_last"]) == (14.0, 40.0)
    # the re-acquired track's first frame follows an unobserved stretch: no origin (FR-008)
    assert tracks["side_left-person-2"]["origin_zone"] is None


# ---------------------------------------------------------------------------
# All scenarios: roles, citations, uncited sentences, claims inside gaps, check 7
# ---------------------------------------------------------------------------

ROLE_BASIS = {
    "A": {"front-person-1": "egress:front_door_egress"},
    "A-prime": {"front-person-1": "egress:front_door_egress"},
    "B": {"front-person-1": "perimeter:driveway_entry"},
    "B-prime": {"front-person-1": "window:w3"},
    "C": {"side_left-person-1": "perimeter:side_alley"},
}


@pytest.mark.parametrize("sid", ALL)
def test_golden_role_basis_and_every_event_has_a_role(golden, sid: str) -> None:
    _, result = golden(sid)
    (v,) = result["visits"]
    for tid, basis in ROLE_BASIS[sid].items():
        assert subject_of(v, tid)["role_basis"] == basis
    subjects = {s["id"]: s for s in result["subjects"]}
    assert subjects == {s["id"]: s for s in v["subjects"]}
    for e in result["events"]:
        assert e["subject_id"] in subjects, e
        assert e["actor_role"] == subjects[e["subject_id"]]["actor_role"]
        assert e["track_id"] in subjects[e["subject_id"]]["track_ids"]


@pytest.mark.parametrize("sid", ALL)
def test_golden_citations_resolve_and_nothing_uncited(golden, sid: str) -> None:
    _, result = golden(sid)
    for v in result["visits"]:
        events = {e["id"]: e for e in v["events"]}
        gaps = {g["id"]: g for g in v["gaps"]}
        assert set(events) == set(v["event_ids"])
        for s in v["story"]:
            if s["source"] == "code":
                assert s["gap_id"] in gaps
                assert not s["event_ids"]
                continue
            assert s["event_ids"], f"uncited sentence shipped: {s['text']!r}"
            assert set(s["event_ids"]) <= set(events)
            for eid in s["event_ids"]:  # no claim about what happened inside a gap
                e = events[eid]
                for g in gaps.values():
                    assert not (g["t0"] + 0.5 < e["t0"] < g["t1"] - 0.5)
                    assert not (g["t0"] + 0.5 < e["t1"] < g["t1"] - 0.5)


def _ledger(sc: Scenario, v: dict[str, Any], cfg: Config) -> VisitLedger:
    return VisitLedger(
        visit=Visit.model_validate({k: v[k] for k in Visit.model_fields}),
        events=[Event.model_validate(e) for e in v["events"]],
        gaps=[Gap.model_validate(g) for g in v["gaps"]],
        camera_names={c.id: c.name for c in cfg.cameras},
        subjects=[Subject.model_validate(s) for s in v["subjects"]],
        session_start=sc.session_start,
    )


@pytest.mark.parametrize("sid", ALL)
def test_golden_shipped_story_revalidates_with_check_7(
    golden, sid: str, sample_config: Config
) -> None:
    """The shipped sentences (Wonder or template), re-checked against the ledger with its
    subjects, pass every check including 7 (role claims backed by role_basis)."""
    sc, result = golden(sid)
    v = only_visit(result)
    ledger = _ledger(sc, v, sample_config)
    shipped = [StorySentence.model_validate(s) for s in v["story"] if s["source"] != "code"]
    assert shipped
    res = validate({"sentences": [s.model_dump() for s in shipped[:6]]}, ledger)
    assert res.passed, res.failures


def test_golden_role_phrase_on_the_wrong_subject_fails_check_7(golden, sample_config) -> None:
    """Check 7 is live in the pipeline's ledger: a household phrase on C's subject fails."""
    sc, result = golden("C")
    v = only_visit(result)
    ledger = _ledger(sc, v, sample_config)
    touch = next(e for e in v["events"] if e["type"] == "touch")
    text = "Someone who came out of the house was seen."
    bad = {"sentences": [{"text": text, "event_ids": [touch["id"]]}]}
    res = validate(bad, ledger)
    assert not res.passed
    assert res.failures


# ---------------------------------------------------------------------------
# EVAL metrics on the five results (FR-024, FR-044, NFR-023)
# ---------------------------------------------------------------------------


def test_golden_eval_metrics(golden) -> None:
    labels = [load_label(s) for s in ALL]
    results = [golden(s)[1] for s in ALL]
    m = compute_metrics(labels, results)
    rows = {r["scenario"]: r for r in m["scenarios"]}
    assert {s: rows[s]["verdict"] for s in rows} == {
        "A": "normal",
        "A-prime": "normal",
        "B": "noteworthy",
        "B-prime": "normal",
        "C": "needs_attention",
    }
    assert all(r["correct"] for r in rows.values())
    t = m["totals"]
    assert t["scenarios"] == 5
    assert t["correct_verdicts"] == 5
    assert t["motion_triggers"] == 20  # 3 + 5 + 3 + 3 + 6 motion windows
    assert t["alerts"] == 1
    assert t["alert_reduction"] == round(1 - 1 / 20, 6)
    assert (t["links"], t["links_correct"], t["link_precision"]) == (3, 3, 1.0)
    assert t["visits"] == 5
    assert t["escalated"] == 3
    assert t["escalation_rate"] == round(3 / 5, 6)
    assert t["claims_inside_gaps"] == 0
    assert t["uncited_sentences_shipped"] == 0
    assert t["positions_inside_gaps"] == 0
    assert (t["gaps_labelled"], t["gaps_matched"]) == (1, 1)
    assert (t["reolink_person_events"], t["reolink_matched_by_sam"]) == (2, 2)
    assert t["reolink_sam_agreement"] == 1.0
    assert m["met"]["claims_inside_gaps"] is True
    assert m["met"]["uncited_sentences_shipped"] is True
    assert m["met"]["link_precision"] is True
    assert m["met"]["alert_reduction"] is True
    assert m["unlabelled_results"] == []


def test_golden_eval_role_miss_rate(golden) -> None:
    """FR-044: assigned vs labelled role per subject, day and night, and the alerts caused."""
    labels = [load_label(s) for s in ALL]
    results = [golden(s)[1] for s in ALL]
    m = compute_metrics(labels, results)
    t = m["totals"]
    assert (t["roles_labelled"], t["roles_correct"], t["role_accuracy"]) == (5, 5, 1.0)
    assert (t["household_subjects"], t["household_missed"], t["role_miss_rate"]) == (2, 0, 0.0)
    assert (t["household_subjects_day"], t["role_miss_rate_day"]) == (1, 0.0)  # A
    assert (t["household_subjects_night"], t["role_miss_rate_night"]) == (1, 0.0)  # A′
    assert t["role_miss_alerts"] == 0
    rows = {r["scenario"]: r for r in m["scenarios"]}
    assert rows["C"]["roles"] == [
        {
            "subject": "S1",
            "labelled": "external_visitor",
            "assigned": "external_visitor",
            "assigned_roles": ["external_visitor"],
            "role_basis": "perimeter:side_alley",
            "correct": True,
            "alert": False,
        }
    ]
    assert rows["B-prime"]["roles"][0]["assigned"] == "expected_visitor"
