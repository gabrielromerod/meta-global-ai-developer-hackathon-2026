"""Muse Wonder: story from the visit ledger JSON, never pixels (FR-014).

The request carries the VisitLedger as JSON text only: no image, video, file id, mask path
or call id ever reaches Wonder (spec 5.8); :func:`assert_no_media` enforces this on every
body. The answer must match the spec 9.4 Story contract (``verdict_proposal`` normal or
noteworthy only, sentences citing event ids, ``gap_after_sentence``, ``watch_proposals``).
A malformed or off-schema answer raises :class:`StoryFormatError`, which carries
``ValidationFailure(check="schema")`` items so the story stage treats it like any
validator failure: one retry with the reasons, then the template (FR-015).

Roles (FR-044, validator check 7): the ledger carries each subject chain's ``actor_role``
and ``role_basis``, and code adds the one ``role_phrase`` the story may use for it (or
``null``), so Wonder never has to infer a role. The ledger holds no person names. The
phrases come from ``config/role_phrases.json``, the file validator check 7 reads.

Spec 5.14 notes that strict-schema support on ``muse-wonder-1.0`` is unverified, so
``schema_mode="json"`` sends no ``text.format`` and puts the schema in the instructions
instead; the parser tolerates a Markdown code fence in that mode.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from vigil.meta.budget import WONDER
from vigil.meta.client import extract_text, load_json_text
from vigil.meta.prompts import load_prompt
from vigil.models import StoryDraft, Subject, ValidationFailure, VisitLedger

SchemaMode = Literal["json_schema", "json"]

_DROP_KEYS = frozenset({"mask_path", "file_id", "call_id", "overlay_path", "path", "mask_rle"})
_MEDIA_TYPES = frozenset({"input_image", "input_video", "input_audio", "input_file"})
_MEDIA_KEYS = frozenset({"file_id", "image_url", "video_url", "audio_url", "file_url"})
_MEDIA_TEXT = re.compile(r"\bfile-[A-Za-z0-9]|data:(?:image|video|audio)/", re.I)
_SENTENCE_KEYS = frozenset({"text", "event_ids"})

ROLE_PHRASES_PATH = Path(__file__).resolve().parents[2] / "config" / "role_phrases.json"
"""The single source of role phrases, shared with validator check 7 (spec 9.4)."""


@dataclass(frozen=True)
class RolePhrase:
    """One allowed role phrase: the role it asserts and, optionally, the role bases it needs."""

    phrase: str
    role: str
    basis_prefixes: tuple[str, ...] = ()


DEFAULT_ROLE_PHRASES: tuple[RolePhrase, ...] = (
    RolePhrase("someone who came out of the house", "household_insider", ("egress:",)),
    RolePhrase("an expected visitor", "expected_visitor"),
    RolePhrase("someone who arrived from outside the property", "external_visitor"),
)
"""Used only when ``config/role_phrases.json`` is absent."""


def load_role_phrases(path: Path | str = ROLE_PHRASES_PATH) -> tuple[RolePhrase, ...]:
    """Role phrases from the check-7 config; :data:`DEFAULT_ROLE_PHRASES` if it is absent."""
    p = Path(path)
    if not p.is_file():
        return DEFAULT_ROLE_PHRASES
    raw = json.loads(p.read_text(encoding="utf-8"))
    return tuple(
        RolePhrase(
            " ".join(str(item["phrase"]).lower().split()),
            str(item["role"]),
            tuple(item.get("basis_prefixes") or ()),
        )
        for item in raw["phrases"]
    )


ROLE_PHRASE_LIST: tuple[RolePhrase, ...] = load_role_phrases()
ROLE_PHRASES: dict[str, str] = {rp.phrase: rp.role for rp in ROLE_PHRASE_LIST}
"""Allowed role phrase -> the role it asserts (spec 9.4 check 7; config/role_phrases.json)."""


def role_phrase_for(subject: Subject, phrases: tuple[RolePhrase, ...] | None = None) -> str | None:
    """The one role phrase a story may use for this subject, or None (check 7).

    A phrase with ``basis_prefixes`` applies only when the subject's ``role_basis`` starts
    with one of them (``household_insider`` needs ``egress:<zone>``, so check-in and group
    subjects get none); ``unknown`` has no phrase.
    """
    role, basis = subject.actor_role, subject.role_basis
    for rp in ROLE_PHRASE_LIST if phrases is None else phrases:
        if rp.role != role:
            continue
        if rp.basis_prefixes and not basis.startswith(rp.basis_prefixes):
            continue
        return rp.phrase
    return None


class PixelLeakError(ValueError):
    """A Wonder request would carry media or a file reference (spec 5.8)."""


class StoryFormatError(ValueError):
    """Wonder's answer is not valid JSON or breaks the Story schema (test_wonder_malformed)."""

    def __init__(self, detail: str, call_id: str | None = None, raw: str = ""):
        self.failures = [ValidationFailure(check="schema", detail=detail)]
        self.call_id = call_id
        self.raw = raw[:2000]
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in _DROP_KEYS}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def _clock_fn(ledger: VisitLedger):
    """Session seconds -> "10:14 PM" local, when the session start is known."""
    if ledger.session_start is None or ledger.session_start.tzinfo is None:
        return None
    try:
        from vigil.reasoning.clock import format_clock, to_local
    except ImportError:  # pragma: no cover - reasoning workstream not present
        return None
    start, tz = ledger.session_start, ledger.timezone

    def clock(t: float) -> str | None:
        try:
            return format_clock(to_local(start, t, tz))
        except (ValueError, OverflowError):
            return None

    return clock


