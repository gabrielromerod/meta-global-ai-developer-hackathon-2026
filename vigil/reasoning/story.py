"""Story orchestration (FR-014, FR-015, spec 5.5): Wonder writes; code checks and decides.

``run_story`` calls the injected writer (Muse Wonder through ``vigil.meta.wonder``), validates
the draft, retries once with the failure reasons, and falls back to the template after a
second failure. Malformed writer output, and a writer that raises, count as validator
failures (global error table: ``test_wonder_malformed``). Gap sentences are always written
here, by code, never by the model.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vigil.models import (
    Config,
    Event,
    Gap,
    GapPlacement,
    StoryDraft,
    StorySentence,
    ValidationFailure,
    ValidationResult,
    VerdictProposal,
    VisitLedger,
    WatchProposal,
)
from vigil.reasoning.templates import template_story
from vigil.reasoning.validator import _parse, failure_reasons, validate
from vigil.reasoning.verdict import proposal_cited as _proposal_cited

log = logging.getLogger(__name__)

Writer = Callable[[VisitLedger, list[str] | None], Any]
"""(ledger, failures from the previous attempt or None) -> StoryDraft, dict or JSON text."""
TemplateFn = Callable[[VisitLedger], list[StorySentence]]

MAX_ATTEMPTS = 2  # the first draft plus one retry


class StoryOutcome(BaseModel):
    """What the card publishes (module-local; requested for vigil.models)."""

    model_config = ConfigDict(extra="forbid")

    sentences: list[StorySentence]
    """Final story with code-written gap sentences in place."""
    source: Literal["wonder", "template"]
    draft: StoryDraft | None = None
    """The validated Wonder draft, when one passed."""
    proposal: VerdictProposal | None = None
    proposal_cited: bool = False
    watch_proposals: list[WatchProposal] = Field(default_factory=list)
    """Only from a validated draft (spec 5.7)."""
    validations: list[ValidationResult] = Field(default_factory=list)


def region_names_from(cfg: Config) -> dict[str, str]:
    return {r.id: r.name for r in cfg.blind_regions}


def _duration(seconds: float) -> str:
    s = max(0, round(seconds))
    if s < 90:
        return f"{s} s"
    m, rem = divmod(s, 60)
    return f"{m} min {rem} s" if rem else f"{m} min"


def gap_sentence(
    gap: Gap, region_names: Mapping[str, str], camera_names: Mapping[str, str]
) -> StorySentence:
    """The code-written sentence for one gap (never produced by a model)."""
    dur = _duration(gap.duration_s)
    if gap.kind == "clip_truncated":
        text = (
            "The recording ended before the camera event closed. "
            "Vigil can't confirm what happened afterward."
        )
    elif gap.kind in {"battery_wake", "clock_drift"}:
        reason = (
            "battery wake" if gap.kind == "battery_wake" else "camera clock drift above 2 seconds"
        )
        text = (
            f"Vigil can't confirm what happened for {dur}: {reason}. The sightings remain unlinked."
        )
    elif gap.kind == "outage":
        cam = camera_names.get(gap.from_camera or "", gap.from_camera or "a")
        text = f"Vigil can't confirm what happened for {dur} while the {cam} camera was offline."
    elif gap.kind == "ambiguous_link":
        cam = camera_names.get(gap.from_camera or "", gap.from_camera)
        after = f" after they left the {cam} camera's view" if cam else ""
        text = (
            f"Vigil can't confirm what happened for {dur}{after}: "
            "more than one later sighting could be them."
        )
    else:
        where = region_names.get(gap.region_id or "") or "in a blind spot"
        if gap.resolved:
            text = f"Vigil can't confirm what happened for {dur} {where}."
        else:
            text = (
                f"Vigil lost sight of them {where} and can't confirm what happened; "
                "they were not seen again."
            )
    return StorySentence(text=text, event_ids=[], source="code", gap_id=gap.id)


def _visit_gaps(ledger: VisitLedger) -> list[Gap]:
    v = ledger.visit
    gs = [g for g in ledger.gaps if g.visit_id == v.id or g.id in v.gap_ids]
    return sorted(gs, key=lambda g: (g.t0, g.id))


def insert_gap_sentences(
    sentences: Sequence[StorySentence],
    gaps: Sequence[Gap],
    events: Sequence[Event],
    placements: Sequence[GapPlacement] = (),
    region_names: Mapping[str, str] | None = None,
    camera_names: Mapping[str, str] | None = None,
) -> list[StorySentence]:
    """Put one code sentence per gap after the sentence the draft chose, else chronologically."""
    region_names = region_names or {}
    camera_names = camera_names or {}
    t_of = {e.id: e.t0 for e in events}
    chosen: dict[str, int] = {}
    for p in placements:
        if -1 <= p.after < len(sentences):
            chosen.setdefault(p.gap_id, p.after)
    after_of: dict[str, int] = {}
    for g in gaps:
        if g.id in chosen:
            after_of[g.id] = chosen[g.id]
            continue
        idx = -1
        for i, s in enumerate(sentences):
            times = [t_of[eid] for eid in s.event_ids if eid in t_of]
            if times and min(times) <= g.t0:
                idx = i
        after_of[g.id] = idx
    out = [gap_sentence(g, region_names, camera_names) for g in gaps if after_of[g.id] == -1]
    for i, s in enumerate(sentences):
        out.append(s)
        out.extend(gap_sentence(g, region_names, camera_names) for g in gaps if after_of[g.id] == i)
    return out


def _attempt(writer: Writer, ledger: VisitLedger, failures: list[str] | None, n: int):
    try:
        raw = writer(ledger, failures)
    except Exception as exc:  # any writer failure is a failed draft, never a blank card
        log.warning("story writer failed on attempt %d: %s", n, type(exc).__name__)
        return None, ValidationResult(
            passed=False,
            failures=[
                ValidationFailure(check="schema", detail=f"writer error: {type(exc).__name__}")
            ],
            attempt=n,
        )
    result = validate(raw, ledger, attempt=n)
    draft, _ = _parse(raw)
    return draft, result


def run_story(
    ledger: VisitLedger,
    writer: Writer | None,
    templates: TemplateFn = template_story,
    *,
    region_names: Mapping[str, str] | None = None,
) -> StoryOutcome:
    """Writer -> validate -> retry once with reasons -> template. Gap sentences by code."""
    gaps = _visit_gaps(ledger)
    validations: list[ValidationResult] = []
    failures: list[str] | None = None
    if writer is not None:
        for n in range(1, MAX_ATTEMPTS + 1):
            draft, result = _attempt(writer, ledger, failures, n)
            validations.append(result)
            if result.passed and draft is not None:
                sentences = insert_gap_sentences(
                    draft.sentences,
                    gaps,
                    ledger.events,
                    draft.gap_after_sentence,
                    region_names,
                    ledger.camera_names,
                )
                return StoryOutcome(
                    sentences=sentences,
                    source="wonder",
                    draft=draft,
                    proposal=draft.verdict_proposal,
                    proposal_cited=_proposal_cited(draft, result),
                    watch_proposals=list(draft.watch_proposals),
                    validations=validations,
                )
            failures = failure_reasons(result)
            log.info("story draft %d rejected: %s", n, "; ".join(failures))

    sentences = insert_gap_sentences(
        templates(ledger), gaps, ledger.events, (), region_names, ledger.camera_names
    )
    return StoryOutcome(sentences=sentences, source="template", validations=validations)
