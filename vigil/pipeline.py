"""The offline pipeline end to end (spec 5.4, 5.5, 5.7; FR-004 to FR-016, FR-020, FR-039).

``run_scenario`` composes the real modules over already-produced perception inputs:

    windows -> SAM objects (injected source, or recorded wire text parsed by vigil.meta.sam)
    -> perception.tracks.stitch -> perception.events.build_events (events, plus each track's
    FR-008 ``origin_zone`` from the observed spans of the windows) -> appearance notes
    -> optional 3D positions (vigil.spatial.locate, when calibrations and ground are given)
    -> reasoning.visits.assemble_visits (links, gaps and the FR-044 subject chains with their
    ``actor_role``/``role_basis``, using the owner's Expected Windows and check-ins)
    -> reasoning.rules.evaluate_rules (``applies_to`` against each event's role, 9.4 floor)
    -> reasoning.triage (forced by code, or the injected model) -> reasoning.story.run_story
    (injected Wonder writer when escalated, else the template; the ledger carries the
    visit's subjects for validator check 7) -> reasoning.verdict.compose
    -> reasoning.loop.accept_watches for the watch proposals of a validated draft.

Every model call is injected, so tests replay recorded answers and nothing here touches the
network. The result is plain JSON (sorted, rounded) and ``write_visits_json`` writes it
byte-for-byte reproducibly (NFR-011).

``process_session`` is the ``vigil process`` entry. It only runs on recorded inputs for now
and raises ``RuntimeError("blocked: ...")`` naming what is missing (footage T-07; SAM via
credits or the local GPU, H-02). ``upload_window`` is the only upload path and runs the
spec 5.8 pre-upload privacy check first.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vigil.models import (
    Appearance,
    Calibration,
    CameraAiEvent,
    CameraCfg,
    CheckIn,
    Config,
    Event,
    ExpectedWindow,
    Gap,
    Position,
    ProtectedObject,
    Rule,
    RuleHit,
    SamObject,
    StoryDraft,
    Subject,
    Track,
    TriageDecision,
    ValidationResult,
    Visit,
    VisitLedger,
    VisitSummary,
    Watch,
    Window,
)
from vigil.reasoning.visits import Outage

log = logging.getLogger(__name__)

BASE_PHRASES: tuple[str, ...] = ("person", "car")
"""SAM 3.1 noun phrases asked for every active window (FR-006); active watches add more."""
FLOAT_DIGITS = 6
"""Every float in the result is rounded to this many decimals (NFR-011)."""
SUBJECT_CLASSES = ("person", "car")
"""Track classes that get 3D positions (people and vehicles move; objects do not)."""

SamSource = Callable[[Window, str], Sequence[SamObject]]
"""(window, noun phrase) -> SAM objects, e.g. a wrapper over vigil.meta.sam.track_concept."""
NotesSource = Mapping[str, Any] | Callable[[list[Track]], Mapping[str, Any]]
"""Appearance notes keyed by burned-in tag or track id, or a callable producing them (Spark)."""
TriageModel = Callable[[VisitSummary], TriageDecision]
Writer = Callable[[VisitLedger, list[str] | None], Any]


class ScenarioInputs(BaseModel):
    """Already-produced perception inputs for one run (module-local contract)."""

    model_config = ConfigDict(extra="forbid")

    scenario: str | None = None
    windows: list[Window] = Field(default_factory=list)
    sam_outputs: dict[str, dict[str, str | list[Any]]] = Field(default_factory=dict)
    """Recorded SAM answers: window id -> noun phrase -> wire text (or Responses events)."""
    sam_objects: list[SamObject] = Field(default_factory=list)
    """SAM objects that were already parsed (added to whatever ``sam_outputs`` yield)."""
    camera_ai_events: list[CameraAiEvent] = Field(default_factory=list)
    outages: list[Outage] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# JSON helpers (NFR-011)
# ---------------------------------------------------------------------------


def _canon(x: Any) -> Any:
    """Plain JSON with every float rounded to FLOAT_DIGITS (and -0.0 folded to 0.0)."""
    if isinstance(x, BaseModel):
        return _canon(x.model_dump(mode="json", by_alias=True))
    if isinstance(x, float):
        r = round(x, FLOAT_DIGITS)
        return 0.0 if r == 0 else r
    if isinstance(x, dict):
        return {str(k): _canon(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_canon(v) for v in x]
    if isinstance(x, datetime):
        return x.isoformat()
    return x


def canonical_json(result: Mapping[str, Any]) -> str:
    """Sorted keys, rounded floats, one trailing newline."""
    return json.dumps(_canon(dict(result)), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def write_visits_json(result: Mapping[str, Any], path: Path | str) -> Path:
    """Write the pipeline result as canonical JSON (byte-identical across runs, NFR-011)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(result), encoding="utf-8", newline="\n")
    return path


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _watch_live(w: Watch, at: datetime) -> bool:
    from vigil.reasoning.loop import is_active

    return is_active(w, at)


