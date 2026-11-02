"""Citation validator (FR-015, NFR-003, spec 9.4). Any failure rejects the draft.

1. Schema valid; 1 to 6 sentences; non-empty text; the model may not write code (gap)
   sentences; gap placements point at a sentence.
2. Every sentence cites at least one event, and every cited event belongs to this visit
   (also the ``reason_event_id`` of watch proposals).
3. Every clock time in a sentence is within 60 s of a cited event and outside every gap.
   "10:14 PM" means 22:14:00-22:14:59; the instant checked against gaps is the point of that
   minute closest to the matched event, so "back at 10:15 PM" for a return at 22:15:11 is fine
   while "at 10:14:50 PM" inside a gap is not.
4. Every camera name (or id) in a sentence belongs to a cited event's camera.
5. No banned words: gender, age, ethnicity, appearance-of-body terms, judgements, and
   gendered pronouns. The subject is always "a person" or "they".
6. Every ``gap_id`` exists in this visit.

All failures are collected (not just the first) so the single retry gets the full list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from vigil.models import (
    Event,
    StoryDraft,
    ValidationFailure,
    ValidationResult,
    VisitLedger,
)
from vigil.reasoning.clock import resolve_tz

MAX_SENTENCES = 6
TIME_TOLERANCE_S = 60.0
GAP_EDGE_EPS_S = 0.5
"""A time on a gap's boundary (the moment the subject left or came back) is not inside it."""

BANNED_WORDS: tuple[str, ...] = (
    # gendered pronouns and nouns
    "he", "she", "him", "her", "his", "hers", "himself", "herself",
    "man", "men", "woman", "women", "male", "males", "female", "females", "boy", "boys",
    "girl", "girls", "guy", "guys", "gal", "lady", "ladies", "gentleman", "gentlemen",
    "mr", "mrs", "sir", "madam", "gender", "masculine", "feminine",
    # age
    "age", "aged", "old", "older", "elderly", "young", "younger", "youth", "teen", "teens",
    "teenager", "teenagers", "teenage", "kid", "kids", "child", "children", "toddler",
    "baby", "adult", "adults", "senior", "juvenile", "minor",
    # ethnicity, skin, face
    "race", "racial", "ethnic", "ethnicity", "asian", "african", "hispanic", "latino",
    "latina", "latinx", "caucasian", "arab", "arabic", "indian", "native", "indigenous",
    "skin", "skinned", "complexion", "face", "faces", "facial", "beard", "bearded", "bald",
    # judgements
    "suspicious", "suspiciously", "suspect", "suspects", "intruder", "intruders", "intrusion",
    "thief", "thieves", "theft", "steal", "stole", "stolen", "stealing", "burglar", "burglars",
    "burglary", "criminal", "criminals", "crime", "prowler", "prowling", "trespasser",
    "trespassing", "lurking", "lurker", "sneaking", "sneaky", "creepy", "dangerous", "threat",
    "threatening", "illegal", "malicious",
)  # fmt: skip
_BANNED_RE = re.compile(
    r"\b(" + "|".join(sorted(BANNED_WORDS, key=len, reverse=True)) + r")\b", re.I
)

_TIME_RE = re.compile(
    r"(?<![\d:])(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?![\w:])",
    re.I,
)


@dataclass(frozen=True)
class ClockMention:
    """A clock time found in text. `minute`/`second` are None when not written."""

    text: str
    hour: int
    minute: int | None
    second: int | None

    @property
    def precision_s(self) -> float:
        return 1.0 if self.second is not None else 60.0


def find_clock_times(text: str) -> list[ClockMention]:
    """Clock times written as '10:14 PM', '10:14pm', '10:14 p.m.', '22:14', '10 PM'.

    A bare number ("41 s") is not a time: it needs a colon or AM/PM.
    """
    out: list[ClockMention] = []
    for m in _TIME_RE.finditer(text):
        hh, mm, ss, ampm = m.group(1), m.group(2), m.group(3), m.group(4)
        if mm is None and ampm is None:
            continue
        hour = int(hh)
        if ampm:
            if not 1 <= hour <= 12:
                continue
            pm = ampm.lower().startswith("p")
            hour = (hour % 12) + (12 if pm else 0)
        elif hour > 23:
            continue
        minute = int(mm) if mm is not None else None
        second = int(ss) if ss is not None else None
        if (minute is not None and minute > 59) or (second is not None and second > 59):
            continue
        out.append(ClockMention(m.group(0).strip(), hour, minute, second))
    return out


