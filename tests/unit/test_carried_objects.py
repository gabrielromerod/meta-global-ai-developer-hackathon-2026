"""Possible weapons carried onto the property (owner decision, Nov 4).

SAM 3.1 is asked for every listed object phrase on every active window. A `carry` event is
code: the object's box sits on a tracked person for at least MIN_FRAMES frames. A default rule
turns a carry by anyone who is not household (spatial origin and check-ins only, FR-044) into
needs_attention; Wonder only narrates, and never sees pixels.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vigil.models import Box, Event, Track, TrackFrame, Visit, Window
from vigil.perception.events import CARRIED_OBJECTS, build_events
from vigil.pipeline import phrases_for
from vigil.reasoning.rules import DEFAULT_RULES_PATH, evaluate_rules, load_rules
from vigil.reasoning.verdict import compose

FPS = 10.0
START = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)


def _track(tid: str, cls: str, phrase: str, boxes: list[tuple[float, Box]]) -> Track:
    frames = [TrackFrame(t=t, box=b) for t, b in boxes]
    return Track(
        id=tid,
        camera_id="front",
        cls=cls,
        phrase=phrase,
        t_first=frames[0].t,
        t_last=frames[-1].t,
        frames=frames,
    )


def _walker(n: int = 30) -> Track:
    """A person walking right across the frame at 10 fps, 60x160 px."""
    return _track(
        "front-person-1",
        "person",
        "person",
        [(i / FPS, Box(x1=200 + 10 * i, y1=400, x2=260 + 10 * i, y2=560)) for i in range(n)],
    )


def _held(phrase: str, frames: range, dx: float = 50.0) -> Track:
    """An object box at the walker's hand height, `dx` px right of the walker's left edge."""
    return _track(
        f"front-{phrase}-1",
        "object",
        phrase,
        [
            (i / FPS, Box(x1=200 + 10 * i + dx, y1=470, x2=200 + 10 * i + dx + 14, y2=500))
            for i in frames
        ],
    )


def _carries(events: list[Event]) -> list[Event]:
    return [e for e in events if e.type == "carry"]


def test_knife_and_gun_are_asked_on_every_active_window():
    assert {"knife", "gun"} <= set(CARRIED_OBJECTS)
    window = Window(id="w1", camera_id="front", t0=0.0, t1=10.0, path="w1.mp4")
    assert phrases_for(window, [], START)[:2] == ["person", "car"]
    assert set(CARRIED_OBJECTS) <= set(phrases_for(window, [], START))


def test_carry_event_when_a_knife_box_sits_on_a_person(sample_config):
    events = build_events([_walker(), _held("knife", range(5, 20))], sample_config, [], [])
    (carry,) = _carries(events)
    assert carry.track_id == "front-person-1"  # the person, so the event gets their role
    assert carry.target == "knife"
    assert carry.t0 == pytest.approx(0.5)
    assert carry.t1 == pytest.approx(1.9)


def test_no_carry_for_a_knife_away_from_every_person(sample_config):
    far = _held("knife", range(5, 20), dx=600.0)
    assert _carries(build_events([_walker(), far], sample_config, [], [])) == []


def test_no_carry_for_a_single_frame_hit(sample_config):
    flash = _held("knife", range(7, 8))
    assert _carries(build_events([_walker(), flash], sample_config, [], [])) == []


def test_no_carry_for_objects_that_are_not_listed(sample_config):
    bin_ = _held("bin", range(5, 20))
    assert _carries(build_events([_walker(), bin_], sample_config, [], [])) == []


def _carry(role: str | None) -> Event:
    return Event(
        id="e1",
        visit_id="v1",
        camera_id="front",
        track_id="front-person-1",
        type="carry",
        t0=10.0,
        t1=12.0,
        target="knife",
        clip_t0=0.0,
        clip_t1=20.0,
        actor_role=role,
    )


def _outcome(role: str | None):
    e = _carry(role)
    visit = Visit(id="v1", t0=e.t0, t1=e.t1, event_ids=[e.id])
    rules = load_rules(DEFAULT_RULES_PATH)
    return evaluate_rules(visit, [e], rules, "America/Los_Angeles", START)


@pytest.mark.parametrize("role", ["external_visitor", "unknown", None, "expected_visitor"])
def test_carried_knife_by_a_non_household_person_needs_attention(role):
    outcome = _outcome(role)
    assert [h.rule_id for h in outcome.hits] == ["r_carried_object"]
    assert outcome.floor == "needs_attention"
    assert (
        compose(outcome.floor, False, "normal", True) == "needs_attention"
    )  # Wonder cannot lower it


def test_household_carrying_a_knife_does_not_alert():
    outcome = _outcome("household_insider")
    assert outcome.hits == []
    assert outcome.floor == "normal"


def test_carried_object_rule_is_always_on_and_matches_any_listed_object():
    rule = next(r for r in load_rules(DEFAULT_RULES_PATH) if r.id == "r_carried_object")
    assert rule.trigger == "carry"
    assert rule.target.kind == "carried_object"
    assert rule.target.id == "*"
    assert rule.active is None
    assert rule.applies_to == "non_household"
    assert rule.severity == "needs_attention"


def test_template_says_possible_knife_and_passes_the_validator():
    """Story wording is hedged ("possible knife"); check 5 bans "dangerous" and "threat"."""
    from tests.unit.test_validator import scenario_c_ledger
    from vigil.models import StoryDraft
    from vigil.reasoning.templates import template_story
    from vigil.reasoning.validator import validate

    ledger = scenario_c_ledger()
    first = ledger.events[0]
    events = [
        e.model_copy(update={"type": "carry", "target": "knife"}) if e.id == first.id else e
        for e in ledger.events
    ]
    ledger = ledger.model_copy(update={"events": events})
    sentences = template_story(ledger)
    by_event = {s.event_ids[0]: s.text for s in sentences}
    assert "possible knife" in by_event[first.id]
    assert "marked as a possible knife" in by_event[first.id]  # hedged, model-neutral
    res = validate(StoryDraft(sentences=sentences), ledger)
    assert res.passed, res.failures


@pytest.mark.parametrize("word", ["weapon", "armed", "dangerous", "threat"])
def test_story_may_not_call_a_carried_object_a_weapon(word):
    """The alert comes from the rule; the story stays hedged (check 5 judgement words)."""
    from tests.unit.test_validator import scenario_c_ledger
    from vigil.models import StoryDraft, StorySentence
    from vigil.reasoning.validator import validate

    ledger = scenario_c_ledger()
    e = ledger.events[0]
    text = f"A person was holding a {word} object on the Front entrance camera."
    draft = StoryDraft(sentences=[StorySentence(text=text, event_ids=[e.id], source="wonder")])
    res = validate(draft, ledger)
    assert not res.passed
    assert any(f.check == "banned_word" or word in f.detail for f in res.failures)
