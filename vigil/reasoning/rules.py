"""Rules engine (FR-012, spec 9.4). Pure code: the floor of every verdict comes from here.

A rule is *in force* for an event when

- the rule's state is ``active``;
- the event type equals the rule's trigger;
- the event's target is the rule's target (for ``watch`` targets, the watch id or the watched
  phrase, e.g. ``package``; ``*`` matches any target of that kind);
- for ``dwell``, the dwell lasted at least ``min_dwell_s``;
- the event's start, in local time, is inside the active window. Windows are
  ``[start, end)``; an end before the start crosses midnight (17:30-06:00); start == end means
  all day; no window means always.

A rule in force *fires* when its ``applies_to`` covers the event's ``actor_role``
(``vigil.models.APPLIES_TO_ROLES``, the spec 9.4 table). An event with no role yet counts as
``unknown``, which every ``applies_to`` covers: roles fail closed.

The floor is the highest severity over the visit's events. A protected-object event (``touch``
on a protected object, or ``removed``) that no rule fired on sets the floor per spec 9.4:

1. a rule fired: its severity (above);
2. rules are in force on the object, every one excludes the actor's role, and the role is
   ``household_insider``: the floor stays **normal** (the owner scoped the rule);
3. otherwise (no rule in force, or an in-force rule excludes an ``expected_visitor``):
   **noteworthy**.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime, time, timedelta
from pathlib import Path

from vigil.models import (
    APPLIES_TO_ROLES,
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


class RuleOutcome(RuleResult):
    """Kept for callers that import it: :class:`RuleResult` now carries ``scoped_out`` (the
    9.4 case-2 household events that keep the floor normal and do not force escalation)."""


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


def role_of(event: Event) -> str:
    """The event's actor role; a missing role is ``unknown`` (fails closed)."""
    return event.actor_role or "unknown"


def applies(rule: Rule, event: Event) -> bool:
    """Whether the rule's ``applies_to`` covers the event's actor role (spec 9.4 table)."""
    return role_of(event) in APPLIES_TO_ROLES[rule.applies_to]


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


def is_protected_event(event: Event, protected_ids: Collection[str] | None = None) -> bool:
    """A 9.4 protected-object event: a touch of a protected object, or a removal."""
    if event.type == "removed":
        return True
    return event.type == "touch" and _is_protected(event, protected_ids)


def in_force(
    rule: Rule,
    event: Event,
    tz: str,
    session_start: datetime | None,
    watches: Sequence[Watch] = (),
) -> bool:
    """Whether `rule` is in force for `event`: everything but ``applies_to`` matches."""
    if rule.state != "active" or event.type != rule.trigger:
        return False
    if not _target_matches(rule, event, {w.id: w for w in watches}):
        return False
    if rule.target.kind == "watch" and session_start is not None:
        from vigil.reasoning.loop import is_active

        watch = next((w for w in watches if w.id == event.target), None)
        if watch is not None and not is_active(watch, session_start + timedelta(seconds=event.t0)):
            return False
    if (
        rule.trigger == "dwell"
        and rule.min_dwell_s is not None
        and (event.t1 - event.t0) < rule.min_dwell_s
    ):
        return False
    if rule.active is not None:
        if session_start is None:
            raise ValueError(f"rule {rule.id} has an active window but session_start is unknown")
        if not in_window(rule.active, to_local(session_start, event.t0, tz)):
            return False
    return True


def evaluate_rules(
    visit: Visit,
    events: Sequence[Event],
    rules: Sequence[Rule],
    tz: str,
    session_start: datetime | None,
    *,
    protected_ids: Collection[str] | None = None,
    watches: Sequence[Watch] = (),
) -> RuleOutcome:
    """Fire rules over this visit's events and compute the severity floor (spec 9.4).

    `session_start` is the tz-aware wall-clock time of session t=0; it is required as soon as
    any candidate rule has an active window. `protected_ids` lists protected-object ids; when
    omitted, targets starting with ``po_`` are treated as protected objects.
    """
    mine = _visit_events(visit, events)
    hits: list[RuleHit] = []
    floor: Severity = "normal"
    fired: set[str] = set()
    forced_by: dict[str, list[Rule]] = {e.id: [] for e in mine}

    for rule in rules:
        for e in mine:
            if not in_force(rule, e, tz, session_start, watches):
                continue
            forced_by[e.id].append(rule)
            if not applies(rule, e):
                continue
            hits.append(RuleHit(rule_id=rule.id, visit_id=visit.id, event_id=e.id))
            fired.add(e.id)
            floor = _max(floor, rule.severity)

    scoped_out: list[str] = []
    for e in mine:
        if e.id in fired or not is_protected_event(e, protected_ids):
            continue
        if forced_by[e.id] and role_of(e) == "household_insider":
            scoped_out.append(e.id)  # case 2: every in-force rule excludes the household
            continue
        floor = _max(floor, "noteworthy")  # case 3

    return RuleOutcome(hits=hits, floor=floor, scoped_out=scoped_out)


def _max(a: Severity, b: Severity) -> Severity:
    return a if SEVERITY_ORDER[a] >= SEVERITY_ORDER[b] else b
