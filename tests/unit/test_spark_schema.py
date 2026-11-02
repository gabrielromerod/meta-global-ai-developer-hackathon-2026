"""Muse Spark request builders and parsers (FR-009, FR-021, FR-013 fallback, NFR-003)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from vigil.meta.spark import (
    CARRY_ITEMS,
    AppearanceSchemaError,
    ClarifyingQuestion,
    RuleDraft,
    TargetCatalog,
    appearance_notes,
    appearance_schema,
    build_appearance_request,
    build_rule_request,
    compile_rule,
    parse_appearance,
    rule_schema,
    triage,
)
from vigil.models import COLORS, VisitSummary

# Whole name tokens (split on "_"), so "package" does not match "age".
SENSITIVE = re.compile(
    r"(?:^|_)(face|facial|age|gender|sex|skin|ethnic\w*|race|hair|beard|height|weight|build)(?:$|_)"
)
EXPECTED_TRACK_FIELDS = {
    "tag",
    "class",
    "upper_color",
    "lower_color",
    "carrying",
    "vehicle_color",
    "vehicle_body",
}


class FakeClient:
    """Stands in for MetaClient at the request-builder boundary (no HTTP)."""

    def __init__(self, answer: dict | str):
        self.answer = answer if isinstance(answer, str) else json.dumps(answer)
        self.calls: list[dict] = []
        self.uploads: list[Path] = []

    def upload(self, path: Path) -> str:
        self.uploads.append(Path(path))
        return "file-test-001"

    def responses(self, model, body, purpose, visit_id=None, stream=False, **kw):
        self.calls.append({"model": model, "body": body, "purpose": purpose, **kw})
        return {"output_text": self.answer, "_vigil": {"call_id": "mc_1", "cached": False}}


def _walk(node, names: set[str]) -> None:
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            names.update(props)
        for v in node.values():
            _walk(v, names)
    elif isinstance(node, list):
        for v in node:
            _walk(v, names)


def _strict_ok(node) -> None:
    """Every object is closed and lists every property as required (strict subset)."""
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
            assert set(node["required"]) == set(node["properties"])
        for v in node.values():
            _strict_ok(v)
    elif isinstance(node, list):
        for v in node:
            _strict_ok(v)


def _track(**kw) -> dict:
    base = {
        "tag": "T3",
        "class": "person",
        "upper_color": "navy",
        "lower_color": "grey",
        "carrying": ["backpack"],
        "vehicle_color": None,
        "vehicle_body": None,
    }
    return {**base, **kw}


# --- appearance schema (FR-009, NFR-003) -------------------------------------------------


def test_appearance_schema_tag_is_enum_of_given_tags():
    schema = appearance_schema(["T1", "T3"])
    item = schema["properties"]["tracks"]["items"]
    assert item["properties"]["tag"]["enum"] == ["T1", "T3"]
    assert set(item["properties"]) == EXPECTED_TRACK_FIELDS
    colours = item["properties"]["upper_color"]["enum"]
    assert set(colours) - {None} == set(COLORS)
    _strict_ok(schema)


def test_appearance_schema_has_no_sensitive_fields():
    names: set[str] = set()
    _walk(appearance_schema(["T1"]), names)
    assert names == EXPECTED_TRACK_FIELDS | {"tracks"}
    assert not [n for n in names if SENSITIVE.search(n)]
    assert not [i for i in CARRY_ITEMS if SENSITIVE.search(i)]


def test_appearance_schema_needs_tags():
    with pytest.raises(ValueError):
        appearance_schema([])


def test_parse_appearance_valid():
    notes = parse_appearance(json.dumps({"tracks": [_track(), _track(tag="T1")]}), ["T1", "T3"])
    assert set(notes) == {"T1", "T3"}
    assert notes["T3"].upper_color == "navy"
    assert notes["T3"].class_ == "person"
    assert notes["T3"].carrying == ["backpack"]


def test_unknown_tag_rejected():
    with pytest.raises(AppearanceSchemaError, match="T9"):
        parse_appearance(json.dumps({"tracks": [_track(tag="T9")]}), ["T1", "T3"])


@pytest.mark.parametrize("field", ["gender", "age", "skin_tone", "ethnicity", "face"])
def test_sensitive_field_in_response_rejected(field):
    with pytest.raises(AppearanceSchemaError):
        parse_appearance(json.dumps({"tracks": [_track(**{field: "x"})]}), ["T3"])


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps({"tracks": [_track(upper_color="teal")]}),
        json.dumps({"tracks": [_track(), _track()]}),  # duplicate tag
        json.dumps({"tracks": [_track(carrying=["knife"])]}),
        json.dumps({"tracks": [_track(vehicle_body="spaceship")]}),
        json.dumps({"tracks": [_track(**{"class": "man"})]}),
        json.dumps({"tracks": [], "extra": 1}),
        json.dumps({"tracks": [{k: v for k, v in _track().items() if k != "carrying"}]}),
    ],
)
def test_parse_appearance_rejects_schema_violations(bad):
    with pytest.raises(AppearanceSchemaError):
        parse_appearance(bad, ["T3"])


def test_appearance_request_shape():
    body = build_appearance_request("file-test-001", ["T1", "T3"])
    content = body["input"][0]["content"]
    assert {"type": "input_video", "file_id": "file-test-001"} in content
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["schema"] == appearance_schema(["T1", "T3"])
    instructions = body["instructions"].lower()
    for word in ("gender", "age", "ethnicity", "skin", "face"):
        assert word in instructions  # forbidden explicitly
    assert "model" not in body  # MetaClient adds it


def test_appearance_notes_uploads_and_parses(tmp_path: Path):
    clip = tmp_path / "tagged.mp4"
    clip.write_bytes(b"\x00" * 32)
    fake = FakeClient({"tracks": [_track()]})
    notes = appearance_notes(fake, clip, ["T3"])
    assert notes["T3"].lower_color == "grey"
    assert fake.uploads == [clip]
    [call] = fake.calls
    assert call["model"] == "muse-spark-1.3"
    assert call["purpose"] == "appearance_notes"
    assert call["feature"] == "appearance"


def test_appearance_notes_rejects_unknown_tag_from_model(tmp_path: Path):
    clip = tmp_path / "tagged.mp4"
    clip.write_bytes(b"\x00" * 32)
    with pytest.raises(AppearanceSchemaError):
        appearance_notes(FakeClient({"tracks": [_track(tag="T7")]}), clip, ["T3"])


# --- rule compile (FR-021) ---------------------------------------------------------------


@pytest.fixture
def catalog(sample_config, po_side_gate) -> TargetCatalog:
    return TargetCatalog.from_config(sample_config, [po_side_gate])


def _rule_answer(**kw) -> dict:
    base = {
        "status": "rule",
        "question": None,
        "name": "Side gate after 10 PM",
        "target_id": "po_side_gate",
        "trigger": "touch",
        "min_dwell_s": None,
        "active_start": "22:00",
        "active_end": "06:00",
        "severity": "needs_attention",
        "identity_exception": False,
    }
    return {**base, **kw}


def test_catalog_lists_existing_objects_zones_and_lines(catalog):
    ids = catalog.ids()
    assert "po_side_gate" in ids
    assert {"porch", "driveway", "backyard", "side_yard"} <= set(ids)
    assert "side_gate" in ids
    assert catalog.get("po_side_gate").kind == "protected_object"
    assert catalog.get("side_gate").kind == "line"


def test_rule_schema_targets_limited_to_catalog(catalog):
    schema = rule_schema(catalog)
    assert set(schema["properties"]["target_id"]["enum"]) - {None} == set(catalog.ids())
    _strict_ok(schema)
    body = build_rule_request("tell me if anyone opens the gate after 10", catalog)
    assert body["text"]["format"]["schema"] == schema


def test_compile_rule_reference_phrasing(catalog, rule_r7):
    fake = FakeClient(_rule_answer())
    draft = compile_rule(fake, "tell me if anyone opens this gate after 10 PM", catalog)
    assert isinstance(draft, RuleDraft)
    rule = draft.rule
    assert rule.target == rule_r7.target
    assert rule.trigger == rule_r7.trigger
    assert rule.active == rule_r7.active
    assert rule.severity == "needs_attention"
    assert rule.state == "draft"
    assert rule.applies_to == "anyone"
    assert any("never identifies" in note for note in draft.limits)
    assert fake.calls[0]["model"] == "muse-spark-1.3"
    assert fake.calls[0]["feature"] == "rule_compile"


def test_compile_rule_identity_exception_becomes_anyone(catalog):
    text = "alert me if anyone except my family goes in the backyard at night"
    fake = FakeClient(
        _rule_answer(
            name="Backyard at night",
            target_id="backyard",
            trigger="enter",
            active_start="23:00",
            active_end="05:00",
        )
    )
    draft = compile_rule(fake, text, catalog)
    assert isinstance(draft, RuleDraft)
    assert draft.rule.applies_to == "anyone"
    assert draft.identity_exception is True
    assert any("family" in n.lower() or "everyone" in n.lower() for n in draft.limits)
    assert draft.rule.target.kind == "zone"


def test_compile_rule_unresolvable_target_asks_a_question(catalog):
    fake = FakeClient(
        _rule_answer(status="clarify", target_id=None, question="Which object do you mean?")
    )
    out = compile_rule(fake, "tell me if anyone touches the thing", catalog)
    assert isinstance(out, ClarifyingQuestion)
    assert out.question == "Which object do you mean?"
    assert "po_side_gate" in out.options


def test_compile_rule_target_outside_catalog_is_not_a_rule(catalog):
    out = compile_rule(FakeClient(_rule_answer(target_id="po_garage")), "garage door", catalog)
    assert isinstance(out, ClarifyingQuestion)


def test_compile_rule_bad_time_asks_a_question(catalog):
    out = compile_rule(FakeClient(_rule_answer(active_start="25:00")), "gate at 25", catalog)
    assert isinstance(out, ClarifyingQuestion)


def test_compile_rule_malformed_answer_asks_a_question(catalog):
    out = compile_rule(FakeClient("nope"), "gate after ten", catalog)
    assert isinstance(out, ClarifyingQuestion)


# --- triage fallback (FR-013, FR-028) ----------------------------------------------------


def _summary(**kw) -> VisitSummary:
    base = dict(
        visit_id="v1",
        cameras=["front"],
        event_types=["enter", "exit"],
        rule_fired=False,
        protected_touched=False,
        unresolved_gap=False,
        duration_s=12.0,
    )
    return VisitSummary(**{**base, **kw})


@pytest.mark.parametrize("flag", ["rule_fired", "protected_touched", "unresolved_gap"])
def test_triage_forced_cases_make_no_call(flag):
    fake = FakeClient({"escalate": False, "reason": "x"})
    decision = triage(fake, _summary(**{flag: True}))
    assert decision.escalate
    assert decision.forced
    assert decision.source == "code"
    assert fake.calls == []


def test_triage_spark_decides_otherwise():
    fake = FakeClient({"escalate": False, "reason": "a short delivery at the porch"})
    decision = triage(fake, _summary())
    assert decision.escalate is False
    assert decision.source == "spark"
    assert not decision.forced
    [call] = fake.calls
    assert call["model"] == "muse-spark-1.3"
    assert call["feature"] == "triage"
    assert call["body"]["text"]["format"]["type"] == "json_schema"


def test_compile_rule_accepts_dict_catalog():
    catalog = {
        "protected_object": [{"id": "po_side_gate", "label": "side gate"}],
        "zone": ["porch"],
    }
    draft = compile_rule(FakeClient(_rule_answer()), "anyone opens the gate after 10", catalog)
    assert isinstance(draft, RuleDraft)
    assert draft.rule.target.kind == "protected_object"
    assert TargetCatalog.coerce(catalog).get("porch").kind == "zone"


def test_compile_rule_with_no_targets_asks_first():
    fake = FakeClient(_rule_answer())
    out = compile_rule(fake, "anyone at the gate", TargetCatalog())
    assert isinstance(out, ClarifyingQuestion)
    assert fake.calls == []


@pytest.mark.parametrize("name", ["appearance_notes", "story", "rule_compile", "triage"])
def test_prompts_forbid_identity_and_judgement_and_require_citations(name):
    from vigil.meta.prompts import load_prompt

    prompt = load_prompt(name)
    assert prompt.version
    text = prompt.text.lower()
    for word in ("gender", "age", "ethnicity", "skin", "face", "suspicious", "intruder", "thief"):
        assert word in text, f"{name} must explicitly forbid {word!r}"
    assert "never" in text
    assert "cite" in text
