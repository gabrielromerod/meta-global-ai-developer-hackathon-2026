"""Story orchestration: writer -> validate -> retry once -> template; code-written gaps (FR-014)."""

from __future__ import annotations

import json
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.unit.test_validator import CAMERA_NAMES, START, good_draft, scenario_c_ledger
from vigil.models import Event, Gap, StoryDraft, Visit, VisitLedger
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


EVENT_TYPES = ["enter", "exit", "cross", "touch", "removed", "dwell"]


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
                target=draw(st.sampled_from([None, "po_side_gate", "porch", "side_gate", "w2"])),
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
