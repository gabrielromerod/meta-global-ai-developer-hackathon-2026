"""Triage (FR-013, spec 5.5): code forces escalation; otherwise a model decides.

Escalation is forced, without asking any model, when a rule fired, a protected object was
touched, or a gap is unresolved. The only exempt touch is a spec 9.4 case-2 touch: a
``household_insider`` touching an object whose every in-force rule excludes the household
(the owner scoped the rule), reported by ``evaluate_rules`` as ``RuleResult.scoped_out``.
Otherwise the injected model triage (Glimmer on the local
GPU, or Spark through ``vigil.meta``) decides. If it is unavailable or fails, a code
heuristic decides (escalate only when a new object appeared) so a card is never blank.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence

from vigil.models import Event, Gap, RuleResult, Track, TriageDecision, Visit, VisitSummary
from vigil.reasoning.rules import PROTECTED_PREFIX

log = logging.getLogger(__name__)

ModelTriage = Callable[[VisitSummary], TriageDecision]
OBJECT_CLASSES = frozenset({"package", "object"})


def forced_escalation(summary: VisitSummary) -> TriageDecision | None:
    """A forced decision when code requires escalation, else None (ask the model)."""
    reasons = []
    if summary.rule_fired:
        reasons.append("a rule fired")
    if summary.protected_touched:
        reasons.append("a protected object was touched")
    if summary.unresolved_gap:
        reasons.append("a gap is unresolved")
    if not reasons:
        return None
    return TriageDecision(
        escalate=True, forced=True, reason="forced by code: " + ", ".join(reasons), source="code"
    )


def decide(summary: VisitSummary, model_triage: ModelTriage | None) -> TriageDecision:
    forced = forced_escalation(summary)
    if forced is not None:
        return forced
    if model_triage is not None:
        try:
            d = model_triage(summary)
        except Exception as exc:  # model down: fall back to code, never blank
            log.warning("model triage failed: %s", type(exc).__name__)
        else:
            # A model can never claim a forced (code) decision.
            source = d.source if d.source in ("glimmer", "spark") else "spark"
            return d.model_copy(update={"forced": False, "source": source})
    return TriageDecision(
        escalate=summary.new_object,
        forced=False,
        reason="model triage unavailable; escalated only if a new object appeared",
        source="code",
    )


def summarize(
    visit: Visit,
    events: Sequence[Event],
    gaps: Sequence[Gap],
    rule_result: RuleResult,
    *,
    protected_ids: Collection[str] | None = None,
    tracks: Sequence[Track] = (),
    exempt_event_ids: Collection[str] = (),
) -> VisitSummary:
    """Compact triage input for one visit.

    A touch listed in ``rule_result.scoped_out`` (any :class:`RuleResult`) or in
    `exempt_event_ids` is a 9.4 case-2 household touch and does not count as touched.
    """
    exempt = set(exempt_event_ids) | set(rule_result.scoped_out)
    ids = set(visit.event_ids)
    mine = sorted(
        (e for e in events if e.id in ids or e.visit_id == visit.id), key=lambda e: (e.t0, e.id)
    )

    def protected(target: str | None) -> bool:
        if target is None:
            return False
        if protected_ids is not None:
            return target in protected_ids
        return target.startswith(PROTECTED_PREFIX)

    cls = {t.id: t.cls for t in tracks}
    vgaps = [g for g in gaps if g.visit_id == visit.id or g.id in visit.gap_ids]
    return VisitSummary(
        visit_id=visit.id,
        cameras=sorted({e.camera_id for e in mine}),
        event_types=[e.type for e in mine],
        rule_fired=bool(rule_result.hits),
        protected_touched=any(
            e.type == "touch" and protected(e.target) and e.id not in exempt for e in mine
        ),
        unresolved_gap=any(not g.resolved for g in vgaps),
        new_object=any(e.type == "enter" and cls.get(e.track_id) in OBJECT_CLASSES for e in mine),
        duration_s=visit.t1 - visit.t0,
    )
