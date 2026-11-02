"""Golden pipeline (spec 12.1 "Integration: golden pipeline"; FR-004 to FR-016, FR-039).

Recorded-style answers for scenarios A, B and C (spec 4) go through the real modules:
SAM wire text -> vigil.meta.sam -> stitch -> events -> visits and gaps -> rules -> triage ->
story and validator -> verdict -> closed loop, plus locate for C. Offline and deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from tests.fixtures.scenarios.builders import (
    GAP_C,
    SCENARIOS,
    Scenario,
    load_label,
    make_window,
    run_golden,
)
from vigil.eval.metrics import compute_metrics
from vigil.models import Config, ProtectedObject, Rule, Watch
from vigil.pipeline import run_scenario
from vigil.reasoning.rules import load_rules
from vigil.reasoning.validator import validate

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


# ---------------------------------------------------------------------------
# Scenario A: routine
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
    assert v["floor"] == "normal"
    # the person and the car share one visit (same camera, overlapping in time)
    assert sorted(v["track_ids"]) == ["front-car-1", "front-person-1"]
    assert v["watches"] == {"accepted": [], "rejected": []}


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
            assert f"left the {e['target']} area" in s["text"], s["text"]
        else:
            assert "camera's view" in s["text"], s["text"]


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
# Scenario C: night, rule r7, blind spot, rejected draft
# ---------------------------------------------------------------------------


def test_golden_c_rule_gap_and_verdict(golden) -> None:
    _, result = golden("C")
    v = only_visit(result)
    assert v["verdict"] == "needs_attention"
    assert v["floor"] == "needs_attention"
    assert v["escalated"] is True
    assert v["triage"]["forced"] is True
    assert v["triage"]["source"] == "code"

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


def test_golden_c_touch_is_at_2214_pacific(golden) -> None:
    sc, result = golden("C")
    v = only_visit(result)
    touch = next(e for e in v["events"] if e["type"] == "touch")
    local = sc.session_start + timedelta(seconds=touch["t0"])
    assert (local.hour, local.minute) == (22, 14)


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


# ---------------------------------------------------------------------------
# All scenarios: citations, uncited sentences, claims inside gaps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sid", ["A", "B", "C"])
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


@pytest.mark.parametrize("sid", ["B", "C"])
def test_golden_shipped_wonder_story_revalidates(golden, sid: str) -> None:
    """The shipped model sentences, re-checked against the visit ledger, still pass."""
    from vigil.models import Event, Gap, StorySentence, Visit, VisitLedger

    sc, result = golden(sid)
    v = only_visit(result)
    ledger = VisitLedger(
        visit=Visit.model_validate({k: v[k] for k in Visit.model_fields}),
        events=[Event.model_validate(e) for e in v["events"]],
        gaps=[Gap.model_validate(g) for g in v["gaps"]],
        camera_names={"front": "Front entrance", "side_left": "Left side"},
        session_start=sc.session_start,
    )
    model_sentences = [StorySentence.model_validate(s) for s in v["story"] if s["source"] != "code"]
    res = validate({"sentences": [s.model_dump() for s in model_sentences]}, ledger)
    assert res.passed, res.failures


# ---------------------------------------------------------------------------
# EVAL metrics on the three results (FR-024, NFR-023)
# ---------------------------------------------------------------------------


def test_golden_eval_metrics(golden) -> None:
    labels = [load_label(s) for s in ("A", "B", "C")]
    results = [golden(s)[1] for s in ("A", "B", "C")]
    m = compute_metrics(labels, results)
    rows = {r["scenario"]: r for r in m["scenarios"]}
    assert {s: rows[s]["verdict"] for s in rows} == {
        "A": "normal",
        "B": "noteworthy",
        "C": "needs_attention",
    }
    assert all(r["correct"] for r in rows.values())
    t = m["totals"]
    assert t["scenarios"] == 3
    assert t["correct_verdicts"] == 3
    assert t["motion_triggers"] == 12  # 3 + 3 + 6 motion windows
    assert t["alerts"] == 1
    assert t["alert_reduction"] == round(1 - 1 / 12, 6)
    assert (t["links"], t["links_correct"], t["link_precision"]) == (1, 1, 1.0)
    assert t["visits"] == 3
    assert t["escalated"] == 2
    assert t["escalation_rate"] == round(2 / 3, 6)
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