def phrases_for(window: Window, watches: Iterable[Watch], session_start: datetime) -> list[str]:
    """``person``, ``car`` plus every watch active on the window's camera at its start."""
    at = session_start + timedelta(seconds=window.t0)
    extra = sorted(
        {
            " ".join(w.phrase.split()).lower()
            for w in watches
            if w.camera_id == window.camera_id and _watch_live(w, at)
        }
        - set(BASE_PHRASES)
    )
    return [*BASE_PHRASES, *extra]


def _sam_objects(
    inputs: ScenarioInputs,
    windows: list[Window],
    watches: Sequence[Watch],
    session_start: datetime,
    sam: SamSource | None,
) -> tuple[list[SamObject], list[str]]:
    from vigil.meta.sam import parse_video_output

    objs: list[SamObject] = []
    missing: list[str] = []
    for w in windows:
        if w.status == "idle":  # motion gate: no model call for idle windows (FR-005)
            continue
        for phrase in phrases_for(w, watches, session_start):
            if sam is not None:
                objs.extend(sam(w, phrase))
                continue
            recorded = inputs.sam_outputs.get(w.id, {})
            if phrase not in recorded:
                missing.append(f"{w.id}/{phrase}")
                continue
            objs.extend(parse_video_output(recorded[phrase], w, phrase))
    objs.extend(inputs.sam_objects)
    by_window = {w.id: w for w in windows}
    out = []
    for o in objs:
        w = by_window.get(o.window_id)
        if (o.width is None or o.height is None) and w is not None:
            o = o.model_copy(update={"width": w.width, "height": w.height})
        out.append(o)
    return out, missing


def _notes(notes: NotesSource | None, tracks: list[Track]) -> dict[str, Appearance]:
    """Notes keyed by track id (Spark answers by burned-in tag)."""
    if notes is None:
        return {}
    raw = notes(tracks) if callable(notes) else notes
    by_tag = {t.tag: t.id for t in tracks if t.tag}
    out: dict[str, Appearance] = {}
    for key, val in raw.items():
        app = val if isinstance(val, Appearance) else Appearance.model_validate(val)
        out[by_tag.get(key, key)] = app
    return out


def _seed(track_id: str) -> int:
    return int.from_bytes(hashlib.blake2b(track_id.encode(), digest_size=8).digest(), "big")


def _positions(
    tracks: list[Track],
    calibrations: Mapping[str, Calibration] | Sequence[Calibration] | None,
    ground: Any,
) -> list[Position]:
    if not calibrations or ground is None:
        return []
    from vigil.spatial.locate import locate_track

    cals = (
        dict(calibrations)
        if isinstance(calibrations, Mapping)
        else {c.camera_id: c for c in calibrations}
    )
    out: list[Position] = []
    for t in sorted(tracks, key=lambda t: t.id):
        cal = cals.get(t.camera_id)
        if cal is None or t.cls not in SUBJECT_CLASSES or not t.frames:
            continue
        rng = np.random.default_rng(_seed(t.id))  # reproducible r95 (NFR-011)
        out.extend(locate_track(t.frames, cal, ground, rng, track_id=t.id))
    return out


class _RecordingWriter:
    """Wraps the Wonder writer to keep every raw draft for the trace (rejected ones too)."""

    def __init__(self, writer: Writer) -> None:
        self.writer = writer
        self.raw: list[Any] = []

    def __call__(self, ledger: VisitLedger, failures: list[str] | None) -> Any:
        try:
            out = self.writer(ledger, failures)
        except Exception:
            self.raw.append(None)  # run_story records this attempt as a failed draft
            raise
        self.raw.append(out)
        return out


def _draft_record(raw: Any, result: ValidationResult) -> dict[str, Any]:
    from vigil.reasoning.validator import _parse

    draft, _ = _parse(raw)
    sentences: list[Any]
    if isinstance(draft, StoryDraft):
        sentences = [s.model_dump(include={"text", "event_ids"}) for s in draft.sentences]
    elif isinstance(raw, dict):
        sentences = list(raw.get("sentences") or [])
    else:
        sentences = []
    return {
        "attempt": result.attempt,
        "passed": result.passed,
        "sentences": sentences,
        "failures": [f.model_dump() for f in result.failures],
    }


