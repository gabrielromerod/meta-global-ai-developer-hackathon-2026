"""Muse Spark: appearance notes, rule compile, triage fallback (FR-009, FR-021, FR-013).

Request builders return a Responses API body *without* ``model`` (MetaClient adds it) and
with structured output in ``text.format`` (``type: json_schema``, ``name``, ``schema``,
``strict``), per https://dev.meta.ai/docs/api-reference/responses/schemas. Every schema
follows the strict subset: closed objects, every property required, nullable via
``["string", "null"]``. Parsers re-validate in code, so a model that ignores the schema is
still caught.

Appearance schema (NFR-003): ``tag`` is an enum of the burned-in tags, colours come from
``vigil.models.COLORS``, and there are no face, age, gender, skin or ethnicity fields.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel, Field, ValidationError, model_validator

from vigil.meta.budget import SPARK
from vigil.meta.client import extract_text, load_json_text
from vigil.meta.prompts import load_prompt
from vigil.models import (
    COLORS,
    ActiveWindow,
    Appearance,
    Config,
    ProtectedObject,
    Rule,
    RuleTarget,
    RuleTrigger,
    Severity,
    TargetKind,
    TriageDecision,
    VehicleBody,
    VisitSummary,
    Watch,
)

# ---------------------------------------------------------------------------
# Appearance notes (FR-009)
# ---------------------------------------------------------------------------

CARRY_ITEMS: tuple[str, ...] = (
    "backpack", "bag", "handbag", "box", "package", "envelope", "bottle", "umbrella",
    "phone", "bicycle", "scooter", "stroller", "cart", "ladder", "tool", "leash", "other",
)  # fmt: skip
"""Fixed list of carried items; free text is not allowed (it could carry personal traits)."""

APPEARANCE_CLASSES = ("person", "vehicle", "object")
TRACK_FIELDS = (
    "tag", "class", "upper_color", "lower_color", "carrying", "vehicle_color", "vehicle_body",
)  # fmt: skip


class AppearanceSchemaError(ValueError):
    """Spark's appearance JSON broke the schema (unknown tag, extra field, bad value)."""


class SparkAnswerError(ValueError):
    """Spark's answer could not be parsed into the requested JSON."""


def _nullable_enum(values: list[Any] | tuple[Any, ...]) -> dict:
    return {"type": ["string", "null"], "enum": [*values, None]}


def appearance_schema(tags: list[str]) -> dict:
    """Strict JSON schema for appearance notes; ``tag`` is an enum of ``tags``."""
    if not tags:
        raise ValueError("appearance notes need at least one track tag")
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": list(TRACK_FIELDS),
        "properties": {
            "tag": {"type": "string", "enum": list(dict.fromkeys(tags))},
            "class": {"type": "string", "enum": list(APPEARANCE_CLASSES)},
            "upper_color": _nullable_enum(COLORS),
            "lower_color": _nullable_enum(COLORS),
            "carrying": {"type": "array", "items": {"type": "string", "enum": list(CARRY_ITEMS)}},
            "vehicle_color": _nullable_enum(COLORS),
            "vehicle_body": _nullable_enum(get_args(VehicleBody)),
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["tracks"],
        "properties": {"tracks": {"type": "array", "items": item}},
    }


def _json_format(name: str, schema: dict, strict: bool = True) -> dict:
    return {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": strict}}


def build_appearance_request(file_id: str, tags: list[str]) -> dict:
    prompt = load_prompt("appearance_notes")
    return {
        "instructions": prompt.text,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_video", "file_id": file_id},
                    {
                        "type": "input_text",
                        "text": "Tags drawn in this clip: "
                        + ", ".join(tags)
                        + ". Return one entry per tag you can see.",
                    },
                ],
            }
        ],
        "text": _json_format("appearance_notes", appearance_schema(tags)),
        "max_output_tokens": 300 + 150 * len(tags),
    }


