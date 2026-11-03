"""Adversarial citation validator: every planted failure is caught (FR-015, NFR-003)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from vigil.models import Box, Event, Gap, ProtectedObject, StoryDraft, Subject, Visit, VisitLedger
from vigil.reasoning.validator import (
    BANNED_WORDS,
    ROLE_BANNED_WORDS,
    ROLE_CHECK,
    ROLE_PHRASES,
    find_clock_times,
    validate,
)

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


# --- check 7: role claims, role words and names -------------------------------


def role_ledger(role: str = "external_visitor", basis: str = "perimeter:side_alley") -> VisitLedger:
    """Scenario C with one subject chain holding `role` (FR-044) on every visit event."""
    ledger = scenario_c_ledger()
    events = [
        e.model_copy(update={"subject_id": "s1", "actor_role": role}) if e.visit_id == "v3" else e
        for e in ledger.events
    ]
    subject = Subject(id="s1", visit_id="v3", track_ids=["t1"], actor_role=role, role_basis=basis)
    return ledger.model_copy(update={"events": events, "subjects": [subject]})


EXT_PHRASE = "Someone who arrived from outside the property touched the side gate at 10:14 PM."
HH_PHRASE = "Someone who came out of the house touched the side gate at 10:14 PM."
EXP_PHRASE = "An expected visitor touched the side gate at 10:14 PM."


def first(text: str, ids: list[str] | None = None) -> dict:
    d = good_draft()
    d["sentences"][0] = {"text": text, "event_ids": ids if ids is not None else ["e17"]}
    return d


@pytest.mark.parametrize(
    ("text", "role", "basis"),
    [
        (EXT_PHRASE, "external_visitor", "perimeter:side_alley"),
        (EXT_PHRASE.lower().capitalize(), "external_visitor", "group:external_visitor"),
        (HH_PHRASE, "household_insider", "egress:front_door_egress"),
        (EXP_PHRASE, "expected_visitor", "window:w3"),
        ("A person touched the side gate at 10:14 PM.", "unknown", "origin_null:t1"),
    ],
)
def test_backed_role_phrases_pass(text: str, role: str, basis: str) -> None:
    res = validate(first(text), role_ledger(role, basis))
    assert res.passed, res.failures


@pytest.mark.parametrize(
    ("text", "role", "basis"),
    [
        (EXT_PHRASE, "household_insider", "egress:front_door_egress"),
        (EXT_PHRASE, "unknown", "origin_null:t1"),
        (EXP_PHRASE, "external_visitor", "perimeter:side_alley"),
        (EXP_PHRASE, "unknown", "gap_unresolved:g4"),
        (HH_PHRASE, "external_visitor", "perimeter:side_alley"),
        (HH_PHRASE, "unknown", "ambiguous_link:t1"),
        # household by check-in or group gets no role phrase (spec 9.4 check 7)
        (HH_PHRASE, "household_insider", "checkin:c1"),
        (HH_PHRASE, "household_insider", "group:household_insider"),
    ],
)
def test_role_phrase_not_backed_by_the_ledger_is_caught(text: str, role: str, basis: str) -> None:
    res = validate(first(text), role_ledger(role, basis))
    assert checks(res) == {ROLE_CHECK}
    assert res.failures[0].sentence_index == 0


def test_role_phrase_must_cite_an_event() -> None:
    res = validate(first(EXT_PHRASE, []), role_ledger())
    assert {"uncited", ROLE_CHECK} <= checks(res)


def test_role_phrase_without_roles_in_the_ledger_fails_closed() -> None:
    res = validate(first(EXT_PHRASE), scenario_c_ledger())  # no subjects, no actor_role
    assert checks(res) == {ROLE_CHECK}


def test_role_phrase_over_subjects_with_different_roles_fails() -> None:
    ledger = role_ledger()
    events = [
        e.model_copy(update={"subject_id": "s2", "actor_role": "unknown"}) if e.id == "e19" else e
        for e in ledger.events
    ]
    s2 = Subject(
        id="s2",
        visit_id="v3",
        track_ids=["t2"],
        actor_role="unknown",
        role_basis="gap_unresolved:g4",
    )
    ledger = ledger.model_copy(update={"events": events, "subjects": [*ledger.subjects, s2]})
    text = "Someone who arrived from outside the property touched the gate and came back."
    assert checks(validate(first(text, ["e17", "e19"]), ledger)) == {ROLE_CHECK}
    assert validate(first(text, ["e17", "e18"]), ledger).passed


def test_subject_found_by_track_when_event_has_no_subject_id() -> None:
    ledger = role_ledger()
    events = [e.model_copy(update={"subject_id": None, "actor_role": None}) for e in ledger.events]
    ledger = ledger.model_copy(update={"events": events})
    assert validate(first(EXT_PHRASE), ledger).passed


def test_two_role_phrases_in_one_sentence_fail() -> None:
    text = (
        "Someone who arrived from outside the property and someone who came out of the house "
        "were at the side gate at 10:14 PM."
    )
    assert checks(validate(first(text), role_ledger())) == {ROLE_CHECK}


@pytest.mark.parametrize(
    "text",
    [
        "A family member walked toward the shed.",
        "The courier walked toward the shed.",
        "A delivery driver walked toward the shed.",
        "A neighbour walked toward the shed.",
        "A neighbor walked toward the shed.",
        "The homeowner walked toward the shed.",
        "The owner walked toward the shed.",
        "A guest walked toward the shed.",
        "A stranger walked toward the shed.",
        "A visitor walked toward the shed.",
        "An unexpected visitor walked toward the shed.",
        "A household member walked toward the shed.",
        "A resident walked toward the shed.",
        "Their dad walked toward the shed.",
        "Their son walked toward the shed.",
        "The wife walked toward the shed.",
        "The plumber walked toward the shed.",
    ],
)
def test_role_words_caught(text: str) -> None:
    res = validate(with_sentence(text, ["e18"]), role_ledger())
    assert checks(res) == {ROLE_CHECK}


def evening_ledger(role: str = "external_visitor", basis: str = "perimeter:side_alley"):
    """role_ledger shifted so that e17 (the side-gate touch) is at 6:14 PM."""
    return role_ledger(role, basis).model_copy(update={"session_start": START - timedelta(hours=4)})


def only(text: str, ids: tuple[str, ...] = ("e17",)) -> dict:
    """A one-sentence draft (no gap placement), for the 6:14 PM evening ledger."""
    return {"verdict_proposal": "noteworthy", "sentences": [{"text": text, "event_ids": [*ids]}]}


def test_evening_ledger_baseline_passes() -> None:
    assert validate(only("A person touched the side gate at 6:14 PM."), evening_ledger()).passed


def test_role_paraphrase_is_caught() -> None:
    # F8: the allowed phrase reworded slips past a phrase-only check
    text = "A person who came out of the house touched the side gate at 6:14 PM."
    res = validate(only(text), evening_ledger())
    assert checks(res) == {ROLE_CHECK}
    assert res.failures[0].sentence_index == 0


@pytest.mark.parametrize(
    "text",
    [
        "A person from inside touched the side gate.",
        "A person from indoors touched the side gate.",
        "A person who lives here touched the side gate.",
        "A person from the home touched the side gate.",
        "A person who came from the street touched the side gate.",
        "A person who arrived from the street touched the side gate.",
        "A person from outside touched the side gate.",
        "A person they were expecting touched the side gate.",
        "An expected person touched the side gate.",
        "An unexpected person touched the side gate.",
        "An invited person touched the side gate.",
        "A delivery person touched the side gate.",
        "Someone who came out touched the side gate.",
        "A recognised person touched the side gate.",
        "Someone who arrived from outside touched the side gate.",
        # Second review round: paraphrases that slipped past the first cue list.
        "A person who stepped out of the residence touched the side gate.",
        "A person who emerged from the building touched the side gate.",
        "A person who exited the dwelling touched the side gate.",
        "A person who walked in off the sidewalk touched the side gate.",
        "A person who approached from the curb touched the side gate.",
        "A passer-by touched the side gate.",
        "An unannounced person touched the side gate.",
        "An anticipated person touched the side gate.",
        "A scheduled arrival touched the side gate.",
        "A person from within the property touched the side gate.",
        "A person from beyond the property line touched the side gate.",
        "A local touched the side gate.",
        "An occupier touched the side gate.",
    ],
)
def test_role_cues_caught(text: str) -> None:
    for role, basis in [
        ("external_visitor", "perimeter:side_alley"),
        ("household_insider", "egress:front_door_egress"),
        ("unknown", "origin_null:t1"),
    ]:
        res = validate(first(text), role_ledger(role, basis))
        assert checks(res) == {ROLE_CHECK}, (text, role, res.failures)


def test_ledger_names_with_cue_words_are_not_role_claims() -> None:
    ledger = role_ledger("household_insider", "egress:front_door_egress")
    events = [
        e.model_copy(update={"target": "side_door_egress"}) if e.id == "e16" else e
        for e in ledger.events
    ]
    ledger = ledger.model_copy(
        update={
            "events": events,
            "region_names": {"shed_back": "behind the house"},
            "protected_objects": [
                ProtectedObject(
                    id="po_side_gate",
                    camera_id="side_left",
                    label="side gate",
                    bbox=Box(x1=0, y1=0, x2=1, y2=1),
                )
            ],
        }
    )
    d = good_draft()
    d["sentences"][0] = {
        "text": "Someone who came out of the house entered the side door egress area on the "
        "Left side camera.",
        "event_ids": ["e16"],
    }
    d["sentences"][1] = {"text": "They walked behind the house.", "event_ids": ["e18"]}
    res = validate(d, ledger)
    assert res.passed, res.failures


@pytest.mark.parametrize(
    "text",
    [
        "At 6:14 p.m. Sam touched the side gate.",
        "6:14 p.m. Sam touched the side gate.",
        "At 6:14 PM Sam touched the side gate.",
        "6:14 PM. Sam touched the side gate.",
        "A person touched the side gate! Sam was there.",
        "A person touched the side gate? Sam was there.",
        "A person touched the side gate. Then they left.",
    ],
)
def test_names_after_times_or_stops_caught(text: str) -> None:
    res = validate(only(text), evening_ledger())
    assert checks(res) == {ROLE_CHECK}, res.failures


def test_role_word_lists_cover_spec_terms() -> None:
    words = set(ROLE_BANNED_WORDS)
    for w in ("household", "family", "resident", "owner", "guest", "visitor", "courier",
              "delivery", "stranger", "neighbour", "neighbor", "dad", "mum", "mom", "son",
              "daughter", "wife", "husband"):  # fmt: skip
        assert w in words
    assert {p.role for p in ROLE_PHRASES} == {
        "household_insider",
        "expected_visitor",
        "external_visitor",
    }  # unknown has no phrase


@pytest.mark.parametrize(
    "text",
    [
        "They waved at Sam near the shed.",
        "A person, Maria, walked toward the shed.",
        "They walked toward the shed with Jordan.",
        "They walked toward the Garcia house.",
        "A person in a Nike jacket walked toward the shed.",
    ],
)
def test_names_caught(text: str) -> None:
    res = validate(with_sentence(text, ["e18"]), role_ledger())
    assert checks(res) == {ROLE_CHECK}


@pytest.mark.parametrize(
    "text",
    [
        "On Monday they walked toward the shed.",
        "In November they walked toward the shed.",
        "They walked toward the shed in Nov.",
        "They walked out of the Left side camera's view toward the shed.",
        "They walked toward the Side Gate.",  # protected object label in the ledger
        "They walked toward the area Behind The Shed.",  # region name in the ledger
        '"They" walked toward the shed.',
        "(They walked toward the shed.)",
        "They walked out of view at 10:14 P.M. toward the shed.",
        "They walked toward the shed at 10:14 P.M.",
        "They stopped. then they walked toward the shed.",  # lower case after a stop is fine
    ],
)
def test_allowed_capitalised_tokens_pass(text: str) -> None:
    ledger = role_ledger()
    ledger = ledger.model_copy(
        update={
            "protected_objects": [
                ProtectedObject(
                    id="po_side_gate",
                    camera_id="side_left",
                    label="side gate",
                    bbox=Box(x1=0, y1=0, x2=1, y2=1),
                )
            ],
            "region_names": {"shed_back": "behind the shed"},
        }
    )
    res = validate(with_sentence(text, ["e18"]), ledger)
    assert res.passed, res.failures


def test_identity_banned_word_is_reported_once() -> None:
    res = validate(
        with_sentence("A Hispanic person walked toward the shed.", ["e18"]), role_ledger()
    )
    assert [f.check for f in res.failures] == ["banned_word"]