def _link_end(track: Track) -> dict[str, Any]:
    return {
        "track_id": track.id,
        "camera_id": track.camera_id,
        "t0": track.t_first,
        "t1": track.t_last,
    }


def _track_row(t: Track) -> dict[str, Any]:
    return {
        "id": t.id,
        "camera_id": t.camera_id,
        "cls": t.cls,
        "t_first": t.t_first,
        "t_last": t.t_last,
        "tag": t.tag,
        "phrase": t.phrase,
        "window_ids": list(t.window_ids),
        "n_frames": len(t.frames),
        "masks": sum(1 for f in t.frames if f.mask_rle),
        "origin_zone": t.origin_zone,
    }


def _observation(windows: Sequence[Window], sam_missing: Sequence[str], outages: Sequence[Any]):
    """Observed spans per camera for FR-008 origin tagging (None when no windows exist).

    A window whose recorded SAM answer for a base phrase is missing was not processed, so it
    counts as ``failed`` (not observed); idle windows were skipped by the motion gate.
    """
    from vigil.perception.events import Observation

    if not windows:
        return None
    lacking = {m.split("/", 1)[0] for m in sam_missing if m.split("/", 1)[1] in BASE_PHRASES}
    marked = [
        w.model_copy(update={"status": "failed"}) if w.id in lacking and w.status != "idle" else w
        for w in windows
    ]
    return Observation.from_windows(marked, outages)


def _rules_excluded(
    v_events: Sequence[Event],
    rules: Sequence[Rule],
    subjects: Mapping[str, Subject],
    tz: str,
    session_start: datetime,
    watches: Sequence[Watch],
) -> list[dict[str, Any]]:
    """Rules in force on an event that did not fire because of ``applies_to`` (A′ trace)."""
    from vigil.reasoning.rules import applies, in_force, role_of

    out: list[dict[str, Any]] = []
    for e in v_events:
        for rule in rules:
            if not in_force(rule, e, tz, session_start, watches) or applies(rule, e):
                continue
            s = subjects.get(e.subject_id or "")
            out.append(
                {
                    "rule_id": rule.id,
                    "event_id": e.id,
                    "applies_to": rule.applies_to,
                    "actor_role": role_of(e),
                    "subject_id": e.subject_id,
                    "role_basis": s.role_basis if s is not None else None,
                }
            )
    return out


# ---------------------------------------------------------------------------
# run_scenario
# ---------------------------------------------------------------------------


