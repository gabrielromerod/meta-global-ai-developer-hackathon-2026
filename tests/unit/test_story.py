"""Story orchestration: writer -> validate -> retry once -> template; code-written gaps (FR-014)."""

from __future__ import annotations

import json
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.unit.test_validator import CAMERA_NAMES, START, good_draft, scenario_c_ledger
from vigil.models import Event, Gap, StoryDraft, Subject, Visit, VisitLedger
from vigil.reasoning.story import gap_sentence, run_story
from vigil.reasoning.templates import template_story
from vigil.reasoning.validator import BANNED_WORDS, validate

REGIONS = {"shed_back": "behind the shed"}


class FakeWriter:
    """Injected stand-in for Muse Wonder: returns scripted outputs, records the failures."""

    def __init__(self, *outputs) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[str] | None] = []

    def __call__(self, ledger: VisitLedger, failures: list[str] | None = None):
        self.calls.append(failures)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def bad_draft() -> dict:
    d = good_draft()
    d["sentences"][1] = {"text": "He checked the shed door.", "event_ids": []}
    return d


def test_valid_draft_is_published_with_code_gap_sentence() -> None:
    writer = FakeWriter(good_draft())
    out = run_story(scenario_c_ledger(), writer, region_names=REGIONS)
    assert out.source == "wonder"
    assert len(writer.calls) == 1
    assert writer.calls[0] is None
    assert [v.passed for v in out.validations] == [True]
    texts = [s.text for s in out.sentences]
    assert len(texts) == 5
    gap_s = out.sentences[2]
    assert gap_s.source == "code"
    assert gap_s.gap_id == "g4"
    assert gap_s.text == "Vigil can't confirm what happened for 41 s behind the shed."
    assert [s.source for s in out.sentences] == ["wonder", "wonder", "code", "wonder", "wonder"]
    assert out.proposal == "noteworthy"
    assert out.proposal_cited is True


def test_retry_once_with_failure_reasons() -> None:
    writer = FakeWriter(bad_draft(), good_draft())
    out = run_story(scenario_c_ledger(), writer, region_names=REGIONS)
    assert out.source == "wonder"
    assert len(writer.calls) == 2
    reasons = writer.calls[1]
    assert reasons
    assert any("uncited" in r for r in reasons)
    assert any("banned_word" in r for r in reasons)
    assert [(v.attempt, v.passed) for v in out.validations] == [(1, False), (2, True)]


def test_two_failures_fall_back_to_template() -> None:
    writer = FakeWriter(bad_draft(), bad_draft())
    out = run_story(scenario_c_ledger(), writer, region_names=REGIONS)
    assert out.source == "template"
    assert len(writer.calls) == 2
    assert [v.passed for v in out.validations] == [False, False]
    assert out.proposal is None
    assert out.proposal_cited is False
    assert out.watch_proposals == []
    assert {s.source for s in out.sentences} == {"template", "code"}
    assert any(s.gap_id == "g4" for s in out.sentences)


@pytest.mark.parametrize(
    "malformed",
    [
        "{not json",
        {"sentences": "nope"},
        {"verdict_proposal": "needs_attention", "sentences": []},
        ValueError("model returned invalid JSON"),
    ],
)
def test_wonder_malformed(malformed) -> None:
    """Global error table: malformed Wonder output counts as a validator failure."""
    writer = FakeWriter(malformed, malformed)
    out = run_story(scenario_c_ledger(), writer, region_names=REGIONS)
    assert out.source == "template"
    assert len(writer.calls) == 2
    assert all(not v.passed for v in out.validations)
    assert all(v.failures[0].check in {"schema", "sentence_count"} for v in out.validations)


def test_malformed_then_valid_recovers() -> None:
    writer = FakeWriter("garbage", json.dumps(good_draft()))
    out = run_story(scenario_c_ledger(), writer, region_names=REGIONS)
    assert out.source == "wonder"


def test_watch_proposals_only_from_validated_draft() -> None:
    d = good_draft()
    d["watch_proposals"] = [{"camera_id": "front", "phrase": "package", "reason_event_id": "e17"}]
    out = run_story(scenario_c_ledger(), FakeWriter(d), region_names=REGIONS)
    assert [w.phrase for w in out.watch_proposals] == ["package"]
    bad = bad_draft()
    bad["watch_proposals"] = d["watch_proposals"]
    out = run_story(scenario_c_ledger(), FakeWriter(bad, bad), region_names=REGIONS)
    assert out.watch_proposals == []


