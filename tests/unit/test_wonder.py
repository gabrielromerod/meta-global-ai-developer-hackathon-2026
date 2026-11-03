"""Muse Wonder story request and parsing (FR-014, spec section 3 test_wonder_malformed)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from vigil.meta.wonder import (
    ROLE_PHRASES,
    PixelLeakError,
    StoryFormatError,
    assert_no_media,
    build_story_request,
    parse_story,
    role_phrase_for,
    story_schema,
    write_story,
)
from vigil.models import (
    Appearance,
    Event,
    Gap,
    RuleHit,
    StoryDraft,
    Subject,
    Visit,
    VisitLedger,
)

GOOD = {
    "verdict_proposal": "noteworthy",
    "sentences": [
        {"text": "A person walked up the side path at 10:13 PM.", "event_ids": ["e16"]},
        {"text": "They touched the side gate at 10:14 PM.", "event_ids": ["e17"]},
    ],
    "gap_after_sentence": [{"gap_id": "g4", "after": 1}],
    "watch_proposals": [],
}


class FakeClient:
    def __init__(self, answer: dict | str):
        self.answer = answer if isinstance(answer, str) else json.dumps(answer)
        self.calls: list[dict] = []

    def upload(self, path):  # pragma: no cover - must never be called
        raise AssertionError("Wonder must never upload media")

    def responses(self, model, body, purpose, visit_id=None, stream=False, **kw):
        self.calls.append({"model": model, "body": body, "purpose": purpose,
                           "visit_id": visit_id, **kw})  # fmt: skip
        return {"output_text": self.answer, "_vigil": {"call_id": "mc_9", "cached": False}}


@pytest.fixture
def ledger(po_side_gate) -> VisitLedger:
    po = po_side_gate.model_copy(update={"mask_path": "data/masks/po_side_gate.png",
                                         "call_id": "mc_sam_1"})  # fmt: skip
    events = [
        Event(id="e16", camera_id="side_left", track_id="t5", type="enter",
              t0=780.0, t1=781.0, clip_t0=775.0, clip_t1=790.0),
        Event(id="e17", camera_id="side_left", track_id="t5", type="touch",
              t0=840.0, t1=842.0, target="po_side_gate", clip_t0=835.0, clip_t1=850.0),
    ]  # fmt: skip
    return VisitLedger(
        visit=Visit(
            id="v3",
            scenario="C",
            t0=780.0,
            t1=900.0,
            event_ids=["e16", "e17"],
            gap_ids=["g4"],
            track_ids=["t5"],
        ),
        events=events,
        gaps=[
            Gap(
                id="g4",
                visit_id="v3",
                kind="blind_spot",
                t0=845.0,
                t1=886.0,
                from_camera="side_left",
                to_camera="side_left",
                region_id="shed_back",
            )
        ],
        protected_objects=[po],
        rule_hits=[RuleHit(rule_id="r7", visit_id="v3", event_id="e17")],
        appearance={"t5": Appearance(tag="T3", **{"class": "person"}, upper_color="navy")},
        camera_names={"side_left": "Left side"},
        # 10:00 PM PST; a fixed offset keeps the test exact without the tzdata package.
        session_start=datetime(2026, 11, 2, 22, 0, tzinfo=timezone(timedelta(hours=-8))),
    )


# --- request: JSON only, never pixels (spec 5.8) -----------------------------------------


def test_story_request_has_no_pixels_or_file_ids(ledger):
    body = build_story_request(ledger)
    text = json.dumps(body)
    for forbidden in ("input_video", "input_image", "file_id", "mask_path", "data:image",
                      "mc_sam_1", "masks/"):  # fmt: skip
        assert forbidden not in text
    assert "e17" in text
    assert "g4" in text
    assert "po_side_gate" in text
    content = body["input"][0]["content"]
    assert all(part["type"] == "input_text" for part in content)
    assert "model" not in body


def test_story_request_carries_local_clock_times(ledger):
    sent = json.loads(
        build_story_request(ledger)["input"][0]["content"][0]["text"].split("\n", 1)[1]
    )
    e17 = next(e for e in sent["events"] if e["id"] == "e17")
    assert e17["clock_t0"] == "10:14 PM"


@pytest.mark.parametrize(
    "body",
    [
        {"input": [{"type": "input_image", "image_url": "https://x/y.png"}]},
        {"input": [{"type": "input_video", "file_id": "file-abc"}]},
        {"input": [{"type": "input_text", "text": "see file-abc123"}]},
        {"input": [{"type": "input_text", "text": "data:image/png;base64,AAAA"}]},
    ],
)
def test_assert_no_media_blocks_pixels(body):
    with pytest.raises(PixelLeakError):
        assert_no_media(body)


# --- schema --------------------------------------------------------------------------------


def test_story_schema_limits_ids_and_proposal(ledger):
    schema = story_schema(ledger)
    props = schema["properties"]
    assert props["verdict_proposal"]["enum"] == ["normal", "noteworthy"]
    sentence = props["sentences"]["items"]
    assert set(sentence["properties"]) == {"text", "event_ids"}
    assert sentence["properties"]["event_ids"]["items"]["enum"] == ["e16", "e17"]
    gap = props["gap_after_sentence"]["items"]
    assert gap["properties"]["gap_id"]["enum"] == ["g4"]
    watch = props["watch_proposals"]["items"]
    assert watch["properties"]["reason_event_id"]["enum"] == ["e16", "e17"]
    assert watch["properties"]["camera_id"]["enum"] == ["side_left"]


def test_story_request_strict_json_schema_by_default(ledger):
    fmt = build_story_request(ledger)["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["schema"] == story_schema(ledger)


def test_story_request_plain_json_mode(ledger):
    body = build_story_request(ledger, schema_mode="json")
    assert "text" not in body
    assert '"verdict_proposal"' in body["instructions"]


# --- write_story ---------------------------------------------------------------------------


def test_write_story_returns_draft(ledger):
    fake = FakeClient(GOOD)
    draft = write_story(fake, ledger)
    assert isinstance(draft, StoryDraft)
    assert draft.verdict_proposal == "noteworthy"
    assert [s.event_ids for s in draft.sentences] == [["e16"], ["e17"]]
    assert all(s.source == "wonder" and s.gap_id is None for s in draft.sentences)
    assert draft.gap_after_sentence[0].gap_id == "g4"
    [call] = fake.calls
    assert call["model"] == "muse-wonder-1.0"
    assert call["purpose"] == "story"
    assert call["feature"] == "story"
    assert call["visit_id"] == "v3"


def test_write_story_retry_includes_failures(ledger):
    fake = FakeClient(GOOD)
    write_story(fake, ledger, failures=["sentence 0 cites e99, which is not in this visit"])
    sent = json.dumps(fake.calls[0]["body"])
    assert "e99" in sent
    assert "rejected" in sent


def test_write_story_plain_json_mode_tolerates_fence(ledger):
    fake = FakeClient("```json\n" + json.dumps(GOOD) + "\n```")
    draft = write_story(fake, ledger, schema_mode="json")
    assert len(draft.sentences) == 2


@pytest.mark.parametrize(
    "answer",
    [
        "The person was at the gate.",  # not JSON
        "{",  # truncated
        json.dumps([GOOD]),  # wrong top-level type
        json.dumps({**GOOD, "verdict_proposal": "needs_attention"}),  # only rules can
        json.dumps({**GOOD, "verdict_proposal": "cant_confirm"}),
        json.dumps({k: v for k, v in GOOD.items() if k != "sentences"}),
        json.dumps({**GOOD, "sentences": [{"text": "x", "event_ids": ["e17"], "source": "code"}]}),
        json.dumps({**GOOD, "sentences": [{"text": "x", "event_ids": "e17"}]}),
        json.dumps({**GOOD, "gap_after_sentence": [{"gap_id": "g4", "after": "one"}]}),
        json.dumps({**GOOD, "mood": "calm"}),
    ],
)
def test_wonder_malformed(ledger, answer):
    """Malformed JSON or a schema mismatch is a typed validator failure (spec section 3)."""
    with pytest.raises(StoryFormatError) as exc:
        write_story(FakeClient(answer), ledger)
    failures = exc.value.failures
    assert failures
    assert all(f.check == "schema" for f in failures)
    assert exc.value.call_id == "mc_9"


def test_parse_story_is_pure():
    draft = parse_story(json.dumps(GOOD))
    assert draft.sentences[1].text.startswith("They touched")


# --- roles in the ledger and validator check 7 (FR-044, spec 9.4) -------------------------


ROLE_EXTERNAL = "someone who arrived from outside the property"


def _subject(sid: str, role: str, basis: str) -> Subject:
    return Subject(id=sid, visit_id="v3", track_ids=["t5"], actor_role=role, role_basis=basis)


@pytest.mark.parametrize(
    ("role", "basis", "phrase"),
    [
        ("household_insider", "egress:front_door_egress", "someone who came out of the house"),
        ("household_insider", "checkin:c1", None),  # check-in subjects get no role phrase
        ("household_insider", "group:household_insider", None),  # nor do group subjects
        ("expected_visitor", "window:w3", "an expected visitor"),
        ("external_visitor", "perimeter:side_alley", ROLE_EXTERNAL),
        ("unknown", "origin_null:t5", None),
        ("unknown", "gap_unresolved:g4", None),
    ],
)  # fmt: skip
def test_role_phrase_for_subject(role, basis, phrase):
    assert role_phrase_for(_subject("s1", role, basis)) == phrase


def test_role_phrases_map_each_phrase_to_one_role():
    assert ROLE_PHRASES == {
        "someone who came out of the house": "household_insider",
        "an expected visitor": "expected_visitor",
        "someone who arrived from outside the property": "external_visitor",
    }


def test_story_request_carries_subjects_roles_and_allowed_phrases(ledger):
    events = [
        e.model_copy(update={"subject_id": "s1", "actor_role": "external_visitor"})
        for e in ledger.events
    ]
    ledger = ledger.model_copy(
        update={
            "events": events,
            "subjects": [_subject("s1", "external_visitor", "perimeter:side_alley")],
        }
    )
    sent = json.loads(
        build_story_request(ledger)["input"][0]["content"][0]["text"].split("\n", 1)[1]
    )
    [subject] = sent["subjects"]
    assert subject["actor_role"] == "external_visitor"
    assert subject["role_basis"] == "perimeter:side_alley"
    assert subject["role_phrase"] == "someone who arrived from outside the property"
    assert {e["subject_id"] for e in sent["events"]} == {"s1"}
    assert {e["actor_role"] for e in sent["events"]} == {"external_visitor"}


def test_story_request_subject_without_phrase_says_so(ledger):
    ledger = ledger.model_copy(
        update={"subjects": [_subject("s1", "household_insider", "checkin:c1")]}
    )
    sent = json.loads(
        build_story_request(ledger)["input"][0]["content"][0]["text"].split("\n", 1)[1]
    )
    assert sent["subjects"][0]["role_phrase"] is None


def test_story_prompt_states_the_role_phrase_rules():
    from vigil.meta.prompts import load_prompt

    text = load_prompt("story").text
    for phrase in ROLE_PHRASES:
        assert f'"{phrase}"' in text
    lower = text.lower()
    for word in ("household", "family", "guest", "visitor", "delivery", "stranger", "neighbour"):
        assert word in lower
    assert "role_phrase" in text
    assert "capitalised" in lower
    assert "different roles" in lower


# --- role phrases come from config/role_phrases.json (single source with check 7) ---------


def test_role_phrases_load_from_the_validator_config():
    from pathlib import Path

    from vigil.meta.wonder import ROLE_PHRASES_PATH, load_role_phrases

    assert Path(ROLE_PHRASES_PATH).name == "role_phrases.json"
    raw = json.loads(Path(ROLE_PHRASES_PATH).read_text(encoding="utf-8"))
    assert {p["phrase"].lower(): p["role"] for p in raw["phrases"]} == ROLE_PHRASES
    assert load_role_phrases() == load_role_phrases(ROLE_PHRASES_PATH)


def test_role_phrases_follow_an_edited_config(tmp_path):
    from vigil.meta.wonder import load_role_phrases, role_phrase_for

    path = tmp_path / "role_phrases.json"
    path.write_text(
        json.dumps(
            {
                "phrases": [
                    {"phrase": "Someone from inside", "role": "household_insider",
                     "basis_prefixes": ["egress:", "checkin:"]},
                    {"phrase": "a person from outside", "role": "external_visitor"},
                ]
            }
        ),
        encoding="utf-8",
    )  # fmt: skip
    phrases = load_role_phrases(path)
    assert [(p.phrase, p.role, p.basis_prefixes) for p in phrases] == [
        ("someone from inside", "household_insider", ("egress:", "checkin:")),
        ("a person from outside", "external_visitor", ()),
    ]
    subj = _subject("s1", "household_insider", "checkin:c1")
    assert role_phrase_for(subj, phrases) == "someone from inside"
    assert role_phrase_for(_subject("s1", "expected_visitor", "window:w3"), phrases) is None


def test_role_phrases_fall_back_when_the_config_is_absent(tmp_path):
    from vigil.meta.wonder import DEFAULT_ROLE_PHRASES, load_role_phrases

    assert load_role_phrases(tmp_path / "missing.json") == DEFAULT_ROLE_PHRASES
    assert {p.phrase: p.role for p in DEFAULT_ROLE_PHRASES} == ROLE_PHRASES