def ledger_payload(ledger: VisitLedger) -> dict:
    """The ledger as Wonder sees it: JSON only, file references removed, clock times and
    each subject's allowed ``role_phrase`` added."""
    data = _strip(ledger.model_dump(mode="json", by_alias=True, exclude_none=True))
    data["subjects"] = [
        {
            **_strip(subj.model_dump(mode="json", exclude_none=True)),
            "role_phrase": role_phrase_for(subj),
        }
        for subj in ledger.subjects
    ]
    clock = _clock_fn(ledger)
    if clock is not None:
        for key in ("events", "gaps"):
            for item in data.get(key, []):
                for field in ("t0", "t1"):
                    if field in item and (c := clock(item[field])) is not None:
                        item[f"clock_{field}"] = c
    return data


def assert_no_media(body: Any) -> None:
    """Raise PixelLeakError if any part of a request references pixels or files."""
    if isinstance(body, dict):
        if body.get("type") in _MEDIA_TYPES:
            raise PixelLeakError(f"Wonder request contains a {body['type']} part")
        leaked = _MEDIA_KEYS & set(body)
        if leaked:
            raise PixelLeakError(f"Wonder request contains {sorted(leaked)}")
        for v in body.values():
            assert_no_media(v)
    elif isinstance(body, list):
        for v in body:
            assert_no_media(v)
    elif isinstance(body, str) and _MEDIA_TEXT.search(body):
        raise PixelLeakError("Wonder request text references a file id or inline media")


def _id_enum(values: list[str]) -> dict:
    return {"type": "string", "enum": values} if values else {"type": "string"}


def _closed(props: dict[str, dict]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(props),
        "properties": props,
    }


