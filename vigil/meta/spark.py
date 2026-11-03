"""Muse Spark: appearance notes, rule compile, triage fallback (FR-009, FR-021, FR-013).

Request builders return a Responses API body *without* ``model`` (MetaClient adds it) and
with structured output in ``text.format`` (``type: json_schema``, ``name``, ``schema``,
``strict``), per https://dev.meta.ai/docs/api-reference/responses/schemas. Every schema
follows the strict subset: closed objects, every property required, nullable via
``["string", "null"]``. Parsers re-validate in code, so a model that ignores the schema is
still caught.

Appearance schema (NFR-003): ``tag`` is an enum of the burned-in tags, colours come from
``vigil.models.COLORS``, and there are no face, age, gender, skin or ethnicity fields.

Rule compile (FR-021): identity phrases map to roles, never to people. Code reads the
owner's words (:func:`classify_role_phrasing`) and its reading wins over the model's
``applies_to``; a named person ("except Sam") gives ``non_household`` plus the spec notice,
and no compiled rule names a person: the rule's name is always built by code from the
target, trigger and window (the model's free-text name is ignored), then checked with
:func:`rule_person_terms`. A ``removed`` rule must target a watch (removal events refer to
watches only); a protected object is mapped to its watch or the draft is refused.
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
    AppliesTo,
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
from vigil.reasoning.triage import forced_escalation  # the one FR-013 forced rule

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

HOUSEHOLD_BASIS = (
    "Vigil treats someone as household only when it saw them come out of the house's own "
    "doors, or when a household member checked in on the app just before coming into view. "
    "Household members arriving from the street without checking in, and anyone Vigil loses "
    "track of, count as non-household and can trigger this rule. Vigil places people by where "
    "they came from; it does not identify anyone and creates no face, voice or body templates."
)
"""The basis the draft card states for a role-scoped rule (FR-021, UC-03), verbatim."""

NO_TEMPLATES = (
    "Vigil places people by where they came from; it does not identify anyone and creates no "
    "face, voice or body templates."
)

BASIS_NOTES: dict[str, str] = {
    "anyone": "Applies to everyone, household members included. " + NO_TEMPLATES,
    "non_household": "Applies to everyone except household members. " + HOUSEHOLD_BASIS,
    "external_visitor_only": (
        "Applies only to people arriving from outside the property, not to household members "
        "or expected visitors. Vigil treats someone as an expected visitor only when they "
        "arrive from the street, the driveway entry or the side alley during an expected guest "
        "or delivery window you set, on a camera that window covers. " + HOUSEHOLD_BASIS
    ),
}
"""Draft-card basis note per ``applies_to`` (spec 9.6 ``POST /api/rules/compile``)."""

BASE_LIMIT = "Vigil does not identify anyone and creates no face, voice or body templates."
GENERIC_NAMED = "the person you named"


def named_person_notice(names: list[str]) -> str:
    """FR-021 notice for "except Sam": the name stays in the notice, never in the rule."""
    who = " and ".join(names) if names else GENERIC_NAMED
    verb = "are" if len(names) > 1 else "is"
    return (
        "Vigil can't recognise individuals. It treats someone as household only if they came "
        f"out of the house's own doors or checked in on the app, so {who} {verb} exempt only "
        "in those cases."
    )


# -- role phrasing (code decides; the model's answer is only a hint) -----------------------


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_CUE_RE = re.compile(
    r"\b(?:except(?:\s+for)?|unless(?:\s+(?:it['\u2019]?s|it\s+is|they['\u2019]?re|they\s+are))?|"
    r"other\s+than|but(?:\s+not)?|apart\s+from|excluding|besides|not)\b",
    re.I,
)
IDENTITY_RE = re.compile(
    r"\b(except|unless|other than|but not|apart from|excluding|besides|strangers?|"
    r"not (?:the |any )?(?:household|family|us|me|guests?|visitors?|deliver(?:y|ies)|couriers?)|"
    r"people (?:i|we) don['\u2019]?t know)\b",
    re.I,
)
_EXTERNAL_ONLY_RE = re.compile(
    r"\bstrangers?\b|\bpeople\s+(?:i|we)\s+don['\u2019]?t\s+know\b|\boutsiders?\b|"
    r"\b(?:not|except(?:\s+for)?|excluding|but\s+not|other\s+than|apart\s+from|besides)\s+"
    r"(?:the\s+|any\s+|our\s+|my\s+)?(?:guests?|visitors?|deliver(?:y|ies)|couriers?|"
    r"delivery\s+(?:people|drivers?))\b",
    re.I,
)
_HOUSEHOLD_WORDS = _words(
    "family families household households us me we myself ourselves residents resident "
    "wife husband partner kids kid children child son sons daughter daughters mum mom mother "
    "dad father parents parent grandma grandpa grandmother grandfather sister brother "
    "siblings roommate roommates housemates flatmates"
)
_HOUSEHOLD_PHRASES = re.compile(
    r"^(?:one\s+of\s+us|people\s+who\s+live\s+here|anyone\s+who\s+lives\s+here|"
    r"those\s+who\s+live\s+here)\b",
    re.I,
)
_SPECIFIC_PEOPLE = _words(
    "neighbour neighbor neighbours neighbors friend friends gardener cleaner nanny "
    "babysitter landlord plumber"
)
_SKIP = _words("for the my our your a an of")
_FUNCTION_WORDS = _words(
    "at after before in on when if during between from to while until by around near "
    "anyone someone anybody somebody people person everyone everybody they them it its "
    "it's is are was be do does did please and or but just only also then there here "
    "this that these those night nights day days daytime weekends weekend weekdays weekday "
    "morning mornings evening evenings afternoon today tonight tomorrow dark midnight noon "
    "alert tell let notify warn note make send open opens touch touches enter enters go "
    "goes come comes cross crosses stay stays leave leaves take takes"
)
_CALENDAR = _words(
    "monday tuesday wednesday thursday friday saturday sunday mondays tuesdays wednesdays "
    "thursdays fridays saturdays sundays january february march april may june july august "
    "september october november december am pm i"
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*|,")


class RolePhrasing(BaseModel):
    """What code reads from the owner's words: a role scope, never an identity (FR-021)."""

    applies_to: AppliesTo | None = None
    names: list[str] = Field(default_factory=list)
    """Named people or specific non-household people. Used only for the notice."""
    named: bool = False