def parse_appearance(text: str, tags: list[str]) -> dict[str, Appearance]:
    """Validate Spark's JSON against the schema in code and return notes keyed by tag."""
    try:
        data = load_json_text(text)
    except ValueError:
        raise AppearanceSchemaError("appearance answer is not JSON") from None
    if not isinstance(data, dict) or set(data) != {"tracks"}:
        raise AppearanceSchemaError("appearance answer must be an object with only 'tracks'")
    if not isinstance(data["tracks"], list):
        raise AppearanceSchemaError("'tracks' must be a list")
    allowed = set(tags)
    out: dict[str, Appearance] = {}
    for i, item in enumerate(data["tracks"]):
        if not isinstance(item, dict):
            raise AppearanceSchemaError(f"track {i} is not an object")
        keys = set(item)
        if keys != set(TRACK_FIELDS):
            extra = sorted(keys - set(TRACK_FIELDS))
            missing = sorted(set(TRACK_FIELDS) - keys)
            raise AppearanceSchemaError(f"track {i}: extra fields {extra}, missing {missing}")
        tag = item["tag"]
        if tag not in allowed:
            raise AppearanceSchemaError(
                f"track {i}: unknown tag {tag!r} (allowed {sorted(allowed)})"
            )
        if tag in out:
            raise AppearanceSchemaError(f"track {i}: duplicate tag {tag!r}")
        if item["class"] not in APPEARANCE_CLASSES:
            raise AppearanceSchemaError(f"track {i}: class {item['class']!r} not allowed")
        carrying = item["carrying"]
        if not isinstance(carrying, list) or any(c not in CARRY_ITEMS for c in carrying):
            raise AppearanceSchemaError(f"track {i}: carrying {carrying!r} not in the fixed list")
        try:
            out[tag] = Appearance.model_validate(item)
        except ValidationError as exc:
            first = exc.errors()[0]
            raise AppearanceSchemaError(f"track {i}: {first['loc']}: {first['msg']}") from None
    return out


def appearance_notes(
    c, tagged_clip: Path, tags: list[str], visit_id: str | None = None
) -> dict[str, Appearance]:
    """Upload the tagged clip once, ask Spark for notes, and validate them (FR-009)."""
    file_id = c.upload(Path(tagged_clip))
    body = build_appearance_request(file_id, tags)
    resp = c.responses(
        SPARK, body, purpose="appearance_notes", visit_id=visit_id, feature="appearance"
    )
    return parse_appearance(extract_text(resp), tags)


# ---------------------------------------------------------------------------
# Rule compile (FR-021)
# ---------------------------------------------------------------------------

BASE_LIMIT = "Vigil never identifies people, so this rule applies to anyone."
IDENTITY_LIMIT = (
    "You asked to treat some people differently (for example family). Vigil cannot tell "
    "who someone is, so this rule will apply to everyone, family included."
)
IDENTITY_RE = re.compile(
    r"\b(except|unless|other than|but not|apart from|excluding|besides|strangers?|"
    r"unknown (?:people|persons?)|people i don'?t know|not (?:me|us|my \w+))\b",
    re.I,
)
_TRIGGER_KINDS: dict[str, set[str]] = {
    "touch": {"protected_object"},
    "cross": {"line"},
    "enter": {"zone"},
    "dwell": {"zone"},
    "removed": {"watch", "protected_object"},
}


class CatalogEntry(BaseModel):
    kind: TargetKind
    id: str
    label: str
    camera_id: str | None = None


