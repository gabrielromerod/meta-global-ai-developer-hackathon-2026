"""Muse Spark request builders and parsers (FR-009, FR-021, FR-013 fallback, NFR-003)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from vigil.meta.spark import (
    BASIS_NOTES,
    CARRY_ITEMS,
    HOUSEHOLD_BASIS,
    AppearanceSchemaError,
    ClarifyingQuestion,
    RuleDraft,
    TargetCatalog,
    appearance_notes,
    appearance_schema,
    build_appearance_request,
    build_rule_request,
    classify_role_phrasing,
    compile_rule,
    named_person_notice,
    parse_appearance,
    rule_person_terms,
    rule_schema,
    triage,
)
from vigil.models import COLORS, ActiveWindow, Rule, RuleTarget, VisitSummary

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
    from tests.fixtures.video.synth import blob_clip

    blob_clip(clip, 0.2, size=(160, 90))
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
    from tests.fixtures.video.synth import blob_clip

    blob_clip(clip, 0.2, size=(160, 90))
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
        "applies_to": "anyone",
        "named_person": False,
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


SPEC_BASIS = (
    "Vigil treats someone as household only when it saw them come out of the house's own "
    "doors, or when a household member checked in on the app just before coming into view. "
    "Household members arriving from the street without checking in, and anyone Vigil loses "
    "track of, count as non-household and can trigger this rule. Vigil places people by where "
    "they came from; it does not identify anyone and creates no face, voice or body templates."
)
SAM_NOTICE = (
    "Vigil can't recognise individuals. It treats someone as household only if they came out "
    "of the house's own doors or checked in on the app, so Sam is exempt only in those cases."
)


def test_compile_rule_reference_phrasing(catalog, rule_r7):
    """UC-03: "anyone except family ... after dark" compiles to r7 (spec 9.4, Nov 2)."""
    fake = FakeClient(
        _rule_answer(
            name="Side gate after dark",
            active_start="17:30",
            active_end="06:00",
            applies_to="non_household",
        )
    )
    text = "Tell me if anyone except family opens this gate after dark"
    draft = compile_rule(fake, text, catalog)
    assert isinstance(draft, RuleDraft)
    rule = draft.rule
    assert rule.target == rule_r7.target
    assert rule.trigger == rule_r7.trigger
    assert rule.active == rule_r7.active
    assert rule.severity == rule_r7.severity
    assert rule.applies_to == rule_r7.applies_to == "non_household"
    assert rule.state == "draft"
    assert draft.basis_note == "Applies to everyone except household members. " + SPEC_BASIS
    assert draft.notice is None
    assert draft.identity_exception is True
    assert any("does not identify anyone" in note for note in draft.limits)
    assert fake.calls[0]["model"] == "muse-spark-1.3"
    assert fake.calls[0]["feature"] == "rule_compile"


def test_household_basis_is_the_spec_text():
    assert HOUSEHOLD_BASIS == SPEC_BASIS
    assert set(BASIS_NOTES) == {"anyone", "non_household", "external_visitor_only"}
    for note in BASIS_NOTES.values():
        assert note.endswith("creates no face, voice or body templates.")


def test_compile_rule_family_exception_becomes_non_household(catalog):
    """Revised Nov 2 (FR-021): "except my family" maps to the non_household role, no longer
    to anyone. Replaces test_compile_rule_identity_exception_becomes_anyone."""
    text = "alert me if anyone except my family goes in the backyard at night"
    fake = FakeClient(
        _rule_answer(
            name="Backyard at night",
            target_id="backyard",
            trigger="enter",
            active_start="23:00",
            active_end="05:00",
            applies_to="anyone",  # the model got it wrong; code maps the phrase
        )
    )
    draft = compile_rule(fake, text, catalog)
    assert isinstance(draft, RuleDraft)
    assert draft.rule.applies_to == "non_household"
    assert draft.identity_exception is True
    assert draft.basis_note.startswith("Applies to everyone except household members.")
    assert draft.rule.target.kind == "zone"


# --- the FR-021 reference set: 10 phrasings, 4 of them role phrasings ----------------------

REFERENCE_SET = [
    # (text, model answer overrides, expected rule fields, expected notice name or None)
    (
        "Tell me if anyone except family opens this gate after dark",
        {"active_start": "17:30", "active_end": "06:00", "applies_to": "non_household"},
        {"target": "po_side_gate", "trigger": "touch", "applies_to": "non_household"},
        None,
    ),
    (
        "Alert me when anyone except us touches the side gate at night",
        {"active_start": "17:30", "active_end": "06:00", "applies_to": "anyone"},
        {"target": "po_side_gate", "trigger": "touch", "applies_to": "non_household"},
        None,
    ),
    (
        "Let me know if anyone who is not the household goes into the backyard",
        {"target_id": "backyard", "trigger": "enter", "active_start": None, "active_end": None,
         "applies_to": "non_household"},
        {"target": "backyard", "trigger": "enter", "applies_to": "non_household"},
        None,
    ),
    (
        "Strangers only: tell me if they touch the side gate after 10 PM",
        {"applies_to": "non_household"},  # the model got it wrong; code maps the phrase
        {"target": "po_side_gate", "trigger": "touch", "applies_to": "external_visitor_only"},
        None,
    ),
    (
        "Alert me if anyone touches the side gate, but not guests or deliveries",
        {"active_start": None, "active_end": None, "applies_to": "external_visitor_only"},
        {"target": "po_side_gate", "trigger": "touch", "applies_to": "external_visitor_only"},
        None,
    ),
    (
        "Tell me if anyone except Sam enters the backyard",
        {"name": "Backyard except Sam", "target_id": "backyard", "trigger": "enter",
         "active_start": None, "active_end": None, "applies_to": "non_household",
         "named_person": True},
        {"target": "backyard", "trigger": "enter", "applies_to": "non_household"},
        "Sam",
    ),
    (
        "Tell me if anyone opens the side gate",
        {"active_start": None, "active_end": None},
        {"target": "po_side_gate", "trigger": "touch", "applies_to": "anyone"},
        None,
    ),
    (
        "Make a note when someone crosses the side gate line",
        {"target_id": "side_gate", "trigger": "cross", "active_start": None,
         "active_end": None, "severity": "noteworthy"},
        {"target": "side_gate", "trigger": "cross", "applies_to": "anyone",
         "severity": "noteworthy"},
        None,
    ),
    (
        "Alert me if anyone stays on the porch for more than 2 minutes",
        {"target_id": "porch", "trigger": "dwell", "min_dwell_s": 120, "active_start": None,
         "active_end": None},
        {"target": "porch", "trigger": "dwell", "applies_to": "anyone", "min_dwell_s": 120},
        None,
    ),
    (
        "Tell me if anyone goes in the backyard between 11 PM and 5 AM",
        {"target_id": "backyard", "trigger": "enter", "active_start": "23:00",
         "active_end": "05:00"},
        {"target": "backyard", "trigger": "enter", "applies_to": "anyone",
         "active": ("23:00", "05:00")},
        None,
    ),
]  # fmt: skip


@pytest.mark.parametrize(("text", "answer", "expected", "named"), REFERENCE_SET)
def test_reference_set_compiles_to_expected_json(catalog, text, answer, expected, named):
    draft = compile_rule(FakeClient(_rule_answer(**answer)), text, catalog)
    assert isinstance(draft, RuleDraft), getattr(draft, "reason", draft)
    rule = draft.rule
    assert rule.target.id == expected["target"]
    assert rule.trigger == expected["trigger"]
    assert rule.applies_to == expected["applies_to"]
    assert rule.severity == expected.get("severity", "needs_attention")
    if "min_dwell_s" in expected:
        assert rule.min_dwell_s == expected["min_dwell_s"]
    if "active" in expected:
        assert rule.active == ActiveWindow(start=expected["active"][0], end=expected["active"][1])
    assert draft.basis_note == BASIS_NOTES[rule.applies_to]
    if named:
        assert draft.notice == named_person_notice([named])
        assert draft.notice in draft.limits
    else:
        assert draft.notice is None
    # No compiled rule ever names a person (FR-021).
    assert rule_person_terms(rule, catalog) == []
    if named:
        assert named.lower() not in rule.model_dump_json().lower()


def test_reference_set_has_at_least_three_role_phrasings():
    roles = [e for _, _, e, _ in REFERENCE_SET if e["applies_to"] != "anyone"]
    assert len(REFERENCE_SET) == 10
    assert len(roles) >= 3
    assert {e["applies_to"] for e in roles} == {"non_household", "external_visitor_only"}


def test_named_person_notice_is_the_spec_text():
    assert named_person_notice(["Sam"]) == SAM_NOTICE


@pytest.mark.parametrize(
    ("text", "applies_to", "names"),
    [
        ("anyone except family", "non_household", []),
        ("anyone except for my family", "non_household", []),
        ("anyone except us", "non_household", []),
        ("anyone except me", "non_household", []),
        ("anyone who is not the household", "non_household", []),
        ("unless it's one of us", "non_household", []),
        ("strangers only", "external_visitor_only", []),
        ("only strangers", "external_visitor_only", []),
        ("not guests or deliveries", "external_visitor_only", []),
        ("anyone except family, and not deliveries", "external_visitor_only", []),
        ("anyone except Sam", "non_household", ["Sam"]),
        ("unless it's Sam or Alex", "non_household", ["Sam", "Alex"]),
        ("anyone except the neighbour", "non_household", ["the neighbour"]),
        ("anyone at the gate after 10 PM", None, []),
        ("anyone except at night on Monday", None, []),
    ],
)
def test_classify_role_phrasing(text, applies_to, names):
    result = classify_role_phrasing(text)
    assert result.applies_to == applies_to
    assert result.names == names


def test_lowercase_transcript_name_needs_the_model_flag():
    assert classify_role_phrasing("anyone except sam").applies_to is None
    flagged = classify_role_phrasing("anyone except sam", model_named=True)
    assert flagged.applies_to == "non_household"
    assert flagged.names == ["Sam"]


def test_named_person_never_reaches_the_rule_even_from_a_transcript(catalog):
    fake = FakeClient(
        _rule_answer(
            name="sam can open the gate",
            applies_to="non_household",
            named_person=True,
            active_start=None,
            active_end=None,
        )
    )
    draft = compile_rule(fake, "tell me if anyone except sam opens the side gate", catalog)
    assert isinstance(draft, RuleDraft)
    assert draft.rule.applies_to == "non_household"
    assert "sam" not in draft.rule.model_dump_json().lower()
    assert draft.notice is not None
    assert "Sam is exempt only in those cases" in draft.notice


def test_model_flag_without_a_name_in_text_gets_a_generic_notice(catalog):
    fake = FakeClient(_rule_answer(applies_to="non_household", named_person=True))
    draft = compile_rule(fake, "tell me if anyone but my friend opens the side gate", catalog)
    assert isinstance(draft, RuleDraft)
    assert draft.rule.applies_to == "non_household"
    assert draft.notice is not None
    assert draft.notice.startswith("Vigil can't recognise individuals.")


def test_model_role_without_any_exception_phrase_is_ignored(catalog):
    fake = FakeClient(_rule_answer(applies_to="external_visitor_only"))
    draft = compile_rule(fake, "tell me if anyone opens the side gate after 10 PM", catalog)
    assert isinstance(draft, RuleDraft)
    assert draft.rule.applies_to == "anyone"
    assert draft.identity_exception is False


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("Side gate except Sam", ["Sam"]),
        ("Side gate, not family", ["family"]),
        ("Mum's gate", ["Mum's"]),
        ("Side gate after dark", []),
        ("Side gate on Monday after 10 PM", []),
        ("porch (Front entrance) dwell", []),
    ],
)
def test_rule_person_terms(catalog, name, bad):
    rule = Rule(
        id="r1",
        name=name,
        target=RuleTarget(kind="protected_object", id="po_side_gate"),
        trigger="touch",
        severity="needs_attention",
    )
    assert rule_person_terms(rule, catalog, names=["Sam"]) == bad


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


def test_rule_person_terms_ignores_hash_ids_but_catches_named_ids(catalog):
    base = dict(
        name="Side gate touch",
        target=RuleTarget(kind="protected_object", id="po_side_gate"),
        trigger="touch",
        severity="needs_attention",
    )
    assert rule_person_terms(Rule(id="r_dad1f0e2", **base), catalog) == []
    assert rule_person_terms(Rule(id="r_sam_gate", **base), catalog, names=["Sam"]) == ["sam"]


# --- F9: the rule name is always built by code (FR-021) ----------------------------------


def test_rule_name_is_code_built_even_for_a_lowercase_name(catalog):
    """'except when sam is home': code reads no name after the cue, the model flags a named
    person and puts 'sam' in its free-text name. No compiled rule ever names a person."""
    fake = FakeClient(
        _rule_answer(
            name="side gate touch unless sam is home",
            active_start="17:30",
            active_end="06:00",
            applies_to="non_household",
            named_person=True,
        )
    )
    text = "alert me when the side gate is touched at night, except when sam is home"
    draft = compile_rule(fake, text, catalog)
    assert isinstance(draft, RuleDraft), getattr(draft, "reason", draft)
    assert "sam" not in draft.rule.model_dump_json().lower()
    assert draft.rule.name == "Side gate touch, 17:30-06:00"
    assert draft.notice is not None


@pytest.mark.parametrize(
    "model_name", ["Side gate after dark", "anything at all", "Gate rule for the kids"]
)
def test_rule_name_never_keeps_model_free_text(catalog, model_name):
    draft = compile_rule(
        FakeClient(_rule_answer(name=model_name, active_start=None, active_end=None)),
        "tell me if anyone opens the side gate",
        catalog,
    )
    assert isinstance(draft, RuleDraft)
    assert draft.rule.name == "Side gate touch"


# --- removed on a protected object can never fire (fail-open) ----------------------------


@pytest.fixture
def bike(po_side_gate):
    return po_side_gate.model_copy(update={"id": "po_bike", "label": "bike"})


def _bike_answer() -> dict:
    return _rule_answer(
        name="Bike taken", target_id="po_bike", trigger="removed", active_start=None,
        active_end=None,
    )  # fmt: skip


def test_removed_on_protected_object_without_a_watch_is_rejected(sample_config, bike):
    """'Alert if my bike is taken': removed events target watches only, so a rule on the
    protected object would never fire. It is not accepted as a rule."""
    catalog = TargetCatalog.from_config(sample_config, [bike])
    out = compile_rule(FakeClient(_bike_answer()), "Alert if my bike is taken", catalog)
    assert isinstance(out, ClarifyingQuestion)
    assert "watch" in out.reason


def test_removed_on_protected_object_maps_to_its_watch(sample_config, bike):
    from vigil.models import Watch

    watch = Watch(
        id="w_bike", camera_id=bike.camera_id, phrase="bike", origin="owner", status="watching"
    )
    catalog = TargetCatalog.from_config(sample_config, [bike], [watch])
    draft = compile_rule(FakeClient(_bike_answer()), "Alert if my bike is taken", catalog)
    assert isinstance(draft, RuleDraft), getattr(draft, "reason", draft)
    assert draft.rule.target == RuleTarget(kind="watch", id="w_bike")
    assert draft.rule.trigger == "removed"
    assert draft.rule.name == "Bike removal"
    assert any("watch" in note for note in draft.limits)


# --- triage: one forced-escalation rule, shared with vigil.reasoning.triage (FR-013) -------


def test_spark_triage_uses_the_reasoning_forced_escalation():
    from vigil.meta import spark
    from vigil.reasoning import triage as reasoning_triage

    assert spark.forced_escalation is reasoning_triage.forced_escalation


def test_spark_triage_case2_household_touch_is_not_forced():
    """Spec 9.4 case 2: a household touch every in-force rule excludes does not force
    escalation, so Spark decides."""
    from vigil.models import Event, Visit
    from vigil.reasoning.rules import RuleOutcome
    from vigil.reasoning.triage import summarize

    touch = Event(
        id="e1", visit_id="v1", camera_id="side_left", track_id="t1", type="touch", t0=1.0,
        t1=2.0, target="po_side_gate", clip_t0=0.0, clip_t1=3.0, actor_role="household_insider",
    )  # fmt: skip
    visit = Visit(id="v1", t0=0.0, t1=3.0, event_ids=["e1"])
    summary = summarize(visit, [touch], [], RuleOutcome(scoped_out=["e1"]))
    assert summary.protected_touched is False
    fake = FakeClient({"escalate": False, "reason": "routine"})
    decision = triage(fake, summary)
    assert decision.source == "spark"
    assert len(fake.calls) == 1