def run_scenario(
    inputs: ScenarioInputs | Mapping[str, Any],
    *,
    cfg: Config,
    rules: Sequence[Rule],
    protected: Sequence[ProtectedObject],
    watches: Sequence[Watch],
    session_start: datetime,
    sam: SamSource | None = None,
    notes: NotesSource | None = None,
    writer: Writer | None = None,
    triage_model: TriageModel | None = None,
    calibrations: Mapping[str, Calibration] | Sequence[Calibration] | None = None,
    ground: Any = None,
    allowlist: Iterable[str] | None = None,
    expected_windows: Sequence[ExpectedWindow] = (),
    checkins: Sequence[CheckIn] = (),
    replay_bindings: Mapping[str, tuple[str, float, str]] | None = None,
) -> dict[str, Any]:
    """Run the offline pipeline over one session's windows and return a JSON-able result.

    ``session_start`` must be timezone-aware (rules with time windows, Expected Windows and
    check-ins need it). ``sam`` is a ``(window, phrase) -> SamObjects`` source; without it,
    recorded ``inputs.sam_outputs`` are parsed (a missing window/phrase is listed in
    ``result["sam_missing"]``, and that window counts as unobserved for FR-008 origins).
    ``writer`` is the Wonder stand-in, only called for escalated visits. ``allowlist``
    defaults to ``config/allowlist.json``. ``expected_windows`` (FR-029) and ``checkins``
    (FR-044 step 2) feed the role rules; without them steps 2 and 3 never match.
    """
    from vigil.perception.events import build_events
    from vigil.perception.tracks import stitch
    from vigil.reasoning.loop import accept_watches, load_allowlist
    from vigil.reasoning.rules import evaluate_rules
    from vigil.reasoning.story import region_names_from, run_story
    from vigil.reasoning.triage import decide, summarize
    from vigil.reasoning.verdict import compose, has_unresolved_gap
    from vigil.reasoning.visits import assemble_visits
    from vigil.spatial.locate import filter_gaps

    if session_start.tzinfo is None or session_start.utcoffset() is None:
        raise ValueError("session_start must be timezone-aware")
    inp = inputs if isinstance(inputs, ScenarioInputs) else ScenarioInputs.model_validate(inputs)
    windows = sorted(inp.windows, key=lambda w: (w.camera_id, w.t0, w.id))
    cams = {c.id: c for c in cfg.cameras}
    allowed = set(allowlist) if allowlist is not None else load_allowlist()
    protected = sorted(protected, key=lambda p: p.id)
    watches = sorted(watches, key=lambda w: w.id)
    protected_ids = {p.id for p in protected}
    expected_windows = sorted(expected_windows, key=lambda w: (w.start, w.id))
    checkins = sorted(checkins, key=lambda c: (c.start, c.id))

    # perception ------------------------------------------------------------
    objs, sam_missing = _sam_objects(inp, windows, watches, session_start, sam)
    tracks = stitch(objs, frame_height={c.id: c.height for c in cfg.cameras})
    observation = _observation(windows, sam_missing, inp.outages)
    events = build_events(
        tracks,
        cfg,
        list(protected),
        list(watches),
        exits_as_zones=True,
        observation=observation,
        session_start=session_start,
    )
    appearance = _notes(notes, tracks)
    positions = _positions(tracks, calibrations, ground)

    # reasoning -------------------------------------------------------------
    asm = assemble_visits(
        events,
        tracks,
        appearance,
        positions,
        cfg,
        outages=inp.outages,
        windows=expected_windows,
        checkins=checkins,
        session_start=session_start,
        replay_bindings=replay_bindings,
    )
    subjects_by_id = {s.id: s for s in asm.subjects}
    by_track = {t.id: t for t in tracks}
    camera_names = {c.id: c.name for c in cfg.cameras}
    region_names = region_names_from(cfg)

    visits_out: list[dict[str, Any]] = []
    accepted_all: list[Watch] = []
    rejected_all: list[Watch] = []
    kept_positions: list[Position] = []
    in_visit: set[str] = set()
    for v in asm.visits:
        v_events = [e for e in asm.events if e.visit_id == v.id]
        v_gaps = [g for g in asm.gaps if g.visit_id == v.id]
        rr = evaluate_rules(
            v,
            asm.events,
            rules,
            cfg.timezone,
            session_start,
            protected_ids=protected_ids,
            watches=watches,
        )
        # a 9.4 case-2 household touch (rr.scoped_out) neither raises the floor nor forces
        # escalation; summarize() reads it from the RuleOutcome
        summary = summarize(v, asm.events, asm.gaps, rr, protected_ids=protected_ids, tracks=tracks)
        decision = decide(summary, triage_model)
        visit = v.model_copy(update={"floor": rr.floor, "scenario": inp.scenario})
        v_subjects = [s for s in asm.subjects if s.visit_id == v.id]
        excluded = _rules_excluded(
            v_events, rules, subjects_by_id, cfg.timezone, session_start, watches
        )
        ledger = VisitLedger(
            visit=visit,
            events=v_events,
            gaps=v_gaps,
            protected_objects=list(protected),
            rule_hits=rr.hits,
            appearance={tid: appearance[tid] for tid in v.track_ids if tid in appearance},
            camera_names=camera_names,
            region_names=region_names,
            subjects=v_subjects,
            timezone=cfg.timezone,
            session_start=session_start,
        )
        recorder = _RecordingWriter(writer) if (decision.escalate and writer) else None
        outcome = run_story(ledger, recorder, region_names=region_names)
        unresolved = has_unresolved_gap(v_gaps)
        verdict = compose(rr.floor, unresolved, outcome.proposal, outcome.proposal_cited)

        loop_accepted: list[Watch] = []
        loop_rejected: list[Watch] = []
        if outcome.source == "wonder" and outcome.watch_proposals:
            loop = accept_watches(
                outcome.watch_proposals,
                list(cams),
                allowed,
                [*watches, *accepted_all],
                session_start + timedelta(seconds=v.t1),
                v.id,
                validated=True,
                visit_event_ids=set(v.event_ids),
            )
            loop_accepted, loop_rejected = loop.accepted, loop.rejected
            accepted_all += loop_accepted
            rejected_all += loop_rejected

        tracks_here = set(v.track_ids) | {e.track_id for e in v_events}
        in_visit |= tracks_here
        v_positions = filter_gaps((p for p in positions if p.track_id in tracks_here), v_gaps)
        kept_positions += v_positions
        links = [
            {
                "from": _link_end(by_track[lk.from_track]),
                "to": _link_end(by_track[lk.to_track]),
                "gap_s": lk.gap_s,
                "blind": lk.blind,
                "region_id": lk.region_id,
                "route_kind": lk.route_kind,
            }
            for lk in asm.links
            if lk.from_track in v.track_ids and lk.from_track in by_track
        ]
        drafts = (
            [
                _draft_record(raw, res)
                for raw, res in zip(recorder.raw, outcome.validations, strict=True)
            ]
            if recorder is not None
            else []
        )
        final = visit.model_copy(
            update={
                "state": "published" if v.state == "closed" else v.state,
                "proposal": outcome.proposal,
                "verdict": verdict,
                "escalated": decision.escalate,
                "story": outcome.sentences,
            }
        )
        visits_out.append(
            {
                **final.model_dump(mode="json"),
                "forced": decision.forced,
                "triage": decision.model_dump(mode="json"),
                "summary": summary.model_dump(mode="json"),
                "story_source": outcome.source,
                "events": [e.model_dump(mode="json") for e in v_events],
                "gaps": [g.model_dump(mode="json") for g in v_gaps],
                "rule_hits": [h.model_dump(mode="json") for h in rr.hits],
                "rules_excluded": excluded,
                "scoped_out": list(rr.scoped_out),
                "subjects": [s.model_dump(mode="json") for s in v_subjects],
                "links": links,
                "positions": [p.model_dump(mode="json") for p in v_positions],
                "validations": [r.model_dump(mode="json") for r in outcome.validations],
                "drafts": drafts,
                "verdict_inputs": {
                    "floor": rr.floor,
                    "unresolved_gap": unresolved,
                    "proposal": outcome.proposal,
                    "proposal_cited": outcome.proposal_cited,
                    "result": verdict,
                },
                "watch_proposals": [p.model_dump(mode="json") for p in outcome.watch_proposals],
                "watches": {
                    "accepted": [w.model_dump(mode="json") for w in loop_accepted],
                    "rejected": [w.model_dump(mode="json") for w in loop_rejected],
                },
            }
        )

    kept_positions += [p for p in positions if p.track_id not in in_visit]
    kept_positions.sort(key=lambda p: (p.t, p.track_id, p.cameras))
    result = {
        "scenario": inp.scenario,
        "session_start": session_start.isoformat(),
        "timezone": cfg.timezone,
        "motion_triggers": sum(1 for w in windows if w.trigger == "motion"),
        "windows": [
            {
                "id": w.id,
                "camera_id": w.camera_id,
                "t0": w.t0,
                "t1": w.t1,
                "trigger": w.trigger,
                "status": "idle" if w.status == "idle" else "processed",
            }
            for w in windows
        ],
        "sam_missing": sam_missing,
        "tracks": [_track_row(t) for t in sorted(tracks, key=lambda t: t.id)],
        "events": [e.model_dump(mode="json") for e in asm.events],
        "gaps": [g.model_dump(mode="json") for g in asm.gaps],
        "subjects": [s.model_dump(mode="json") for s in asm.subjects],
        "expected_windows": [w.model_dump(mode="json") for w in expected_windows],
        "checkins": [c.model_dump(mode="json") for c in asm.checkins],
        "positions": [p.model_dump(mode="json") for p in kept_positions],
        "camera_ai_events": [
            e.model_dump(mode="json") for e in sorted(inp.camera_ai_events, key=lambda e: e.id)
        ],
        "watches": {
            "accepted": [w.model_dump(mode="json") for w in accepted_all],
            "rejected": [w.model_dump(mode="json") for w in rejected_all],
        },
        "visits": visits_out,
    }
    from vigil.perception.overlays import overlay_json

    result["overlays"] = overlay_json(tracks, {c.id: (c.width, c.height) for c in cfg.cameras})
    return _canon(result)