class TargetCatalog(BaseModel):
    """The only targets a compiled rule may use: existing objects, zones, lines, watches.

    Module-private until a shared ``TargetCatalog`` exists in vigil.models (spec 9.5).
    """

    entries: list[CatalogEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> TargetCatalog:
        ids = [e.id for e in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("catalog target ids must be unique")
        return self

    def ids(self) -> list[str]:
        return [e.id for e in self.entries]

    @classmethod
    def coerce(cls, obj: Any) -> TargetCatalog:
        """Accept a TargetCatalog, ``{"entries": [...]}``, a list of entry dicts, or a
        mapping of kind to ids / entry dicts (``{"zone": ["porch"], ...}``)."""
        if isinstance(obj, cls):
            return obj
        if isinstance(obj, list):
            return cls(entries=[CatalogEntry.model_validate(e) for e in obj])
        if isinstance(obj, dict):
            if "entries" in obj:
                return cls.model_validate(obj)
            entries: list[CatalogEntry] = []
            for kind, items in obj.items():
                for item in items or []:
                    if isinstance(item, str):
                        entries.append(CatalogEntry(kind=kind, id=item, label=item))
                    else:
                        entries.append(CatalogEntry.model_validate({"kind": kind, **item}))
            return cls(entries=entries)
        raise TypeError(f"cannot build a TargetCatalog from {type(obj).__name__}")

    def get(self, target_id: str) -> CatalogEntry:
        for e in self.entries:
            if e.id == target_id:
                return e
        raise KeyError(target_id)

    @classmethod
    def from_config(
        cls,
        cfg: Config,
        protected: list[ProtectedObject] | tuple[ProtectedObject, ...] = (),
        watches: list[Watch] | tuple[Watch, ...] = (),
    ) -> TargetCatalog:
        entries: dict[str, CatalogEntry] = {}

        def add(entry: CatalogEntry) -> None:
            entries.setdefault(entry.id, entry)

        for po in protected:
            add(
                CatalogEntry(
                    kind="protected_object", id=po.id, label=po.label, camera_id=po.camera_id
                )
            )
        for cam in cfg.cameras:
            for zone in cam.zones:
                add(
                    CatalogEntry(
                        kind="zone", id=zone, label=f"{zone} ({cam.name})", camera_id=cam.id
                    )
                )
            for line in cam.lines:
                add(
                    CatalogEntry(
                        kind="line", id=line, label=f"{line} ({cam.name})", camera_id=cam.id
                    )
                )
        for w in watches:
            if w.status == "watching":
                add(CatalogEntry(kind="watch", id=w.id, label=w.phrase, camera_id=w.camera_id))
        return cls(entries=list(entries.values()))


class RuleDraft(BaseModel):
    """A compiled rule awaiting the owner's confirmation, with what Vigil cannot do."""

    rule: Rule
    limits: list[str]
    identity_exception: bool = False
    source_text: str
    call_id: str | None = None


class ClarifyingQuestion(BaseModel):
    """Returned instead of a rule when the target cannot be resolved (FR-021)."""

    question: str
    options: list[str] = Field(default_factory=list)
    reason: str
    source_text: str
    call_id: str | None = None


def rule_schema(catalog: TargetCatalog) -> dict:
    ids = catalog.ids()
    props: dict[str, dict] = {
        "status": {"type": "string", "enum": ["rule", "clarify"]},
        "question": {"type": ["string", "null"]},
        "name": {"type": "string"},
        "target_id": {"type": ["string", "null"], "enum": [*ids, None]},
        "trigger": {"type": "string", "enum": list(get_args(RuleTrigger))},
        "min_dwell_s": {"type": ["number", "null"]},
        "active_start": {"type": ["string", "null"]},
        "active_end": {"type": ["string", "null"]},
        "severity": {"type": "string", "enum": list(get_args(Severity))},
        "identity_exception": {"type": "boolean"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(props),
        "properties": props,
    }


def build_rule_request(text: str, catalog: TargetCatalog) -> dict:
    prompt = load_prompt("rule_compile")
    targets = [e.model_dump(exclude_none=True) for e in catalog.entries]
    user = f"Targets that exist:\n{json.dumps(targets)}\n\nOwner request:\n{text.strip()}"
    return {
        "instructions": prompt.text,
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": user}]}
        ],
        "text": _json_format("rule_draft", rule_schema(catalog)),
        "max_output_tokens": 400,
    }


def _rule_id(text: str) -> str:
    return "r_" + hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:8]


def parse_rule(
    answer: str,
    text: str,
    catalog: TargetCatalog,
    *,
    rule_id: str | None = None,
    call_id: str | None = None,
) -> RuleDraft | ClarifyingQuestion:
    """Turn Spark's JSON into a draft rule, or a clarifying question when it cannot."""
    options = catalog.ids()

    def ask(reason: str, question: str | None = None) -> ClarifyingQuestion:
        labels = ", ".join(e.label for e in catalog.entries[:8])
        return ClarifyingQuestion(
            question=question or f"Which of these do you mean: {labels}?",
            options=options,
            reason=reason,
            source_text=text,
            call_id=call_id,
        )

    try:
        data = load_json_text(answer)
    except ValueError:
        return ask("the rule compiler's answer was not JSON")
    if not isinstance(data, dict):
        return ask("the rule compiler's answer was not an object")
    question = data.get("question") if isinstance(data.get("question"), str) else None
    if data.get("status") != "rule":
        return ask("the target could not be resolved", question)
    target_id = data.get("target_id")
    if not isinstance(target_id, str) or target_id not in options:
        return ask(f"target {target_id!r} is not an existing object, zone, line or watch")
    entry = catalog.get(target_id)
    active = None
    start, end = data.get("active_start"), data.get("active_end")
    try:
        if start or end:
            active = ActiveWindow(start=start or "00:00", end=end or "23:59")
        rule = Rule(
            id=rule_id or _rule_id(text),
            name=str(data.get("name") or f"Rule on {entry.label}")[:80],
            target=RuleTarget(kind=entry.kind, id=entry.id),
            trigger=data.get("trigger"),
            min_dwell_s=data.get("min_dwell_s"),
            active=active,
            severity=data.get("severity") or "needs_attention",
            applies_to="anyone",
            state="draft",
        )
    except (ValidationError, ValueError) as exc:
        return ask(f"the rule was incomplete: {type(exc).__name__}", question)

    identity = bool(data.get("identity_exception")) or bool(IDENTITY_RE.search(text))
    limits = [BASE_LIMIT]
    if identity:
        limits.append(IDENTITY_LIMIT)
    if entry.kind not in _TRIGGER_KINDS.get(rule.trigger, {entry.kind}):
        limits.append(
            f"'{rule.trigger}' is normally used with a "
            f"{' or '.join(sorted(_TRIGGER_KINDS[rule.trigger]))}, but {entry.label} is a "
            f"{entry.kind.replace('_', ' ')}; check the target before confirming."
        )
    return RuleDraft(
        rule=rule, limits=limits, identity_exception=identity, source_text=text, call_id=call_id
    )


def compile_rule(
    c, text: str, catalog: TargetCatalog | dict | list, rule_id: str | None = None
) -> RuleDraft | ClarifyingQuestion:
    """Compile typed (or transcribed) text into a draft rule limited to the catalog (FR-021)."""
    catalog = TargetCatalog.coerce(catalog)
    if not catalog.entries:
        return ClarifyingQuestion(
            question="Protect an object or define a zone first, then describe the rule.",
            reason="no targets exist yet",
            source_text=text,
        )
    resp = c.responses(
        SPARK, build_rule_request(text, catalog), purpose="rule_compile", feature="rule_compile"
    )
    call_id = (resp.get("_vigil") or {}).get("call_id")
    return parse_rule(extract_text(resp), text, catalog, rule_id=rule_id, call_id=call_id)


# ---------------------------------------------------------------------------
# Triage fallback (FR-013; Spark when Glimmer is unavailable, FR-028)
# ---------------------------------------------------------------------------

TRIAGE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["escalate", "reason"],
    "properties": {"escalate": {"type": "boolean"}, "reason": {"type": "string"}},
}