def _after_cue(text: str) -> list[tuple[str, int]]:
    """Token runs that follow each exception cue: [(token, cue_index)]."""
    out: list[tuple[str, int]] = []
    for i, m in enumerate(_CUE_RE.finditer(text)):
        rest = text[m.end() :]
        if _HOUSEHOLD_PHRASES.match(rest.strip()):
            out.append(("us", i))
            continue
        for tok in _WORD_RE.findall(rest)[:8]:
            out.append((tok, i))
    return out


def classify_role_phrasing(text: str, model_named: bool = False) -> RolePhrasing:
    """Map identity phrases to a role scope (FR-021); names go only to the notice.

    "anyone except family / us / the household" -> ``non_household``; "strangers only",
    "not guests or deliveries" -> ``external_visitor_only`` (it wins when both appear, since
    it excludes more); "except Sam" -> ``non_household`` with Sam named for the notice. A
    lower-case unknown word after a cue (a transcript's "except sam") counts as a name only
    when the model also flagged a named person.
    """
    if _EXTERNAL_ONLY_RE.search(text):
        return RolePhrasing(applies_to="external_visitor_only")
    household = False
    names: list[str] = []
    runs: dict[int, list[str]] = {}
    for tok, cue in _after_cue(text):
        runs.setdefault(cue, []).append(tok)
    for tokens in runs.values():
        expect_name = True
        owner = "the"
        for tok in tokens:
            low = tok.lower().strip("'’")
            if tok == ",":
                break
            if low in _SKIP and expect_name:
                owner = "your" if low in ("my", "our") else owner
                continue
            if low in ("and", "or"):
                expect_name = True
                continue
            if not expect_name:
                break
            if low in _HOUSEHOLD_WORDS:
                household = True
                expect_name = False
            elif low in _SPECIFIC_PEOPLE:
                names.append(f"{owner} {low}")
                expect_name = False
            elif low in _FUNCTION_WORDS or low in _CALENDAR:
                break
            elif tok[0].isupper() or model_named:
                names.append(tok[0].upper() + tok[1:])
                expect_name = False
            else:
                break
    names = list(dict.fromkeys(names))
    if names:
        return RolePhrasing(applies_to="non_household", names=names, named=True)
    if household:
        return RolePhrasing(applies_to="non_household")
    return RolePhrasing()