# ---------------------------------------------------------------------------
# Store, bundle trace
# ---------------------------------------------------------------------------


def store_result(
    db_path: Path | str,
    result: Mapping[str, Any],
    *,
    cfg: Config,
    rules: Sequence[Rule] = (),
    protected: Sequence[ProtectedObject] = (),
) -> Path:
    """Write a pipeline result into a fresh SQLite DB (spec 9.3) for ``vigil export``."""
    from vigil.store import db

    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    conn = db.open_db(db_path)
    try:
        _store(conn, result, cfg, rules, protected)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _store(
    conn: sqlite3.Connection,
    result: Mapping[str, Any],
    cfg: Config,
    rules: Sequence[Rule],
    protected: Sequence[ProtectedObject],
) -> None:
    from vigil.store import db

    for cam in cfg.cameras:
        db.insert_camera(conn, cam)
    for call in result.get("model_calls", []):
        from vigil.models import ModelCall

        db.insert_model_call(conn, ModelCall.model_validate(call))
    for w in result.get("windows", []):
        db.insert_window(conn, Window.model_validate(w))
    for e in result.get("camera_ai_events", []):
        db.insert_camera_ai_event(conn, CameraAiEvent.model_validate(e))
    for t in result.get("tracks", []):
        db.insert_track(
            conn,
            Track(
                id=t["id"],
                camera_id=t["camera_id"],
                cls=t["cls"],
                t_first=t["t_first"],
                t_last=t["t_last"],
                window_ids=t.get("window_ids", []),
                tag=t.get("tag"),
                phrase=t.get("phrase"),
                origin_zone=t.get("origin_zone"),
            ),
        )
    for p in result.get("positions", []):
        db.insert_position(conn, Position.model_validate(p))
    for track_id, notes in result.get("appearance", {}).items():
        db.insert_appearance(
            conn,
            track_id,
            Appearance.model_validate(notes),
            result.get("appearance_calls", {}).get(track_id, ""),
        )
    for w in result.get("expected_windows", []):
        db.insert_expected_window(conn, ExpectedWindow.model_validate(w))
    for c in result.get("checkins", []):
        db.insert_checkin(conn, CheckIn.model_validate(c))
    for po in protected:
        db.insert_protected_object(conn, po)
    for r in rules:
        db.insert_rule(conn, r, "default" if r.id.startswith("r_") else "owner")
    for e in result.get("events", []):
        db.insert_event(conn, Event.model_validate(e))
    for g in result.get("gaps", []):
        db.insert_gap(conn, Gap.model_validate(g))
    for kind in ("accepted", "rejected"):
        for w in result.get("watches", {}).get(kind, []):
            db.insert_watch(conn, Watch.model_validate(w))
    fields = set(Visit.model_fields)
    for v in result.get("visits", []):
        db.insert_visit(conn, Visit.model_validate({k: v[k] for k in fields if k in v}))
        for s in v.get("subjects", []):
            db.insert_subject(conn, Subject.model_validate(s))
        for h in v.get("rule_hits", []):
            db.insert_rule_hit(conn, RuleHit.model_validate(h))
        for r in v.get("validations", []):
            db.insert_validation(conn, v["id"], ValidationResult.model_validate(r))


