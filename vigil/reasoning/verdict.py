"""Verdict (FR-016): a pure function of the rule floor, gaps and Wonder's proposal.

This is the whole rule set, verbatim from spec 9.4. Only rules can produce needs_attention;
an unresolved gap with no such rule gives cant_confirm; a cited noteworthy proposal may raise
normal to noteworthy and can never lower the floor.
"""

from __future__ import annotations

from collections.abc import Iterable

from vigil.models import Gap, StoryDraft, ValidationResult

ORDER = {"normal": 0, "noteworthy": 1, "needs_attention": 2}


def compose(floor: str, unresolved_gap: bool, proposal: str | None, proposal_cited: bool) -> str:
    if floor == "needs_attention":  # only rules can set this
        return "needs_attention"
    if unresolved_gap:  # no rule fired, subject vanished
        return "cant_confirm"
    if proposal == "noteworthy" and proposal_cited:
        return max(floor, "noteworthy", key=ORDER.get)
    return floor  # Wonder can never lower the floor


def has_unresolved_gap(gaps: Iterable[Gap]) -> bool:
    return any(not g.resolved for g in gaps)


def proposal_cited(draft: StoryDraft | None, validation: ValidationResult | None) -> bool:
    """A proposal counts only from a draft that passed validation and cites at least one event."""
    if draft is None or validation is None or not validation.passed:
        return False
    return any(s.event_ids for s in draft.sentences)