def test_gap_placed_chronologically_when_draft_omits_it() -> None:
    d = good_draft()
    d["gap_after_sentence"] = []
    out = run_story(scenario_c_ledger(), FakeWriter(d), region_names=REGIONS)
    assert [s.source for s in out.sentences] == ["wonder", "wonder", "code", "wonder", "wonder"]


def test_no_writer_means_template() -> None:
    out = run_story(scenario_c_ledger(), None, region_names=REGIONS)
    assert out.source == "template"
    assert out.validations == []


def test_gap_sentence_wording() -> None:
    g = Gap(
        id="g1",
        visit_id="v",
        kind="blind_spot",
        t0=0,
        t1=41.4,
        region_id="shed_back",
        resolved=True,
    )
    assert gap_sentence(g, REGIONS, {}).text == (
        "Vigil can't confirm what happened for 41 s behind the shed."
    )
    g2 = g.model_copy(update={"region_id": None, "t1": 125})
    assert gap_sentence(g2, {}, {}).text == (
        "Vigil can't confirm what happened for 2 min 5 s in a blind spot."
    )
    amb = Gap(id="g2", visit_id="v", kind="ambiguous_link", t0=0, t1=12, from_camera="front")
    assert "more than one" in gap_sentence(amb, {}, CAMERA_NAMES).text
    out = Gap(id="g3", visit_id="v", kind="outage", t0=0, t1=30, from_camera="backyard")
    assert gap_sentence(out, {}, CAMERA_NAMES).text == (
        "Vigil can't confirm what happened for 30 s while the Backyard camera was offline."
    )
    unres = g.model_copy(update={"resolved": False, "t1": 180})
    assert "not seen again" in gap_sentence(unres, REGIONS, {}).text
    for s in (g, g2, amb, out, unres):
        sent = gap_sentence(s, REGIONS, CAMERA_NAMES)
        assert sent.source == "code"
        assert sent.gap_id == s.id


# --- templates ---------------------------------------------------------------


def test_template_cites_events_and_passes_validator() -> None:
    ledger = scenario_c_ledger()
    sentences = template_story(ledger)
    assert 1 <= len(sentences) <= 6
    assert all(s.source == "template" and s.event_ids for s in sentences)
    res = validate(StoryDraft(sentences=sentences), ledger)
    assert res.passed, res.failures
    assert "10:14 PM" in sentences[0].text or "10:13 PM" in sentences[0].text


def test_template_is_deterministic() -> None:
    assert template_story(scenario_c_ledger()) == template_story(scenario_c_ledger())


def test_template_names_zones_in_plain_words() -> None:
    # exit-polygon ids ('to_side_left', 'from_house_side') read as places, not ids
    ledger = scenario_c_ledger()
    targets = {"e16": "to_side_left", "e18": "from_house_side", "e19": "zone_back_yard"}
    events = [
        e.model_copy(update={"target": targets[e.id], "type": "enter"}) if e.id in targets else e
        for e in ledger.events
    ]
    ledger = ledger.model_copy(update={"events": events, "visit": ledger.visit})
    by_event = {s.event_ids[0]: s.text for s in template_story(ledger)}
    assert "entered the side left area" in by_event["e16"]
    assert "entered the house side area" in by_event["e18"]
    assert "entered the back yard area" in by_event["e19"]
    assert not any("_" in t or " to " in t.split(" camera")[0] for t in by_event.values())
    res = validate(StoryDraft(sentences=template_story(ledger)), ledger)
    assert res.passed, res.failures


EVENT_TYPES = ["enter", "exit", "cross", "touch", "removed", "dwell"]
TARGETS = [None, "po_side_gate", "porch", "side_gate", "w2", "to_side_left", "from_house_side",
           "zone_back_yard"]  # fmt: skip


@st.composite
def ledgers(draw: st.DrawFn) -> VisitLedger:
    n = draw(st.integers(min_value=1, max_value=12))
    t = draw(st.floats(min_value=0, max_value=80000))
    events = []
    for i in range(n):
        t += draw(st.floats(min_value=0.5, max_value=30))
        events.append(
            Event(
                id=f"e{i}",
                visit_id="v1",
                camera_id=draw(st.sampled_from(list(CAMERA_NAMES))),
                track_id="t1",
                type=draw(st.sampled_from(EVENT_TYPES)),
                t0=t,
                t1=t + 1,
                target=draw(st.sampled_from(TARGETS)),
                clip_t0=t,
                clip_t1=t + 1,
            )
        )
    visit = Visit(id="v1", t0=events[0].t0, t1=events[-1].t1, event_ids=[e.id for e in events])
    return VisitLedger(visit=visit, events=events, camera_names=CAMERA_NAMES, session_start=START)


