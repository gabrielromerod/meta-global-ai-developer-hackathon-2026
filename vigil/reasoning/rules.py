"""Rules engine (FR-012, spec 9.4). Pure code: the floor of every verdict comes from here.

A rule fires on an event of this visit when

- the rule's state is ``active``;
- the event type equals the rule's trigger;
- the event's target is the rule's target (for ``watch`` targets, the watch id or the watched
  phrase, e.g. ``package``; ``*`` matches any target of that kind);
- for ``dwell``, the dwell lasted at least ``min_dwell_s``;
- the event's start, in local time, is inside the active window. Windows are
  ``[start, end)``; an end before the start crosses midnight (22:00-06:00); start == end means
  all day; no window means always.

The floor is the highest severity of the rules that fired. A protected-object touch that no
rule matched sets the floor to at least ``noteworthy`` (spec 9.4 note).
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime, time
from pathlib import Path

from vigil.models import (
    SEVERITY_ORDER,
    ActiveWindow,
    Event,
    Rule,
    RuleHit,
    RuleResult,
    Severity,
    Visit,
    Watch,
)
from vigil.reasoning.clock import to_local

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "rules.default.json"
PROTECTED_PREFIX = "po_"


def load_rules(path: Path | str = DEFAULT_RULES_PATH) -> list[Rule]:
    """Rules from a JSON list (or ``{"rules": [...]}``)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw["rules"] if isinstance(raw, dict) else raw
    return [Rule.model_validate(r) for r in items]


def _secs(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 3600 + int(mm) * 60


def in_window(window: ActiveWindow | None, local: time | datetime) -> bool:
    """Whether a local time of day is inside ``[start, end)``, crossing midnight if needed."""
    if window is None:
        return True
    t = local.time() if isinstance(local, datetime) else local
    s = t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6
    start, end = _secs(window.start), _secs(window.end)
    if start == end:
        return True
    if start < end:
        return start <= s < end
    return s >= start or s < end


def _visit_events(visit: Visit, events: Iterable[Event]) -> list[Event]:
    ids = set(visit.event_ids)
    return sorted(
        (e for e in events if e.id in ids or (e.visit_id == visit.id and e.visit_id is not None)),
        key=lambda e: (e.t0, e.id),
    )


def _target_matches(rule: Rule, event: Event, watches: dict[str, Watch]) -> bool:
    want = rule.target.id
    if event.target is None:
        return False
    if want in ("*", event.target):
        return True
    if rule.target.kind == "watch":
        w = watches.get(event.target)
        return w is not None and w.phrase == want
    return False


def _is_protected(event: Event, protected_ids: Collection[str] | None) -> bool:
    if event.target is None:
        return False
    if protected_ids is not None:
        return event.target in protected_ids
    return event.target.startswith(PROTECTED_PREFIX)


def evaluate_rules(
    visit: Visit,
    events: Sequence[Event],
    rules: Sequence[Rule],
    tz: str,
    session_start: datetime | None,
    *,
    protected_ids: Collection[str] | None = None,
    watches: Sequence[Watch] = (),
) -> RuleResult:
    """Fire rules over this visit's events and compute the severity floor.

    `session_start` is the tz-aware wall-clock time of session t=0; it is required as soon as
    any candidate rule has an active window. `protected_ids` lists protected-object ids; when
    omitted, targets starting with ``po_`` are treated as protected objects.
    """
    mine = _visit_events(visit, events)
    by_watch = {w.id: w for w in watches}
    hits: list[RuleHit] = []
    floor: Severity = "normal"
    hit_events: set[str] = set()

    for rule in rules:
        if rule.state != "active":
            continue
        for e in mine:
            if e.type != rule.trigger or not _target_matches(rule, e, by_watch):
                continue
            if (
                rule.trigger == "dwell"
                and rule.min_dwell_s is not None
                and (e.t1 - e.t0) < rule.min_dwell_s
            ):
                continue
            if rule.active is not None:
                if session_start is None:
                    raise ValueError(
                        f"rule {rule.id} has an active window but session_start is unknown"
                    )
                if not in_window(rule.active, to_local(session_start, e.t0, tz)):
                    continue
            hits.append(RuleHit(rule_id=rule.id, visit_id=visit.id, event_id=e.id))
            hit_events.add(e.id)
            floor = _max(floor, rule.severity)

    for e in mine:
        if e.type == "touch" and _is_protected(e, protected_ids) and e.id not in hit_events:
            floor = _max(floor, "noteworthy")

    return RuleResult(hits=hits, floor=floor)


def _max(a: Severity, b: Severity) -> Severity:
    return a if SEVERITY_ORDER[a] >= SEVERITY_ORDER[b] else b