def bundle_trace(result: Mapping[str, Any]) -> dict[str, Any]:
    """Per-visit "How this was decided" trace for ``export_bundle(trace=...)``."""
    out: dict[str, Any] = {}
    for v in result.get("visits", []):
        out[v["id"]] = {
            "triage": v.get("triage"),
            "drafts": v.get("drafts", []),
            "gap_sentences": [s["gap_id"] for s in v.get("story", []) if s.get("gap_id")],
            "verdict_inputs": v.get("verdict_inputs"),
            "watch_proposals": v.get("watch_proposals", []),
            "subjects": [
                {k: s[k] for k in ("id", "track_ids", "actor_role", "role_basis")}
                for s in v.get("subjects", [])
            ],
            "rules_excluded": v.get("rules_excluded", []),
            "scoped_out": v.get("scoped_out", []),
        }
    return out


# ---------------------------------------------------------------------------
# Upload (spec 5.8 privacy boundary)
# ---------------------------------------------------------------------------


class Uploader(Protocol):
    def upload(self, path: Path) -> str: ...


def upload_window(client: Uploader, window: Window, cam: CameraCfg) -> str:
    """Upload a masked window once; the pre-upload privacy check runs first (spec 5.8).

    Raises ``vigil.ingest.privacy.PrivacyViolation`` (and uploads nothing) when any pixel
    inside the camera's privacy polygons is not black or the file has an audio stream.
    """
    from vigil.ingest.privacy import assert_uploadable

    if window.file_id:
        return window.file_id
    if not window.path:
        raise ValueError(f"window {window.id} has no file to upload")
    if window.camera_id != cam.id:
        raise ValueError(f"window {window.id} is on {window.camera_id}, not {cam.id}")
    assert_uploadable(window.path, cam.privacy, ref_size=(cam.width, cam.height))
    window.file_id = client.upload(Path(window.path))
    return window.file_id


# ---------------------------------------------------------------------------
# vigil process
# ---------------------------------------------------------------------------


def _blocked(msg: str) -> RuntimeError:
    return RuntimeError(f"blocked: {msg}")