@settings(max_examples=60, deadline=None)
@given(ledger=ledgers())
def test_prop_template_always_valid_and_identity_free(ledger: VisitLedger) -> None:
    sentences = template_story(ledger)
    assert 1 <= len(sentences) <= 6
    res = validate(StoryDraft(sentences=sentences), ledger)
    assert res.passed, res.failures
    words = {w.lower() for s in sentences for w in re.findall(r"[A-Za-z]+", s.text)}
    assert not words & set(BANNED_WORDS)


# --- templates with spatial-origin roles (FR-044, validator check 7) ----------------------


def roled(ledger: VisitLedger, subjects: list[Subject]) -> VisitLedger:
    of_track = {tid: s for s in subjects for tid in s.track_ids}
    events = [
        e.model_copy(update={"subject_id": of_track[e.track_id].id,
                             "actor_role": of_track[e.track_id].actor_role})
        if e.track_id in of_track
        else e
        for e in ledger.events
    ]  # fmt: skip
    return ledger.model_copy(update={"events": events, "subjects": subjects})


def _two_track_c() -> VisitLedger:
    ledger = scenario_c_ledger()
    events = [
        e.model_copy(update={"track_id": "t2"}) if e.id in ("e19", "e20") else e
        for e in ledger.events
    ]
    return ledger.model_copy(update={"events": events})


@pytest.mark.parametrize(
    ("role", "basis", "opening"),
    [
        (
            "external_visitor",
            "perimeter:side_alley",
            "Someone who arrived from outside the property",
        ),
        ("household_insider", "egress:front_door_egress", "Someone who came out of the house"),
        ("expected_visitor", "window:w3", "An expected visitor"),
        ("household_insider", "checkin:c1", "A person"),  # check-in: no role phrase
        ("household_insider", "group:household_insider", "A person"),
        ("unknown", "origin_null:t1", "A person"),
    ],
)
def test_template_uses_role_phrase_only_where_allowed(role, basis, opening) -> None:
    s = Subject(id="s1", visit_id="v3", track_ids=["t1", "t2"], actor_role=role, role_basis=basis)
    ledger = roled(_two_track_c(), [s])
    sentences = template_story(ledger)
    assert sentences[0].text.startswith(opening + " ")
    assert all(x.text.startswith("They ") for x in sentences[1:])
    res = validate(StoryDraft(sentences=sentences), ledger)
    assert res.passed, res.failures


def test_template_names_a_new_subject_after_a_broken_chain() -> None:
    subjects = [
        Subject(id="s1", visit_id="v3", track_ids=["t1"], actor_role="household_insider",
                role_basis="egress:front_door_egress"),
        Subject(id="s2", visit_id="v3", track_ids=["t2"], actor_role="unknown",
                role_basis="gap_unresolved:g4"),
    ]  # fmt: skip
    ledger = roled(_two_track_c(), subjects)
    sentences = template_story(ledger)
    by_event = {x.event_ids[0]: x.text for x in sentences}
    assert by_event["e16"].startswith("Someone who came out of the house ")
    assert by_event["e17"].startswith("They ")
    assert by_event["e19"].startswith("A person ")  # not "they": the role did not carry
    assert by_event["e20"].startswith("They ")
    assert validate(StoryDraft(sentences=sentences), ledger).passed


ROLES = ["household_insider", "expected_visitor", "external_visitor", "unknown"]
BASES = ["egress:front_door_egress", "checkin:c1", "window:w1", "perimeter:side_alley",
         "group:x", "gap_unresolved:g1", "ambiguous_link:t1", "origin_null:t1"]  # fmt: skip


@settings(max_examples=60, deadline=None)
@given(
    ledger=ledgers(),
    role=st.sampled_from(ROLES),
    basis=st.sampled_from(BASES),
    with_subject=st.booleans(),
)
def test_prop_template_with_roles_always_valid(ledger, role, basis, with_subject) -> None:
    if with_subject:
        s = Subject(id="s1", visit_id="v1", track_ids=["t1"], actor_role=role, role_basis=basis)
        ledger = roled(ledger, [s])
    else:  # events carry a role but the ledger has no subjects (pipeline without them)
        events = [e.model_copy(update={"actor_role": role}) for e in ledger.events]
        ledger = ledger.model_copy(update={"events": events})
    sentences = template_story(ledger)
    res = validate(StoryDraft(sentences=sentences), ledger)
    assert res.passed, res.failures