# -- no compiled rule ever names a person (FR-021) ------------------------------------------

PERSON_WORDS = frozenset(
    _HOUSEHOLD_WORDS
    | _SPECIFIC_PEOPLE
    | _words(
        "owner owners guest guests visitor visitors courier couriers delivery deliveries "
        "stranger strangers neighbour neighbor mum's mom's dad's"
    )
)
"""Relationship and role words a rule's name must not carry (cf. validator check 7)."""


def rule_person_terms(
    rule: Rule, catalog: TargetCatalog | None = None, names: list[str] | tuple[str, ...] = ()
) -> list[str]:
    """Tokens in a rule's name (or id) that could name a person; [] when the rule is clean.

    Flags in the name: any of ``names``; relationship or role words; and capitalised tokens
    after the first that are not words of a catalog label or id, a weekday, a month, or
    AM/PM. The id (a code-made hash unless the caller gives one) is checked for ``names``.
    """
    allowed: set[str] = set(_CALENDAR)
    for e in catalog.entries if catalog else ():
        allowed.update(w.lower() for w in _WORD_RE.findall(f"{e.label} {e.id}".replace("_", " ")))
    named = {n.lower() for name in names for n in _WORD_RE.findall(name)} - _SKIP
    bad: list[str] = []
    tokens = [t for t in _WORD_RE.findall(rule.name.replace("_", " ")) if t != ","]
    for i, tok in enumerate(tokens):
        low = tok.lower()
        base = low.removesuffix("'s").removesuffix("’s")
        if (
            low in named
            or base in named
            or low in PERSON_WORDS
            or base in PERSON_WORDS
            or (i > 0 and tok[0].isupper() and low not in allowed and base not in allowed)
        ):
            bad.append(tok)
    id_tokens = {t.lower() for t in _WORD_RE.findall(rule.id.replace("_", " "))}
    bad += [n for n in sorted(named) if n in id_tokens]
    return list(dict.fromkeys(bad))


_TRIGGER_NOUN = {
    "touch": "touch",
    "cross": "crossing",
    "enter": "entry",
    "dwell": "stay",
    "removed": "removal",
}


def _code_rule_name(entry: CatalogEntry, rule: Rule) -> str:
    """The rule's name, always built by code from the target's label, the trigger and the
    active window. The model's free-text name is never kept (FR-021): a lower-case name in a
    transcript ("unless sam is home") cannot be told from an ordinary word."""
    label = entry.label[:1].upper() + entry.label[1:]
    name = f"{label} {_TRIGGER_NOUN.get(rule.trigger, rule.trigger)}"
    if rule.active is not None:
        name += f", {rule.active.start}-{rule.active.end}"
    return name[:80]


# -- catalog -----------------------------------------------------------------------------

_TRIGGER_KINDS: dict[str, set[str]] = {
    "touch": {"protected_object"},
    "cross": {"line"},
    "enter": {"zone"},
    "dwell": {"zone"},
    "removed": {"watch"},
}
"""Target kinds each trigger's events can refer to. ``removed`` events target watches only
(vigil.perception.events), so a removal rule on anything else could never fire."""


def _norm_label(text: str) -> str:
    words = [w for w in _WORD_RE.findall(text.lower()) if w != "," and w not in _SKIP]
    return " ".join(words)


def _watch_for_object(entry: CatalogEntry, catalog: TargetCatalog) -> CatalogEntry | None:
    """The one active watch on the protected object's camera whose phrase is its label."""
    label = _norm_label(entry.label)
    found = [
        e
        for e in catalog.entries
        if e.kind == "watch"
        and _norm_label(e.label) == label
        and (entry.camera_id is None or e.camera_id in (None, entry.camera_id))
    ]
    return found[0] if len(found) == 1 else None


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
    """A compiled rule awaiting the owner's confirmation (FR-021, spec 9.6).

    ``basis_note`` is what the draft card says about whom the rule applies to; ``notice`` is
    the named-person notice; ``limits`` lists what Vigil cannot do (the notice included).
    """

    rule: Rule
    basis_note: str
    limits: list[str]
    notice: str | None = None
    identity_exception: bool = False
    """True when the owner's words scoped the rule by role (any applies_to but anyone)."""
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
        "applies_to": {"type": "string", "enum": list(get_args(AppliesTo))},
        "named_person": {"type": "boolean"},
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