def _recorded_sam(sam_dir: Path, windows: list[Window]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for w in windows:
        wdir = sam_dir / w.id
        if not wdir.is_dir():
            continue
        for f in sorted(wdir.iterdir()):
            if f.suffix == ".txt":
                out.setdefault(w.id, {})[f.stem] = f.read_text(encoding="utf-8")
            elif f.suffix == ".json":
                out.setdefault(w.id, {})[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return out


def _owner_records(settings, expected, checkins, *, session, session_start):
    """Merge persistent owner state; a cancellation or consumed check-in wins over a file."""
    path = getattr(settings, "db_path", None)
    if settings.mode != "edge" or path is None or not Path(path).exists():
        return expected, checkins, {}
    from vigil.store import db

    conn = db.connect(path)
    try:
        windows = {w.id: w for w in expected}
        windows.update({w.id: w for w in db.expected_windows(conn)})
        taps = {c.id: c for c in checkins}
        taps.update({c.id: c for c in db.checkins(conn)})
        replay = {}
        prior_path = settings.data_dir / "results" / session / "visits.json"
        try:
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
            same_session = (
                prior.get("scenario") == session
                and datetime.fromisoformat(prior["session_start"]) == session_start
            )
            track_rows = {t["id"]: t for t in prior.get("tracks", [])}
            prior_taps = {c["id"]: c for c in prior.get("checkins", [])}
            if same_session:
                for subject in prior.get("subjects", []):
                    basis = subject.get("role_basis", "")
                    cid = basis.removeprefix("checkin:")
                    tap = taps.get(cid)
                    ids = subject.get("track_ids", [])
                    if (
                        basis.startswith("checkin:")
                        and tap
                        and not tap.revoked
                        and ids
                        and tap.bound_subject == subject["id"]
                        and prior_taps.get(cid, {}).get("bound_subject") == subject["id"]
                        and ids[0] in track_rows
                    ):
                        replay[cid] = (ids[0], track_rows[ids[0]]["t_first"], subject["id"])
        except (OSError, ValueError, KeyError, TypeError):
            pass  # no trustworthy same-session replay: consumed taps stay consumed
        return list(windows.values()), list(taps.values()), replay
    finally:
        conn.close()


def _save_owner_bindings(settings, result, replay_bindings):
    path = getattr(settings, "db_path", None)
    if settings.mode != "edge" or path is None or not Path(path).exists():
        return
    from vigil.store import db

    conn = db.connect(path)
    try:
        with conn:
            for tap in result.get("checkins", []):
                if tap.get("bound_subject"):
                    conn.execute(
                        "UPDATE checkins SET bound_subject=? WHERE id=? "
                        "AND (bound_subject IS NULL OR bound_subject=?)",
                        (
                            tap["bound_subject"],
                            tap["id"],
                            replay_bindings.get(tap["id"], (None, None, None))[2],
                        ),
                    )
    finally:
        conn.close()


def process_session(
    session: str,
    *,
    confirm: bool = False,
    settings: Any = None,
    cloud: bool = False,
    client: Any = None,
    report=None,
) -> dict:
    """Process recorded inputs, or explicitly opt into the complete cloud adapters.

    Layout under ``settings.data_dir`` (gitignored):

    - ``windows/<session>/windows.json``: the cut windows (``vigil ingest``);
    - ``windows/<session>/session.json``: ``{"session_start": ISO-8601 with offset}`` plus
      optional ``protected_objects``, ``rules`` (owner rules, added to the defaults),
      ``watches``, ``expected_windows`` (FR-029, set by the owner before they start) and
      ``checkins`` (FR-044 step 2, "I'm outside" taps from the LAN app);
    - ``sam/<session>/<window id>/<phrase>.txt`` (wire text) or ``.json`` (Responses events):
      recorded SAM 3.1 answers.

    Writes ``results/<session>/visits.json``. The default path only parses recordings.
    ``cloud=True`` (CLI --cloud), or an injected client in tests, uses MetaClient for SAM,
    Spark and Wonder; sandbox/cache-only settings still prohibit network. It prints an
    estimate before any upload and requires ``confirm`` above $5. The cloud result is
    stored at ``results/<session>/result.sqlite``, preserving the owner's persistent DB.
    """
    from vigil.ingest.config import load_config
    from vigil.reasoning.rules import load_rules
    from vigil.settings import get_settings

    settings = settings or get_settings()
    if not session or Path(session).name != session or session in {".", ".."}:
        raise ValueError("invalid session name")
    data = Path(settings.data_dir)
    wdir = data / "windows" / session
    wfile = wdir / "windows.json"
    if not wfile.exists():
        has_clips = wdir.is_dir() and any(wdir.glob("*.mp4"))
        detail = (
            f"{wdir} has clips but no windows.json (run `vigil ingest` to write it)"
            if has_clips
            else f"no windows in {wdir}"
        )
        raise _blocked(
            f"{detail}. Record the evening's footage (T-07) and cut it into masked windows "
            "with `vigil ingest` first."
        )
    windows = [Window.model_validate(w) for w in json.loads(wfile.read_text(encoding="utf-8"))]
    if not windows:
        raise _blocked(f"{wfile} lists no windows; record footage (T-07) and run `vigil ingest`.")
    sam_dir = data / "sam" / session
    recorded = _recorded_sam(sam_dir, windows)
    active = [w for w in windows if w.status != "idle"]
    lacking = [w.id for w in active if not all(p in recorded.get(w.id, {}) for p in BASE_PHRASES)]
    if (not recorded or lacking) and not (cloud or client is not None):
        n = len(lacking) if recorded else len(active)
        raise _blocked(
            f"{n} of {len(active)} active windows have no recorded SAM 3.1 answers in {sam_dir}. "
            "SAM needs API credits (budget guard, `vigil process --confirm` once the live path "
            "is wired) or the local GPU backend (H-02); this offline entry never calls the "
            "network."
        )
    meta_file = wdir / "session.json"
    if not meta_file.exists():
        raise _blocked(f"{meta_file} is missing: the session start time (with UTC offset).")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    session_start = datetime.fromisoformat(meta["session_start"])
    cfg = load_config(settings.config_path)
    from vigil.ingest.config import privacy_polygons

    cfg = cfg.model_copy(
        update={
            "cameras": [
                c.model_copy(
                    update={
                        "privacy": privacy_polygons(
                            cfg, c.id, settings.config_path.parent / "privacy"
                        )
                    }
                )
                for c in cfg.cameras
            ]
        }
    )
    rules = [*load_rules(), *(Rule.model_validate(r) for r in meta.get("rules", []))]
    protected = [ProtectedObject.model_validate(p) for p in meta.get("protected_objects", [])]
    watches = [Watch.model_validate(w) for w in meta.get("watches", [])]
    expected = [ExpectedWindow.model_validate(w) for w in meta.get("expected_windows", [])]
    checkins = [CheckIn.model_validate(c) for c in meta.get("checkins", [])]
    expected, checkins, replay_bindings = _owner_records(
        settings, expected, checkins, session=session, session_start=session_start
    )
    result_dir = data / "results" / session
    calibrations, ground = None, None
    spatial_model = data / "spatial" / "model.glb"
    calibration_file = settings.config_path.parent / "calibration.json"
    if spatial_model.exists() and calibration_file.exists():
        from vigil.spatial.calibrate import load_calibrations
        from vigil.spatial.glb import load_glb_scene

        ground = load_glb_scene(spatial_model)
        calibrations = load_calibrations(calibration_file)
    if cloud or client is not None:
        from vigil.cloud import run_cloud
        from vigil.meta.client import MetaClient

        for w in active:
            cam = cfg.camera(w.camera_id)
            if not cam.privacy and not cam.privacy_none_needed:
                raise _blocked(
                    f"camera {cam.id}: privacy polygons required or privacy: none_needed"
                )
        own_client = client is None
        if own_client:
            client = MetaClient(
                settings, cache_only=settings.meta_cache_only or settings.mode == "sandbox"
            )
        try:
            result = run_cloud(
                client=client,
                windows=windows,
                cfg=cfg,
                session=session,
                session_start=session_start,
                result_dir=result_dir,
                rules=rules,
                protected=protected,
                watches=watches,
                expected=expected,
                checkins=checkins,
                confirm=confirm,
                report=report,
                calibrations=calibrations,
                ground=ground,
                replay_bindings=replay_bindings,
            )
        finally:
            if own_client:
                client.close()
        result["db_path"] = str(result_dir / "result.sqlite")
        store_result(result["db_path"], result, cfg=cfg, rules=rules, protected=protected)
        write_visits_json(result, result_dir / "visits.json")
        _save_owner_bindings(settings, result, replay_bindings)
        return result
    result = run_scenario(
        {"scenario": session, "windows": windows, "sam_outputs": recorded},
        cfg=cfg,
        rules=rules,
        protected=protected,
        watches=watches,
        session_start=session_start,
        expected_windows=expected,
        checkins=checkins,
        calibrations=calibrations,
        ground=ground,
        replay_bindings=replay_bindings,
    )
    write_visits_json(result, data / "results" / session / "visits.json")
    _save_owner_bindings(settings, result, replay_bindings)
    return result