def _parse(draft: Any) -> tuple[StoryDraft | None, str | None]:
    if isinstance(draft, StoryDraft):
        return draft, None
    try:
        if isinstance(draft, (str, bytes)):
            return StoryDraft.model_validate_json(draft), None
        if isinstance(draft, dict):
            return StoryDraft.model_validate(draft), None
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        return None, f"output is not a valid story: {_short(exc)}"
    return None, f"output is not a JSON object (got {type(draft).__name__})"


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errs = exc.errors()[:3]
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errs)
    return str(exc)[:200]


def _visit_event_map(ledger: VisitLedger) -> dict[str, Event]:
    v = ledger.visit
    ids = set(v.event_ids)
    return {
        e.id: e
        for e in ledger.events
        if e.id in ids or e.visit_id == v.id or (not ids and e.visit_id is None)
    }


def _camera_terms(ledger: VisitLedger) -> list[tuple[re.Pattern[str], str]]:
    terms: list[tuple[str, str]] = []
    for cid, name in ledger.camera_names.items():
        terms.append((name, cid))
        if "_" in cid or cid.lower() != name.lower():
            terms.append((cid, cid))
    terms.sort(key=lambda x: -len(x[0]))
    return [(re.compile(r"\b" + re.escape(t) + r"\b", re.I), cid) for t, cid in terms]


def _mention_candidates(m: ClockMention, near: datetime) -> list[tuple[datetime, datetime]]:
    """Absolute [start, end) intervals the mention could mean, on days around `near`."""
    out = []
    for day in (-1, 0, 1):
        d = near + timedelta(days=day)
        start = d.replace(hour=m.hour, minute=m.minute or 0, second=m.second or 0, microsecond=0)
        out.append((start, start + timedelta(seconds=m.precision_s)))
    return out


def _check_times(
    idx: int,
    text: str,
    cited: list[Event],
    ledger: VisitLedger,
    failures: list[ValidationFailure],
) -> None:
    mentions = find_clock_times(text)
    if not mentions:
        return
    if ledger.session_start is None or ledger.session_start.utcoffset() is None:
        failures.append(
            ValidationFailure(
                check="time_mismatch",
                sentence_index=idx,
                detail="clock time in text but the session start time is unknown",
            )
        )
        return
    zone = resolve_tz(ledger.timezone, ledger.session_start.tzinfo)
    start = ledger.session_start
    gaps = [g for g in ledger.gaps if g.visit_id == ledger.visit.id or g.id in ledger.visit.gap_ids]
    for m in mentions:
        best: tuple[float, float] | None = None  # (distance, instant in session seconds)
        for e in cited:
            e_local = (start + timedelta(seconds=e.t0)).astimezone(zone)
            for lo, hi in _mention_candidates(m, e_local):
                lo_s = (lo - start).total_seconds()
                hi_s = (hi - start).total_seconds() - 1e-6  # [lo, hi)
                # distance between the mention's interval and the event's [t0, t1], and the
                # point of the mention's interval closest to the event's start
                dist = max(0.0, lo_s - e.t1, e.t0 - hi_s)
                x = min(max(e.t0, lo_s), hi_s)
                if best is None or dist < best[0]:
                    best = (dist, x)
        if best is None or best[0] > TIME_TOLERANCE_S:
            failures.append(
                ValidationFailure(
                    check="time_mismatch",
                    sentence_index=idx,
                    detail=f"'{m.text}' is not within 60 s of any cited event",
                )
            )
            continue
        instant = best[1]
        for g in gaps:
            if g.t0 + GAP_EDGE_EPS_S < instant < g.t1 - GAP_EDGE_EPS_S:
                failures.append(
                    ValidationFailure(
                        check="time_in_gap",
                        sentence_index=idx,
                        detail=f"'{m.text}' falls inside gap {g.id}, when nothing was observed",
                    )
                )
                break