def story_schema(ledger: VisitLedger) -> dict:
    """Strict Story schema with event, gap and camera ids limited to this visit."""
    event_ids = list(dict.fromkeys(e.id for e in ledger.events))
    gap_ids = list(dict.fromkeys(g.id for g in ledger.gaps))
    cameras = list(dict.fromkeys(e.camera_id for e in ledger.events))
    sentence = _closed(
        {"text": {"type": "string"}, "event_ids": {"type": "array", "items": _id_enum(event_ids)}}
    )
    gap = _closed({"gap_id": _id_enum(gap_ids), "after": {"type": "integer"}})
    watch = _closed(
        {
            "camera_id": _id_enum(cameras),
            "phrase": {"type": "string"},
            "reason_event_id": _id_enum(event_ids),
        }
    )
    return _closed(
        {
            "verdict_proposal": {"type": "string", "enum": ["normal", "noteworthy"]},
            "sentences": {"type": "array", "items": sentence},
            "gap_after_sentence": {"type": "array", "items": gap},
            "watch_proposals": {"type": "array", "items": watch},
        }
    )


def build_story_request(
    ledger: VisitLedger,
    failures: list[str] | None = None,
    *,
    schema_mode: SchemaMode = "json_schema",
) -> dict:
    """Responses body (without ``model``) asking Wonder for the Story JSON."""
    prompt = load_prompt("story")
    schema = story_schema(ledger)
    content = [
        {
            "type": "input_text",
            "text": "Visit ledger (JSON):\n" + json.dumps(ledger_payload(ledger), sort_keys=True),
        }
    ]
    if failures:
        content.append(
            {
                "type": "input_text",
                "text": "Your previous draft was rejected for these reasons. Fix every one:\n"
                + "\n".join(f"- {f}" for f in failures),
            }
        )
    body: dict[str, Any] = {
        "instructions": prompt.text,
        "input": [{"type": "message", "role": "user", "content": content}],
        "max_output_tokens": 1500,
    }
    if schema_mode == "json_schema":
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": "visit_story",
                "schema": schema,
                "strict": True,
            }
        }
    elif schema_mode == "json":
        body["instructions"] = (
            prompt.text
            + "\n\nReturn only one JSON object that matches this JSON Schema:\n"
            + json.dumps(schema, sort_keys=True)
        )
    else:
        raise ValueError(f"unknown schema_mode {schema_mode!r}")
    assert_no_media(body)
    return body


# ---------------------------------------------------------------------------
# Answer
# ---------------------------------------------------------------------------


def parse_story(text: str, call_id: str | None = None) -> StoryDraft:
    """Parse Wonder's answer into a StoryDraft or raise StoryFormatError."""
    try:
        data = load_json_text(text)
    except ValueError:
        raise StoryFormatError("story answer is not valid JSON", call_id, text) from None
    if not isinstance(data, dict):
        raise StoryFormatError("story answer is not a JSON object", call_id, text)
    if "sentences" not in data:
        raise StoryFormatError("story answer has no 'sentences'", call_id, text)
    sentences = data["sentences"]
    if not isinstance(sentences, list):
        raise StoryFormatError("'sentences' is not a list", call_id, text)
    for i, s in enumerate(sentences):
        if not isinstance(s, dict) or not set(s) <= _SENTENCE_KEYS:
            extra = sorted(set(s) - _SENTENCE_KEYS) if isinstance(s, dict) else []
            raise StoryFormatError(
                f"sentence {i} must have only text and event_ids (extra {extra})", call_id, text
            )
    try:
        draft = StoryDraft.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise StoryFormatError(
            f"story schema mismatch at {loc}: {first['msg']}", call_id, text
        ) from None
    for s in draft.sentences:
        s.source = "wonder"
        s.gap_id = None
    return draft


def write_story(
    c,
    ledger: VisitLedger,
    failures: list[str] | None = None,
    *,
    schema_mode: SchemaMode = "json_schema",
) -> StoryDraft:
    """Ask Wonder for the story of one visit (FR-014); ``failures`` are the retry reasons."""
    body = build_story_request(ledger, failures, schema_mode=schema_mode)
    resp = c.responses(WONDER, body, purpose="story", visit_id=ledger.visit.id, feature="story")
    call_id = (resp.get("_vigil") or {}).get("call_id")
    return parse_story(extract_text(resp), call_id)