def forced_escalation(summary: VisitSummary) -> TriageDecision | None:
    """Code forces escalation on a rule hit, protected touch or unresolved gap (FR-013)."""
    reasons = [
        label
        for flag, label in (
            (summary.rule_fired, "a rule fired"),
            (summary.protected_touched, "a protected object was touched"),
            (summary.unresolved_gap, "a gap is unresolved"),
        )
        if flag
    ]
    if not reasons:
        return None
    return TriageDecision(escalate=True, forced=True, reason="; ".join(reasons), source="code")


def build_triage_request(summary: VisitSummary) -> dict:
    prompt = load_prompt("triage")
    return {
        "instructions": prompt.text,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": summary.model_dump_json()}],
            }
        ],
        "text": _json_format("triage", TRIAGE_SCHEMA),
        "max_output_tokens": 200,
    }


def parse_triage(answer: str) -> TriageDecision:
    try:
        data = load_json_text(answer)
        escalate, reason = data["escalate"], data["reason"]
    except (ValueError, TypeError, KeyError):
        raise SparkAnswerError("triage answer is not the requested JSON") from None
    if not isinstance(escalate, bool) or not isinstance(reason, str):
        raise SparkAnswerError("triage answer has the wrong types")
    return TriageDecision(escalate=escalate, forced=False, reason=reason[:200], source="spark")


def triage(c, summary: VisitSummary) -> TriageDecision:
    """Forced cases are decided by code with no call; otherwise Spark decides."""
    forced = forced_escalation(summary)
    if forced is not None:
        return forced
    resp = c.responses(
        SPARK,
        build_triage_request(summary),
        purpose="triage",
        visit_id=summary.visit_id,
        feature="triage",
    )
    return parse_triage(extract_text(resp))