def validate(draft: Any, ledger: VisitLedger, attempt: int = 1) -> ValidationResult:
    """Run all six checks. `draft` may be a StoryDraft, a dict or raw JSON text."""
    parsed, err = _parse(draft)
    if parsed is None:
        return ValidationResult(
            passed=False,
            failures=[ValidationFailure(check="schema", detail=err or "unreadable output")],
            attempt=attempt,
        )

    failures: list[ValidationFailure] = []
    n = len(parsed.sentences)
    if not 1 <= n <= MAX_SENTENCES:
        failures.append(
            ValidationFailure(
                check="sentence_count", detail=f"{n} sentences; expected 1 to {MAX_SENTENCES}"
            )
        )

    events = _visit_event_map(ledger)
    cams = _camera_terms(ledger)

    for i, s in enumerate(parsed.sentences):
        if not s.text.strip():
            failures.append(ValidationFailure(check="schema", sentence_index=i, detail="empty"))
            continue
        if s.source == "code" or s.gap_id is not None:
            failures.append(
                ValidationFailure(
                    check="schema",
                    sentence_index=i,
                    detail="gap sentences are written by code, not by the model",
                )
            )
        # 2. citations
        if not s.event_ids:
            failures.append(
                ValidationFailure(check="uncited", sentence_index=i, detail="cites no event")
            )
        foreign = [eid for eid in s.event_ids if eid not in events]
        if foreign:
            failures.append(
                ValidationFailure(
                    check="foreign_event",
                    sentence_index=i,
                    detail=f"cites events not in this visit: {', '.join(foreign)}",
                )
            )
        cited = [events[eid] for eid in s.event_ids if eid in events]
        # 3. clock times
        _check_times(i, s.text, cited, ledger, failures)
        # 4. camera names
        cited_cams = {e.camera_id for e in cited}
        named: set[str] = set()
        rest = s.text
        for pat, cid in cams:
            if pat.search(rest):
                named.add(cid)
                rest = pat.sub(" ", rest)
        wrong = sorted(named - cited_cams)
        if wrong:
            failures.append(
                ValidationFailure(
                    check="camera_mismatch",
                    sentence_index=i,
                    detail=f"names camera(s) {', '.join(wrong)} that no cited event is on",
                )
            )
        # 5. banned words
        found = sorted({m.group(0).lower() for m in _BANNED_RE.finditer(s.text)})
        if found:
            failures.append(
                ValidationFailure(
                    check="banned_word",
                    sentence_index=i,
                    detail=f"uses {', '.join(found)}; say 'a person' or 'they', no judgements",
                )
            )

    # 6. gap ids and placements
    visit_gaps = {g.id for g in ledger.gaps if g.visit_id == ledger.visit.id}
    visit_gaps |= set(ledger.visit.gap_ids) & {g.id for g in ledger.gaps}
    for p in parsed.gap_after_sentence:
        if p.gap_id not in visit_gaps:
            failures.append(
                ValidationFailure(
                    check="unknown_gap", detail=f"gap {p.gap_id} is not in this visit"
                )
            )
        if not -1 <= p.after < max(n, 0):
            failures.append(
                ValidationFailure(
                    check="schema", detail=f"gap {p.gap_id} placed after missing sentence {p.after}"
                )
            )
    for w in parsed.watch_proposals:
        if w.reason_event_id not in events:
            failures.append(
                ValidationFailure(
                    check="foreign_event",
                    detail=f"watch proposal cites {w.reason_event_id}, not in this visit",
                )
            )

    return ValidationResult(passed=not failures, failures=failures, attempt=attempt)


def failure_reasons(result: ValidationResult) -> list[str]:
    """Human-readable reasons for the retry prompt."""
    out = []
    for f in result.failures:
        where = f" (sentence {f.sentence_index})" if f.sentence_index is not None else ""
        out.append(f"{f.check}{where}: {f.detail}")
    return out
