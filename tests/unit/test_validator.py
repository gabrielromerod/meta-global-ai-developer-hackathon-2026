"""Adversarial citation validator: every planted failure is caught (FR-015, NFR-003)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from vigil.models import Event, Gap, StoryDraft, Visit, VisitLedger
from vigil.reasoning.validator import BANNED_WORDS, find_clock_times, validate

PST = timezone(timedelta(hours=-8))
START = datetime(2026, 11, 3, 0, 0, tzinfo=PST)
CAMERA_NAMES = {
    "front": "Front entrance",
    "side_left": "Left side",
    "side_right": "Right side",
    "backyard": "Backyard",
}


def _ev(eid: str, cam: str, typ: str, t0: float, target=None, visit_id="v3") -> Event:
    return Event(
        id=eid,
        visit_id=visit_id,
        camera_id=cam,
        track_id="t1",
        type=typ,
        t0=t0,
        t1=t0 + 1.0,
        target=target,
        clip_t0=t0 - 2,
        clip_t1=t0 + 3,
    )


def scenario_c_ledger(session_start: datetime | None = START) -> VisitLedger:
    """Scenario C on the session clock: t=0 is local midnight, 80040 s = 10:14:00 PM."""
    events = [
        _ev("e16", "side_left", "enter", 80020),
        _ev("e17", "side_left", "touch", 80040, "po_side_gate"),
        _ev("e18", "side_left", "exit", 80069, "to_shed_back"),
        _ev("e19", "side_left", "enter", 80111),
        _ev("e20", "side_left", "exit", 80149),
        _ev("e30", "front", "enter", 80400, visit_id="v4"),  # another visit's event
    ]
    gap = Gap(
        id="g4",
        visit_id="v3",
        kind="blind_spot",
        t0=80070,
        t1=80111,
        from_camera="side_left",
        to_camera="side_left",
        region_id="shed_back",
        resolved=True,
    )
    visit = Visit(
        id="v3",
        t0=80020,
        t1=80150,
        event_ids=["e16", "e17", "e18", "e19", "e20"],
        gap_ids=["g4"],
        track_ids=["t1", "t2"],
    )
    return VisitLedger(
        visit=visit,
        events=events,
        gaps=[gap],
        camera_names=CAMERA_NAMES,
        session_start=session_start,
    )


def good_draft() -> dict:
    return {
        "verdict_proposal": "noteworthy",
        "sentences": [
            {"text": "A person touched the side gate at 10:14 PM.", "event_ids": ["e17"]},
            {"text": "They walked out of view toward the shed.", "event_ids": ["e18"]},
            {
                "text": "They came back into view on the Left side camera at 10:15 PM.",
                "event_ids": ["e19"],
            },
            {"text": "They left the side yard at 22:15.", "event_ids": ["e20"]},
        ],
        "gap_after_sentence": [{"gap_id": "g4", "after": 1}],
        "watch_proposals": [],
    }


def with_sentence(text: str, ids: list[str], **extra) -> dict:
    d = good_draft()
    d["sentences"][1] = {"text": text, "event_ids": ids, **extra}
    return d


def checks(result) -> set[str]:
    return {f.check for f in result.failures}


def test_good_draft_passes() -> None:
    res = validate(StoryDraft.model_validate(good_draft()), scenario_c_ledger())
    assert res.passed, res.failures
    assert res.failures == []
    assert res.attempt == 1


def test_accepts_raw_json_string_and_records_attempt() -> None:
    res = validate(json.dumps(good_draft()), scenario_c_ledger(), attempt=2)
    assert res.passed
    assert res.attempt == 2


# --- check 1: schema and sentence count -------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        '{"sentences": ',
        {"sentences": "A person did a thing."},
        {"verdict_proposal": "noteworthy"},
        {"verdict_proposal": "needs_attention", "sentences": [{"text": "x", "event_ids": ["e17"]}]},
        {"sentences": [{"text": "   ", "event_ids": ["e17"]}]},
        None,
        42,
    ],
)
def test_malformed_output_fails_schema(raw) -> None:
    res = validate(raw, scenario_c_ledger())
    assert not res.passed
    assert "schema" in checks(res)


def test_empty_story_fails_sentence_count() -> None:
    res = validate({"sentences": []}, scenario_c_ledger())
    assert not res.passed
    assert checks(res) == {"sentence_count"}


def test_seven_sentences_fail_sentence_count() -> None:
    d = good_draft()
    d["sentences"] = [{"text": "A person touched the side gate.", "event_ids": ["e17"]}] * 7
    d["gap_after_sentence"] = []
    assert checks(validate(d, scenario_c_ledger())) == {"sentence_count"}


def test_model_cannot_write_code_gap_sentences() -> None:
    d = with_sentence("Nothing happened behind the shed.", ["e18"], source="code", gap_id="g4")
    res = validate(d, scenario_c_ledger())
    assert "schema" in checks(res)


def test_gap_placement_out_of_range() -> None:
    d = good_draft()
    d["gap_after_sentence"] = [{"gap_id": "g4", "after": 9}]
    assert "schema" in checks(validate(d, scenario_c_ledger()))


# --- check 2: citations -----------------------------------------------------


def test_missing_id_caught() -> None:
    res = validate(with_sentence("A person walked toward the shed.", []), scenario_c_ledger())
    assert checks(res) == {"uncited"}
    assert res.failures[0].sentence_index == 1


@pytest.mark.parametrize("foreign", ["e99", "e30"])
def test_foreign_id_caught(foreign: str) -> None:
    res = validate(with_sentence("A person walked away.", [foreign]), scenario_c_ledger())
    assert checks(res) == {"foreign_event"}


def test_watch_proposal_must_cite_this_visit() -> None:
    d = good_draft()
    d["watch_proposals"] = [{"camera_id": "front", "phrase": "package", "reason_event_id": "e30"}]
    assert checks(validate(d, scenario_c_ledger())) == {"foreign_event"}


# --- check 3: clock times ---------------------------------------------------


def test_time_far_from_cited_event_caught() -> None:
    res = validate(
        with_sentence("A person touched the side gate at 10:30 PM.", ["e17"]), scenario_c_ledger()
    )
    assert checks(res) == {"time_mismatch"}


@pytest.mark.parametrize(
    "text",
    [
        "At 10:14:50 PM they opened the shed door.",  # seconds precision, inside g4
        "At 10:15 PM they were behind the shed.",  # whole minute, nearest instant in g4
    ],
)
def test_time_inside_gap_caught(text: str) -> None:
    res = validate(with_sentence(text, ["e18"]), scenario_c_ledger())
    assert "time_in_gap" in checks(res)


def test_time_without_session_start_cannot_be_checked() -> None:
    res = validate(good_draft(), scenario_c_ledger(session_start=None))
    assert "time_mismatch" in checks(res)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("at 10:14 PM", [(22, 14, None)]),
        ("at 10:14pm", [(22, 14, None)]),
        ("at 10:14 p.m.", [(22, 14, None)]),
        ("at 22:14", [(22, 14, None)]),
        ("at 10 PM", [(22, None, None)]),
        ("at 12 AM and 12:30 PM", [(0, None, None), (12, 30, None)]),
        ("at 10:14:50 PM", [(22, 14, 50)]),
        ("for 41 s behind 2 sheds", []),
    ],
)
def test_clock_time_parser(text: str, expected) -> None:
    assert [(c.hour, c.minute, c.second) for c in find_clock_times(text)] == expected


def test_hour_only_time_matches_event_on_the_hour() -> None:
    ledger = scenario_c_ledger()
    ledger.events.append(_ev("e21", "side_left", "dwell", 79220))  # 10:00:20 PM
    ledger.visit.event_ids.append("e21")
    d = with_sentence("They waited by the gate at 10 PM.", ["e21"])
    assert validate(d, ledger).passed


# --- check 4: camera names --------------------------------------------------


def test_wrong_camera_caught() -> None:
    res = validate(
        with_sentence("A person was on the Front entrance camera.", ["e18"]), scenario_c_ledger()
    )
    assert checks(res) == {"camera_mismatch"}


def test_camera_id_in_text_also_checked() -> None:
    res = validate(with_sentence("A person was seen on side_right.", ["e18"]), scenario_c_ledger())
    assert checks(res) == {"camera_mismatch"}


# --- check 5: banned words --------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "He walked toward the shed.",
        "She walked toward the shed.",
        "A man walked toward the shed.",
        "A young woman walked toward the shed.",
        "An elderly person walked toward the shed.",
        "A teenager walked toward the shed.",
        "A suspicious person walked toward the shed.",
        "The intruder walked toward the shed.",
        "A thief walked toward the shed.",
        "A burglar walked toward the shed.",
        "A criminal walked toward the shed.",
        "A person walked toward the shed with his bag.",
        "The bag was hers.",
        "A Hispanic person walked toward the shed.",
        "A dark-skinned person walked toward the shed.",
    ],
)
def test_banned_words_caught(text: str) -> None:
    res = validate(with_sentence(text, ["e18"]), scenario_c_ledger())
    assert checks(res) == {"banned_word"}


@pytest.mark.parametrize(
    "text",
    [
        "A person in a white jacket and black trousers walked toward the shed.",
        "They walked here toward the shed with a package.",
        "They looked at the garage, then the shed.",
    ],
)
def test_colours_and_innocent_words_pass(text: str) -> None:
    assert validate(with_sentence(text, ["e18"]), scenario_c_ledger()).passed


def test_banned_list_covers_spec_terms() -> None:
    for w in ("suspicious", "intruder", "thief", "he", "she", "him", "her", "his", "hers"):
        assert w in BANNED_WORDS


# --- check 6: gap ids -------------------------------------------------------


def test_unknown_gap_id_caught() -> None:
    d = good_draft()
    d["gap_after_sentence"] = [{"gap_id": "g9", "after": 1}]
    assert checks(validate(d, scenario_c_ledger())) == {"unknown_gap"}


def test_every_failure_is_reported_not_just_the_first() -> None:
    d = good_draft()
    d["sentences"][0] = {"text": "He touched the gate at 10:40 PM.", "event_ids": ["e17"]}
    d["sentences"][1] = {"text": "Then they left.", "event_ids": []}
    d["gap_after_sentence"] = [{"gap_id": "g9", "after": 1}]
    assert checks(validate(d, scenario_c_ledger())) == {
        "banned_word",
        "time_mismatch",
        "uncited",
        "unknown_gap",
    }