def test_instant_ambiguous_gap_sentence_does_not_say_zero_seconds() -> None:
    # Live run, Nov 4: a window boundary left 0.1 s gaps, written as "for 0 s".
    gap = Gap(id="g1", visit_id="v1", kind="ambiguous_link", t0=12.99, t1=13.09,
              from_camera="side_left", to_camera="side_left")  # fmt: skip
    text = gap_sentence(gap, {}, CAMERA_NAMES).text
    assert "0 s" not in text
    assert "more than one later sighting could be them" in text


def _car_ledger() -> VisitLedger:
    """Front left Duo, Nov 4: a parked car in view from the first frame, then a person."""

    def ev(eid, track, typ, t0, target):
        return Event(id=eid, visit_id="v1", camera_id="side_left", track_id=track, type=typ,
                     t0=t0, t1=t0, target=target, clip_t0=t0, clip_t1=t0 + 1)  # fmt: skip

    events = [
        ev("e1", "side_left-car-1", "enter", 0.0, "left_garden"),
        ev("e2", "side_left-person-1", "enter", 0.8, "left_driveway"),
        ev("e3", "side_left-person-1", "exit", 18.8, "left_driveway"),
    ]
    visit = Visit(id="v1", t0=0.0, t1=24.6, event_ids=[e.id for e in events],
                  track_ids=["side_left-car-1", "side_left-person-1"])  # fmt: skip
    return VisitLedger(visit=visit, events=events, camera_names=CAMERA_NAMES, session_start=START)


def test_template_calls_a_car_track_a_vehicle_without_appearance_notes() -> None:
    # Spark described only some cars; the SAM class in the track id still says "car".
    by_event = {s.event_ids[0]: s.text for s in template_story(_car_ledger())}
    assert by_event["e1"].startswith("A vehicle")
    assert by_event["e2"].startswith("A person")


def test_template_does_not_say_entered_for_what_was_there_when_recording_started() -> None:
    ledger = _car_ledger()
    by_event = {s.event_ids[0]: s.text for s in template_story(ledger)}
    assert "was already in the left garden area when the recording started" in by_event["e1"]
    assert "entered the left driveway area" in by_event["e2"]
    assert validate(StoryDraft(sentences=template_story(ledger)), ledger).passed


def test_template_tells_the_person_not_the_parked_cars() -> None:
    # Live run, Nov 4: four parked cars filled all six sentences and the person was dropped.
    def ev(eid, track, typ, t0, target):
        return Event(id=eid, visit_id="v1", camera_id="side_left", track_id=track, type=typ,
                     t0=t0, t1=t0, target=target, clip_t0=t0, clip_t1=t0 + 1)  # fmt: skip

    events = []
    for n in range(1, 5):
        car = f"side_left-car-{n}"
        events += [ev(f"c{n}a", car, "enter", 0.0, "left_garden"),
                   ev(f"c{n}b", car, "enter", 0.0, "left_driveway"),
                   ev(f"c{n}z", car, "exit", 24.6, "left_garden")]  # fmt: skip
    events += [
        ev("p1", "side_left-person-1", "enter", 0.8, "left_driveway"),
        ev("p2", "side_left-person-1", "enter", 18.7, "left_street"),
        ev("p3", "side_left-person-1", "exit", 19.3, "left_street"),
    ]
    events.sort(key=lambda e: (e.t0, e.id))
    visit = Visit(id="v1", t0=0.0, t1=24.6, event_ids=[e.id for e in events],
                  track_ids=sorted({e.track_id for e in events}))  # fmt: skip
    ledger = VisitLedger(visit=visit, events=events, camera_names=CAMERA_NAMES, session_start=START)
    story = template_story(ledger)
    texts = [s.text for s in story]
    assert texts[0].startswith("4 vehicles were already in view when the recording started")
    assert set(story[0].event_ids) == {f"c{n}{x}" for n in range(1, 5) for x in "ab"}
    assert [s.event_ids for s in story[1:]] == [["p1"], ["p2"], ["p3"]]
    assert texts[1].startswith("A person entered the left driveway area")
    assert not any("vehicle left" in t for t in texts)  # the clip ended; the cars did not leave
    assert validate(StoryDraft(sentences=story), ledger).passed
