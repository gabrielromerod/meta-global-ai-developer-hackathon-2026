"""EVAL metrics against pre-registered labels (FR-024, FR-013, FR-011, NFR-023).

Labels (`eval/labels/<scenario>.json`, schema `ScenarioLabel`) are committed before any
pipeline run; results are the pipeline's per-scenario output (schema in
`eval/labels/README.md`). `compute_metrics()` is pure and deterministic.

Definitions (pre-registered with the targets in EVAL.md):

- **Alert**: a visit whose verdict is `needs_attention` (only rules can produce it).
  **Alert reduction** = 1 - alerts / motion triggers, over all scenarios.
- **Correct verdict**: a scenario's most severe visit verdict equals its labelled
  verdict (order normal < noteworthy < cant_confirm < needs_attention). A scenario with
  no visits has verdict normal; a scenario with no result counts as incorrect.
- **Link precision**: of the cross-window/cross-camera links the system made, the share
  whose two ends overlap appearances of the same labelled subject.
- **Claims inside gaps**: story sentences (not code-written gap sentences) that cite an
  event overlapping the interior of a gap (labelled or system) by more than 0.5 s.
  Positions inside gaps are counted separately (FR-039).
- **Uncited sentences shipped**: sentences with no event id and no gap id.
- **Escalation rate** (FR-013) = escalated visits / visits.
- **Gap match** (FR-011): a labelled gap matched by a system gap whose start and end are
  each within 1 s.
- **Reolink/SAM agreement** (spec 6): share of Reolink person events overlapped by a SAM
  person track on the same camera.
- **Roles** (FR-044): each labelled subject with a ``role`` is compared with every system
  subject chain (``result["subjects"]``, else the visits' ``subjects``) whose tracks of the
  same class overlap its appearances on the same camera. It is correct when all of them hold
  the labelled role (a chain split at a gap counts every part). **Role miss rate** = labelled
  ``household_insider`` subjects not assigned ``household_insider`` / labelled household
  subjects, also split by lighting (day vs ``dusk``/``night_ir``). **Alerts caused** counts
  missed household subjects with a non-household part inside an alert visit. A scenario with
  no result counts every labelled role as missed (fails closed).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vigil.models import ActorRole

LABEL_SCHEMA_VERSION = 1
ALERT_VERDICTS: tuple[str, ...] = ("needs_attention",)
VERDICT_ORDER = {"normal": 0, "noteworthy": 1, "cant_confirm": 2, "needs_attention": 3}
GAP_MATCH_TOL_S = 1.0
GAP_CLAIM_TOL_S = 0.5

TARGETS: dict[str, dict[str, Any]] = {
    "alert_reduction": {"op": ">=", "value": 0.80, "text": "at least 80%"},
    "correct_verdicts": {"op": "share>=", "value": 10 / 12, "text": "at least 10 of 12"},
    "link_precision": {"op": ">=", "value": 0.90, "text": "at least 90%"},
    "claims_inside_gaps": {"op": "==", "value": 0, "text": "0"},
    "uncited_sentences_shipped": {"op": "==", "value": 0, "text": "0"},
}


# ---------------------------------------------------------------------------
# Label schema (pre-registered). No identity fields exist (NFR-003).
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Appearance(_Strict):
    camera_id: str
    t0: float
    t1: float


class LabelSubject(_Strict):
    id: str
    class_: Literal["person", "vehicle", "package", "object"] = Field(alias="class")
    appearances: list[Appearance] = Field(default_factory=list)
    role: ActorRole | None = None
    """The spatial-origin role the subject should get (FR-044), never an identity."""


class LabelGap(_Strict):
    id: str
    kind: Literal["blind_spot", "ambiguous_link", "outage"] = "blind_spot"
    t0: float
    t1: float
    region_id: str | None = None


class LabelEvent(_Strict):
    type: Literal["enter", "exit", "cross", "touch", "removed", "dwell"]
    camera_id: str
    t: float
    target: str | None = None


class ScenarioLabel(_Strict):
    schema_version: int = LABEL_SCHEMA_VERSION
    scenario: str
    title: str = ""
    session: str | None = None
    lighting: Literal["day", "dusk", "night_ir", "unknown"] = "unknown"
    expected_verdict: Literal["normal", "noteworthy", "needs_attention", "cant_confirm"]
    expected_escalated: bool | None = None
    subjects: list[LabelSubject] = Field(default_factory=list)
    gaps: list[LabelGap] = Field(default_factory=list)
    events: list[LabelEvent] = Field(default_factory=list)
    rules_fired: list[str] = Field(default_factory=list)
    labelled_by: str | None = None
    """A team role (e.g. "field lead"), never a name."""
    labelled_at: str | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 6)


def _ratio(num: float, den: float) -> float | None:
    return None if den <= 0 else _r(num / den)


def _subject_for(label: ScenarioLabel, end: dict) -> str | None:
    cam, t0, t1 = end.get("camera_id"), float(end.get("t0", 0)), float(end.get("t1", 0))
    best, best_ov = None, 0.0
    for subj in label.subjects:
        for ap in subj.appearances:
            if ap.camera_id != cam:
                continue
            ov = _overlap(t0, t1, ap.t0, ap.t1)
            if ov > best_ov or (ov == best_ov and ov > 0 and best is not None and subj.id < best):
                best, best_ov = subj.id, ov
    return best


def _visit_verdict(visits: list[dict]) -> str:
    verdicts = [v.get("verdict") or "normal" for v in visits]
    return max(verdicts, key=lambda v: VERDICT_ORDER.get(v, 0), default="normal")


def _check(name: str, value: Any, n: int | None = None) -> bool | None:
    if value is None:
        return None
    t = TARGETS[name]
    if t["op"] == ">=":
        return value >= t["value"]
    if t["op"] == "==":
        return value == t["value"]
    if t["op"] == "share>=":
        return None if not n else (value / n) >= t["value"] - 1e-9
    raise ValueError(t["op"])  # pragma: no cover


# ---------------------------------------------------------------------------
# Per-scenario and totals
# ---------------------------------------------------------------------------


NIGHT_LIGHTING = frozenset({"dusk", "night_ir"})
TRACK_CLASS = {"vehicle": "car"}
"""Label class -> pipeline track class, where they differ (a person stays a person)."""


def _role_rows(label: ScenarioLabel, result: dict, visits: list[dict]) -> list[dict]:
    """Labelled vs assigned role per labelled subject (FR-044 role miss rate)."""
    tracks = {t["id"]: t for t in result.get("tracks") or [] if "id" in t}
    subjects = list(result.get("subjects") or []) or [
        s for v in visits for s in v.get("subjects") or []
    ]
    alert_tracks = {
        tid
        for v in visits
        if (v.get("verdict") or "normal") in ALERT_VERDICTS
        for tid in v.get("track_ids") or []
    }
    rows = []
    for ls in label.subjects:
        if ls.role is None:
            continue
        hits: list[tuple[float, str, dict]] = []
        cls = TRACK_CLASS.get(ls.class_, ls.class_)
        for s in subjects:
            ov = 0.0
            for tid in s.get("track_ids") or []:
                t = tracks.get(tid)
                if t is None or t.get("cls", cls) != cls:
                    continue
                for ap in ls.appearances:
                    if ap.camera_id == t.get("camera_id"):
                        ov += _overlap(float(t["t_first"]), float(t["t_last"]), ap.t0, ap.t1)
            if ov > 0:
                hits.append((ov, str(s.get("id")), s))
        hits.sort(key=lambda h: (-h[0], h[1]))
        roles = sorted({str(s.get("actor_role") or "unknown") for _, _, s in hits})
        correct = roles == [ls.role]
        alert = any(
            str(s.get("actor_role") or "unknown") != ls.role
            and bool(set(s.get("track_ids") or []) & alert_tracks)
            for _, _, s in hits
        )
        rows.append(
            {
                "subject": ls.id,
                "labelled": ls.role,
                "assigned": str(hits[0][2].get("actor_role") or "unknown") if hits else None,
                "assigned_roles": roles,
                "role_basis": hits[0][2].get("role_basis") if hits else None,
                "correct": correct,
                "alert": alert and not correct,
            }
        )
    return rows


def _role_counts(label: ScenarioLabel, roles: list[dict] | None) -> dict[str, int]:
    labelled = [s for s in label.subjects if s.role is not None]
    household = [s for s in labelled if s.role == "household_insider"]
    if roles is None:  # no result: every labelled role counts as missed
        return {
            "roles_labelled": len(labelled),
            "roles_correct": 0,
            "household_subjects": len(household),
            "household_missed": len(household),
            "role_miss_alerts": 0,
        }
    hh = [r for r in roles if r["labelled"] == "household_insider"]
    return {
        "roles_labelled": len(roles),
        "roles_correct": sum(1 for r in roles if r["correct"]),
        "household_subjects": len(hh),
        "household_missed": sum(1 for r in hh if not r["correct"]),
        "role_miss_alerts": sum(1 for r in hh if r["alert"]),
    }


def _scenario_row(label: ScenarioLabel, result: dict | None) -> dict:
    row: dict[str, Any] = {
        "scenario": label.scenario,
        "title": label.title,
        "lighting": label.lighting,
        "expected_verdict": label.expected_verdict,
        "gaps_labelled": len(label.gaps),
    }
    if result is None:
        row.update(
            status="missing", verdict=None, correct=False, motion_triggers=0, alerts=0,
            visits=0, escalated=0, links=0, links_correct=0, claims_inside_gaps=0,
            uncited_sentences_shipped=0, positions_inside_gaps=0, sentences=0,
            gaps_matched=0, reolink_person_events=0, reolink_matched_by_sam=0, roles=[],
            **_role_counts(label, None),
        )  # fmt: skip
        return row

    visits: list[dict] = list(result.get("visits") or [])
    verdict = _visit_verdict(visits)
    alerts = sum(1 for v in visits if (v.get("verdict") or "normal") in ALERT_VERDICTS)
    escalated = sum(1 for v in visits if v.get("escalated"))

    links = links_ok = 0
    claims_in_gaps = uncited = positions_in_gaps = sentences = 0
    sys_gaps: list[dict] = []
    for v in visits:
        gaps = [(float(g["t0"]), float(g["t1"])) for g in v.get("gaps") or []]
        gaps += [(g.t0, g.t1) for g in label.gaps]
        sys_gaps.extend(v.get("gaps") or [])
        ev_times = {
            e["id"]: (float(e["t0"]), float(e.get("t1", e["t0"]))) for e in v.get("events") or []
        }
        for link in v.get("links") or []:
            links += 1
            a, b = _subject_for(label, link["from"]), _subject_for(label, link["to"])
            links_ok += int(a is not None and a == b)
        for s in v.get("story") or []:
            sentences += 1
            ids = list(s.get("event_ids") or [])
            if not ids and not s.get("gap_id"):
                uncited += 1
            if s.get("source") == "code" or s.get("gap_id"):
                continue
            inside = False
            for eid in ids:
                if eid not in ev_times:
                    continue
                e0, e1 = ev_times[eid]
                if e1 <= e0:
                    # an instant (enter/exit) on a gap's boundary is the moment the subject
                    # left or came back, not a claim about the gap's interior
                    inside |= any(g0 < e0 < g1 for g0, g1 in gaps)
                    continue
                inside |= any(
                    _overlap(e0, e1, g0, g1) > min(GAP_CLAIM_TOL_S, (e1 - e0) / 2)
                    for g0, g1 in gaps
                )
            claims_in_gaps += int(inside)
        for p in v.get("positions") or []:
            t = float(p["t"])
            positions_in_gaps += int(any(g0 < t < g1 for g0, g1 in gaps))

    gaps_matched = sum(
        1
        for lg in label.gaps
        if any(
            abs(float(g["t0"]) - lg.t0) <= GAP_MATCH_TOL_S
            and abs(float(g["t1"]) - lg.t1) <= GAP_MATCH_TOL_S
            for g in sys_gaps
        )
    )

    tracks = [t for t in result.get("tracks") or [] if t.get("cls") == "person"]
    reolink = [e for e in result.get("camera_ai_events") or [] if e.get("kind") == "person"]
    matched = 0
    for e in reolink:
        e0 = float(e["t0"])
        e1 = float(e["t1"]) if e.get("t1") is not None else e0 + 1.0
        matched += int(
            any(
                t["camera_id"] == e["camera_id"]
                and _overlap(e0, e1, float(t["t_first"]), float(t["t_last"])) > 0
                for t in tracks
            )
        )

    row.update(
        status="ok",
        verdict=verdict,
        correct=verdict == label.expected_verdict,
        motion_triggers=int(result.get("motion_triggers") or 0),
        alerts=alerts,
        visits=len(visits),
        escalated=escalated,
        links=links,
        links_correct=links_ok,
        claims_inside_gaps=claims_in_gaps,
        uncited_sentences_shipped=uncited,
        positions_inside_gaps=positions_in_gaps,
        sentences=sentences,
        gaps_matched=gaps_matched,
        reolink_person_events=len(reolink),
        reolink_matched_by_sam=matched,
    )
    roles = _role_rows(label, result, visits)
    row.update(roles=roles, **_role_counts(label, roles))
    return row


_SUMS = (
    "motion_triggers", "alerts", "visits", "escalated", "links", "links_correct",
    "claims_inside_gaps", "uncited_sentences_shipped", "positions_inside_gaps", "sentences",
    "gaps_labelled", "gaps_matched", "reolink_person_events", "reolink_matched_by_sam",
    "roles_labelled", "roles_correct", "household_subjects", "household_missed",
    "role_miss_alerts",
)  # fmt: skip


def compute_metrics(labels: list[dict], results: list[dict]) -> dict:
    """NFR-023 metrics plus escalation rate, gap match and Reolink/SAM agreement."""
    parsed = sorted((ScenarioLabel.model_validate(lab) for lab in labels), key=lambda x: x.scenario)
    seen: set[str] = set()
    for lab in parsed:
        if lab.scenario in seen:
            raise ValueError(f"duplicate label for scenario {lab.scenario!r}")
        seen.add(lab.scenario)
    by_scenario = {str(r.get("scenario")): r for r in results}
    rows = [_scenario_row(lab, by_scenario.get(lab.scenario)) for lab in parsed]
    unlabelled = sorted(set(by_scenario) - seen)

    totals: dict[str, Any] = {k: sum(int(r[k]) for r in rows) for k in _SUMS}
    n = len(rows)
    totals["scenarios"] = n
    totals["missing_results"] = sum(1 for r in rows if r["status"] == "missing")
    totals["correct_verdicts"] = sum(1 for r in rows if r["correct"])
    totals["alert_reduction"] = (
        None
        if totals["motion_triggers"] <= 0
        else _r(1 - totals["alerts"] / totals["motion_triggers"])
    )
    totals["link_precision"] = _ratio(totals["links_correct"], totals["links"])
    totals["escalation_rate"] = _ratio(totals["escalated"], totals["visits"])
    totals["reolink_sam_agreement"] = _ratio(
        totals["reolink_matched_by_sam"], totals["reolink_person_events"]
    )
    totals["role_accuracy"] = _ratio(totals["roles_correct"], totals["roles_labelled"])
    totals["role_miss_rate"] = _ratio(totals["household_missed"], totals["household_subjects"])
    for part, keep in (("day", lambda lt: lt == "day"), ("night", NIGHT_LIGHTING.__contains__)):
        mine = [r for r in rows if keep(r["lighting"])]
        hh = sum(int(r["household_subjects"]) for r in mine)
        missed = sum(int(r["household_missed"]) for r in mine)
        totals[f"household_subjects_{part}"] = hh
        totals[f"household_missed_{part}"] = missed
        totals[f"role_miss_rate_{part}"] = _ratio(missed, hh)

    met = {
        "alert_reduction": _check("alert_reduction", totals["alert_reduction"]),
        "correct_verdicts": _check("correct_verdicts", totals["correct_verdicts"], n),
        "link_precision": _check("link_precision", totals["link_precision"]),
        "claims_inside_gaps": _check("claims_inside_gaps", totals["claims_inside_gaps"]),
        "uncited_sentences_shipped": _check(
            "uncited_sentences_shipped", totals["uncited_sentences_shipped"]
        ),
    }
    return {
        "schema_version": LABEL_SCHEMA_VERSION,
        "definitions": {"alert_verdicts": list(ALERT_VERDICTS)},
        "scenarios": rows,
        "totals": totals,
        "targets": TARGETS,
        "met": met,
        "unlabelled_results": unlabelled,
    }