def resolve_applies_to(text: str, model_value: Any, model_named: bool) -> RolePhrasing:
    """Code's reading of the words wins; the model's role is used only when the words hold an
    exception cue that code could not map, and never without one."""
    role = classify_role_phrasing(text, model_named=model_named)
    if role.applies_to is not None:
        return role
    if model_named and _CUE_RE.search(text):
        return RolePhrasing(applies_to="non_household", named=True)
    if model_value in get_args(AppliesTo) and model_value != "anyone" and IDENTITY_RE.search(text):
        return RolePhrasing(applies_to=model_value)
    return RolePhrasing(applies_to="anyone")


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
    trigger = data.get("trigger")
    target_notes: list[str] = []
    if trigger == "removed" and entry.kind != "watch":
        # Removal events refer to watches only: a removal rule on a protected object, zone or
        # line could never fire (fail-open). Use the object's watch, or refuse.
        watch = _watch_for_object(entry, catalog) if entry.kind == "protected_object" else None
        if watch is None:
            return ask(
                f"Vigil can only notice removal of a watched object, and {entry.label} has "
                "no active watch; a removal rule on the protected object would never fire",
                f"Vigil can only tell you an object was taken when it is watched. Watch "
                f"{entry.label} first, or choose a touch rule for it instead?",
            )
        target_notes.append(
            f"Removal is noticed through the watch on {watch.label}, so this rule targets "
            "that watch; it stops working if the watch is revoked or expires."
        )
        entry = watch
    role = resolve_applies_to(text, data.get("applies_to"), bool(data.get("named_person") is True))
    applies_to = role.applies_to or "anyone"
    active = None
    start, end = data.get("active_start"), data.get("active_end")
    try:
        if start or end:
            active = ActiveWindow(start=start or "00:00", end=end or "23:59")
        rule = Rule(
            id=rule_id or _rule_id(text),
            name=f"Rule on {entry.label}"[:80],  # replaced by the code-built name below
            target=RuleTarget(kind=entry.kind, id=entry.id),
            trigger=trigger,
            min_dwell_s=data.get("min_dwell_s"),
            active=active,
            severity=data.get("severity") or "needs_attention",
            applies_to=applies_to,
            state="draft",
        )
    except (ValidationError, ValueError) as exc:
        return ask(f"the rule was incomplete: {type(exc).__name__}", question)

    # No compiled rule ever names a person: the name is always built by code (the model's
    # free text is never kept), then verified.
    rule = rule.model_copy(update={"name": _code_rule_name(entry, rule)})
    if rule_person_terms(rule, catalog, role.names):
        return ask("the rule's name would identify a person; fill the form instead")

    notice = named_person_notice(role.names) if role.named else None
    limits = [BASE_LIMIT, *target_notes]
    if notice:
        limits.append(notice)
    if entry.kind not in _TRIGGER_KINDS.get(rule.trigger, {entry.kind}):
        limits.append(
            f"'{rule.trigger}' is normally used with a "
            f"{' or '.join(sorted(_TRIGGER_KINDS[rule.trigger]))}, but {entry.label} is a "
            f"{entry.kind.replace('_', ' ')}; check the target before confirming."
        )
    return RuleDraft(
        rule=rule,
        basis_note=BASIS_NOTES[applies_to],
        limits=limits,
        notice=notice,
        identity_exception=applies_to != "anyone",
        source_text=text,
        call_id=call_id,
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
    """Forced cases are decided by code with no call; otherwise Spark decides.

    The forced rule is :func:`vigil.reasoning.triage.forced_escalation`, the single source,
    so the spec 9.4 case-2 household exemption (``RuleResult.scoped_out``, applied when the
    summary is built) holds here too.
    """
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
