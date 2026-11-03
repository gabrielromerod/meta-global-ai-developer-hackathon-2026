"""Compose API responses from a loaded bundle (spec 9.6; FR-017, FR-023, FR-040, NFR-022).

Pure functions over `vigil.store.export.Bundle`: verdict labels, sentences with citation
chips and source badges, gap labels, the "How this was decided" trace (with each subject's
spatial-origin role and `role_basis`, and any rule a role excluded; FR-044), telemetry totals,
3D positions with observed path segments and gap connectors. Position labels state the
measured r95 of each estimate, never a fixed figure (spec 4 step 3, NFR-026).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from vigil.models import (
    APPLIES_TO_ROLES,
    Appearance,
    Box,
    Event,
    Gap,
    ModelCall,
    Position,
    ProtectedObject,
    StorySentence,
    Subject,
    Visit,
    VisitLedger,
)
from vigil.store.export import Bundle

VERDICT_LABELS = {
    "normal": "Normal",
    "noteworthy": "Noteworthy",
    "needs_attention": "Needs your attention",
    "cant_confirm": "Can't confirm",
}
PATH_MAX_STEP_S = 1.0  # observed path joins estimates no more than 1 s apart (spec 7)
ROLE_LABELS = {
    "household_insider": "Household",
    "expected_visitor": "Expected visitor",
    "external_visitor": "Arrived from outside",
    "unknown": "Unknown origin (treated as non-household)",
}
APPLIES_WORDS = {
    "anyone": "everyone",
    "non_household": "non-household people only",
    "external_visitor_only": "people from outside the property only",
}


# ---------------------------------------------------------------------------
# Clock and names
# ---------------------------------------------------------------------------


def session_start(bundle: Bundle) -> datetime | None:
    raw = bundle.manifest.get("session_start")
    return datetime.fromisoformat(raw) if raw else None


def clock(bundle: Bundle, t: float, seconds: bool = False) -> str:
    start = session_start(bundle)
    if start is None:
        return f"t={t:.0f} s"
    fmt = "%I:%M:%S %p" if seconds else "%I:%M %p"
    return (start + timedelta(seconds=t)).strftime(fmt).lstrip("0")


def camera_names(bundle: Bundle) -> dict[str, str]:
    return {c["id"]: c["name"] for c in bundle.cameras}


def twin_camera(bundle: Bundle, camera_id: str) -> dict[str, Any] | None:
    return next((c for c in bundle.twin.get("cameras", []) if c["id"] == camera_id), None)


def region_names(bundle: Bundle) -> dict[str, str]:
    return {r["id"]: r["name"] for r in bundle.twin.get("blind_regions", [])}


def gap_label(gap: Gap) -> str:
    return f"Not observed · {round(gap.duration_s)} s"


def recorded_date(raw: str | None) -> str:
    if not raw:
        return "the recorded evening"
    return datetime.fromisoformat(raw).strftime("%b %d, %Y").replace(" 0", " ")


# ---------------------------------------------------------------------------
# Ledger, telemetry
# ---------------------------------------------------------------------------


def call_row(call: ModelCall) -> dict[str, Any]:
    return call.model_dump(mode="json")


def totals(calls: list[ModelCall]) -> dict[str, Any]:
    return {
        "count": len(calls),
        "cost_usd": round(sum(c.cost_usd for c in calls), 6),
        "latency_ms": sum(c.latency_ms or 0 for c in calls),
        "cached": sum(1 for c in calls if c.cached),
        "live": sum(1 for c in calls if not c.cached),
        "failed": sum(1 for c in calls if not c.ok),
    }


def telemetry(calls: list[ModelCall]) -> dict[str, Any]:
    by_purpose: dict[str, dict[str, Any]] = {}
    for c in calls:
        g = by_purpose.setdefault(
            f"{c.model} · {c.purpose}",
            {"model": c.model, "purpose": c.purpose, "count": 0, "cost_usd": 0.0, "latency_ms": 0},
        )
        g["count"] += 1
        g["cost_usd"] = round(g["cost_usd"] + c.cost_usd, 6)
        g["latency_ms"] += c.latency_ms or 0
    return {
        "calls": [call_row(c) for c in calls],
        "groups": list(by_purpose.values()),
        "totals": totals(calls),
    }


# ---------------------------------------------------------------------------
# Visit card
# ---------------------------------------------------------------------------


def story_call(bundle: Bundle, visit: Visit) -> ModelCall | None:
    trace = bundle.trace.get(visit.id, {})
    cid = trace.get("story_call_id")
    calls = bundle.calls_for(visit.id)
    if cid:
        return next((c for c in calls if c.id == cid), None)
    story = [c for c in calls if c.purpose == "story" and c.ok]
    return story[-1] if story else None


def badge(sentence: StorySentence, model: str | None, call_id: str | None) -> dict[str, Any]:
    if sentence.source == "code":
        return {"kind": "code", "model": None, "call_id": None,
                "label": "Gap sentence · written by code"}  # fmt: skip
    if sentence.source == "template":
        return {"kind": "template", "model": None, "call_id": None,
                "label": "Template · written by code"}  # fmt: skip
    return {
        "kind": "model",
        "model": model,
        "call_id": call_id,
        "label": f"{model or 'model'} · {call_id or 'call id missing'}",
    }


def citation(bundle: Bundle, e: Event) -> dict[str, Any]:
    names = camera_names(bundle)
    return {
        "event_id": e.id,
        "t": e.t0,
        "t1": e.t1,
        "clip_t0": e.clip_t0,
        "clip_t1": e.clip_t1,
        "clock": clock(bundle, e.t0, seconds=True),
        "camera_id": e.camera_id,
        "camera_name": names.get(e.camera_id, e.camera_id),
        "type": e.type,
        "target": e.target,
        "track_id": e.track_id,
        "subject_id": e.subject_id,
        "actor_role": e.actor_role,
    }


def sentences_view(
    bundle: Bundle,
    visit: Visit,
    story: list[StorySentence],
    model: str | None = None,
    call_id: str | None = None,
) -> list[dict[str, Any]]:
    if model is None and call_id is None:
        call = story_call(bundle, visit)
        model, call_id = (call.model, call.id) if call else (None, None)
    events = {e.id: e for e in bundle.events_for(visit.id)}
    gaps = {g.id: g for g in bundle.gaps_for(visit.id)}
    out = []
    for i, s in enumerate(story):
        cites = [citation(bundle, events[eid]) for eid in s.event_ids if eid in events]
        item = {
            "index": i,
            "text": s.text,
            "source": s.source,
            "gap_id": s.gap_id,
            "citations": cites,
            "badge": badge(s, model, call_id),
        }
        if s.gap_id and s.gap_id in gaps:
            g = gaps[s.gap_id]
            item["gap"] = {"id": g.id, "t0": g.t0, "t1": g.t1, "label": gap_label(g)}
        out.append(item)
    return out


def gap_view(bundle: Bundle, g: Gap) -> dict[str, Any]:
    names = camera_names(bundle)
    return {
        **g.model_dump(),
        "duration_s": round(g.duration_s, 3),
        "label": gap_label(g),
        "region_name": region_names(bundle).get(g.region_id or "", g.region_id),
        "from_camera_name": names.get(g.from_camera or "", g.from_camera),
        "to_camera_name": names.get(g.to_camera or "", g.to_camera),
        "clock_t0": clock(bundle, g.t0, seconds=True),
        "clock_t1": clock(bundle, g.t1, seconds=True),
    }


def rule_json(bundle: Bundle, rule_id: str) -> dict[str, Any]:
    return next((dict(r["json"]) for r in bundle.rules if r["id"] == rule_id), {})


def rule_hits_view(bundle: Bundle, visit_id: str) -> list[dict[str, Any]]:
    out = []
    for h in bundle.rule_hits:
        if h["visit_id"] == visit_id:
            rule = rule_json(bundle, h["rule_id"])
            out.append(
                {
                    **h,
                    "rule_name": rule.get("name", h["rule_id"]),
                    "applies_to": rule.get("applies_to", "anyone"),
                }
            )
    return out


# ---------------------------------------------------------------------------
# Spatial-origin roles (FR-044): shown with their stored basis, never an identity
# ---------------------------------------------------------------------------


def _place(zone: str) -> str:
    return zone.replace("_", " ")


def basis_label(bundle: Bundle, basis: str) -> str:
    """Plain words for a role_basis value (spec 9.4)."""
    kind, _, ref = basis.partition(":")
    if kind == "egress":
        return f"came out of the house ({_place(ref)})"
    if kind == "checkin":
        return f"a household member checked in on the app just before ({ref})"
    if kind == "window":
        w = next((w for w in bundle.expected_windows if w.id == ref), None)
        label = f' "{w.label}"' if w and w.label else ""
        return f"arrived from the perimeter inside Expected Window {ref}{label}"
    if kind == "perimeter":
        return f"arrived from outside the property ({_place(ref)})"
    if kind == "group":
        return f"walked in a group whose members all held the same role ({ref})"
    if kind == "gap_unresolved":
        return f"re-linked after gap {ref} on timing alone; role unknown"
    if kind == "ambiguous_link":
        return f"followed an ambiguous link ({ref}); role unknown"
    if kind == "origin_null":
        return f"where they came from was not observed ({ref}); role unknown"
    return basis


def subject_view(bundle: Bundle, s: Subject) -> dict[str, Any]:
    return {
        "id": s.id,
        "track_ids": list(s.track_ids),
        "actor_role": s.actor_role,
        "role_basis": s.role_basis,
        "role_label": ROLE_LABELS.get(s.actor_role, s.actor_role),
        "basis_label": basis_label(bundle, s.role_basis),
    }


def _tz(bundle: Bundle) -> ZoneInfo:
    try:
        return ZoneInfo(bundle.manifest.get("timezone") or "America/Los_Angeles")
    except (KeyError, ValueError):
        return ZoneInfo("America/Los_Angeles")


def _minutes(hhmm: str) -> int:
    hh, _, mm = hhmm.partition(":")
    return int(hh) * 60 + int(mm)


def _in_window(active: dict[str, str] | None, minute: int) -> bool:
    if not active:
        return True
    start, end = _minutes(active["start"]), _minutes(active["end"])
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end  # crosses midnight


def _excluded_reason(rule_id: str, name: str, applies: str, role: str, basis: str | None) -> str:
    who = APPLIES_WORDS.get(applies, applies)
    why = f"{role} ({basis})" if basis else role
    return (
        f'{rule_id} "{name}" was in force but applies to {who}; this person\'s role is {why}, '
        "so it did not fire."
    )


def rules_excluded(bundle: Bundle, visit: Visit) -> list[dict[str, Any]]:
    """Rules in force on a touched object that did not fire because of `applies_to` (9.4).

    This is the A′ evidence: r7 was in force on the side gate after dark, but it applies to
    non-household people, and this person came out of the house's own door.
    """
    start = session_start(bundle)
    subjects = {s.id: s for s in bundle.subjects_for(visit.id)}
    hits = {(h["rule_id"], h["event_id"]) for h in bundle.rule_hits}
    out: list[dict[str, Any]] = []
    for e in bundle.events_for(visit.id):
        if e.type not in ("touch", "removed") or not e.target or not e.actor_role:
            continue
        local = (start + timedelta(seconds=e.t0)).astimezone(_tz(bundle)) if start else None
        minute = local.hour * 60 + local.minute if local else None
        for r in bundle.rules:
            rule = dict(r["json"])
            target = rule.get("target") or {}
            if target.get("id") != e.target or rule.get("trigger") != e.type:
                continue
            if rule.get("state", "active") != "active" or (r["id"], e.id) in hits:
                continue
            if minute is not None and not _in_window(rule.get("active"), minute):
                continue
            applies = rule.get("applies_to", "anyone")
            if e.actor_role in APPLIES_TO_ROLES.get(applies, APPLIES_TO_ROLES["anyone"]):
                continue
            s = subjects.get(e.subject_id or "")
            basis = s.role_basis if s else None
            name = rule.get("name", r["id"])
            out.append(
                {
                    "rule_id": r["id"],
                    "rule_name": name,
                    "event_id": e.id,
                    "applies_to": applies,
                    "actor_role": e.actor_role,
                    "role_basis": basis,
                    "reason": _excluded_reason(r["id"], name, applies, e.actor_role, basis),
                }
            )
    return out


def expected_windows_view(bundle: Bundle, visit: Visit) -> list[dict[str, Any]]:
    """Expected Windows a subject of this visit was matched to (they show on the card)."""
    ids = {
        s.role_basis.partition(":")[2]
        for s in bundle.subjects_for(visit.id)
        if s.role_basis.startswith("window:")
    }
    return [w.model_dump(mode="json") for w in bundle.expected_windows if w.id in ids]


def watches_view(bundle: Bundle, visit_id: str) -> list[dict[str, Any]]:
    names = {"front": "porch"}
    out = []
    for w in bundle.watches:
        if w.get("source_visit_id") == visit_id:
            where = names.get(w["camera_id"], camera_names(bundle).get(w["camera_id"], ""))
            notice = (
                f"Now watching: {w['phrase']} on {where}" if w["status"] == "watching" else None
            )
            out.append({**w, "notice": notice})
    return out


def calibration_view(bundle: Bundle, camera_ids: list[str]) -> list[dict[str, Any]]:
    out = []
    for cid in sorted(camera_ids):
        cam = twin_camera(bundle, cid)
        if cam and cam.get("calibration"):
            out.append({"camera_id": cid, "name": cam.get("name", cid), **cam["calibration"]})
    return out


def trace_view(bundle: Bundle, visit: Visit) -> dict[str, Any]:
    raw = dict(bundle.trace.get(visit.id, {}))
    validations = [v.model_dump() for v in bundle.validations_for(visit.id)]
    drafts = raw.get("drafts", [])
    for d in drafts:
        match = next((v for v in validations if v["attempt"] == d.get("attempt")), None)
        if match and "failures" not in d:
            d["failures"] = match["failures"]
    cams = sorted({e.camera_id for e in bundle.events_for(visit.id)})
    return {
        "rules_fired": rule_hits_view(bundle, visit.id),
        "rules_excluded": rules_excluded(bundle, visit),
        "subjects": [subject_view(bundle, s) for s in bundle.subjects_for(visit.id)],
        "floor": visit.floor,
        "triage": raw.get("triage"),
        "drafts": drafts,
        "validations": validations,
        "verdict_inputs": raw.get(
            "verdict_inputs",
            {"floor": visit.floor, "proposal": visit.proposal, "result": visit.verdict},
        ),
        "watch_proposals": raw.get("watch_proposals", []),
        "calibration": calibration_view(bundle, cams),
    }


def visit_summary(bundle: Bundle, visit: Visit) -> dict[str, Any]:
    first = next((s.text for s in visit.story), "")
    return {
        "id": visit.id,
        "scenario": visit.scenario,
        "verdict": visit.verdict,
        "verdict_label": VERDICT_LABELS.get(visit.verdict or "", visit.verdict),
        "escalated": visit.escalated,
        "first_sentence": first,
        "t0": visit.t0,
        "t1": visit.t1,
        "clock": clock(bundle, visit.t0),
        "cameras": sorted({e.camera_id for e in bundle.events_for(visit.id)}),
        "gaps": [gap_label(g) for g in bundle.gaps_for(visit.id)],
        "roles": [s.actor_role for s in bundle.subjects_for(visit.id)],
    }


def visit_view(bundle: Bundle, visit: Visit) -> dict[str, Any]:
    scenario = bundle.scenario(visit.scenario or "")
    events = bundle.events_for(visit.id)
    return {
        **visit_summary(bundle, visit),
        "scenario_title": scenario["title"] if scenario else visit.scenario,
        "state": visit.state,
        "floor": visit.floor,
        "proposal": visit.proposal,
        "clock_t1": clock(bundle, visit.t1),
        "sentences": sentences_view(bundle, visit, visit.story),
        "events": [citation(bundle, e) for e in events],
        "gaps": [gap_view(bundle, g) for g in bundle.gaps_for(visit.id)],
        "rule_hits": rule_hits_view(bundle, visit.id),
        "subjects": [subject_view(bundle, s) for s in bundle.subjects_for(visit.id)],
        "expected_windows": expected_windows_view(bundle, visit),
        "watches": watches_view(bundle, visit.id),
        "trace": trace_view(bundle, visit),
        "telemetry": telemetry(bundle.calls_for(visit.id)),
        "synthetic": bool(bundle.manifest.get("synthetic")),
    }


# ---------------------------------------------------------------------------
# Positions (FR-039, FR-040)
# ---------------------------------------------------------------------------


def _inside(t: float, gaps: list[Gap]) -> bool:
    return any(g.t0 < t < g.t1 for g in gaps)


def positions_view(bundle: Bundle, visit: Visit) -> dict[str, Any]:
    gaps = bundle.gaps_for(visit.id)
    cls = {t["id"]: t["cls"] for t in bundle.tables.get("tracks", [])}
    pos = [p for p in bundle.positions_for(visit.track_ids) if not _inside(p.t, gaps)]
    pos.sort(key=lambda p: (p.t, p.track_id))
    paths: list[list[list[float]]] = []
    for kind in sorted({cls.get(p.track_id, "object") for p in pos}):
        seq = [p for p in pos if cls.get(p.track_id, "object") == kind]
        current: list[list[float]] = []
        for p in seq:
            crosses = (
                any(g.t0 >= current[-1][2] and g.t1 <= p.t for g in gaps) if current else False
            )
            if current and (p.t - current[-1][2] > PATH_MAX_STEP_S or crosses):
                if len(current) > 1:
                    paths.append(current)
                current = []
            current.append([p.x, p.z, p.t])
        if len(current) > 1:
            paths.append(current)

    def point(p: Position | None) -> list[float] | None:
        return [p.x, p.z, p.t] if p else None

    gap_out = []
    for g in gaps:
        before = [p for p in pos if p.t <= g.t0]
        after = [p for p in pos if p.t >= g.t1]
        gap_out.append(
            {
                **gap_view(bundle, g),
                "from": point(before[-1] if before else None),
                "to": point(after[0] if after else None),
            }
        )
    names = camera_names(bundle)
    out_pos = []
    for p in pos:
        row = p.model_dump()
        row["cls"] = cls.get(p.track_id, "object")
        row["label"] = position_label(p, names)
        out_pos.append(row)
    return {"visit_id": visit.id, "positions": out_pos, "paths": paths, "gaps": gap_out}


def position_label(p: Position, names: dict[str, str]) -> str:
    if p.method == "height_prior" or "low_confidence" in p.flags:
        return f"Low confidence ±{p.r95:.1f} m"
    if p.method == "fused" or len(p.cameras) > 1:
        return f"Estimated from {len(p.cameras)} cameras ±{p.r95:.1f} m"
    cam = names.get(p.cameras[0], p.cameras[0]) if p.cameras else "camera"
    return f"Estimated ±{p.r95:.1f} m from {cam} camera"


# ---------------------------------------------------------------------------
# Ledger for a live story re-run (Wonder sees JSON only, never pixels)
# ---------------------------------------------------------------------------


def visit_ledger(bundle: Bundle, visit: Visit) -> VisitLedger:
    objects = []
    for row in bundle.protected_objects:
        objects.append(
            ProtectedObject(
                id=row["id"],
                camera_id=row["camera_id"],
                label=row["label"],
                bbox=Box.model_validate(row["bbox_json"]),
                footprint=[tuple(p) for p in row.get("footprint_json") or []] or None,
                call_id=row.get("call_id"),
            )
        )
    appearance = {}
    for row in bundle.tables.get("appearance", []):
        if row["track_id"] in visit.track_ids:
            appearance[row["track_id"]] = Appearance.model_validate(row["notes_json"])
    from vigil.models import RuleHit

    return VisitLedger(
        visit=visit,
        events=bundle.events_for(visit.id),
        gaps=bundle.gaps_for(visit.id),
        protected_objects=objects,
        rule_hits=[
            RuleHit.model_validate(h) for h in bundle.rule_hits if h["visit_id"] == visit.id
        ],
        appearance=appearance,
        camera_names=camera_names(bundle),
        region_names=region_names(bundle),
        subjects=bundle.subjects_for(visit.id),
        timezone=bundle.manifest.get("timezone", "America/Los_Angeles"),
        session_start=session_start(bundle),
    )


# ---------------------------------------------------------------------------
# Ground footprint of a tapped object (synthetic pinhole from the twin pose)
# ---------------------------------------------------------------------------


def ground_footprint(cam: dict[str, Any], bbox: dict[str, float]) -> list[list[float]] | None:
    """Cast the bottom corners of a mask box onto the ground plane y=0 (site-plan level)."""
    try:
        px, py, pz = cam["position"]
        lx, ly, lz = cam["look_at"]
        w, h = cam.get("width", 1280), cam.get("height", 720)
        fx = (w / 2) / math.tan(math.radians(cam["hfov_deg"]) / 2)
    except (KeyError, TypeError, ValueError):
        return None
    f = [lx - px, ly - py, lz - pz]
    n = math.sqrt(sum(v * v for v in f))
    f = [v / n for v in f]
    r = [-f[2], 0.0, f[0]]  # cross(f, up) with up = +y
    rn = math.hypot(r[0], r[2]) or 1.0
    r = [r[0] / rn, 0.0, r[2] / rn]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]

    def cast(x: float, y: float) -> list[float] | None:
        a, b = (x - w / 2) / fx, -(y - h / 2) / fx
        d = [f[i] + a * r[i] + b * u[i] for i in range(3)]
        if d[1] >= -1e-6:
            return None
        k = -py / d[1]
        return [round(px + k * d[0], 3), round(pz + k * d[2], 3)]

    left = cast(bbox["x1"], bbox["y2"])
    right = cast(bbox["x2"], bbox["y2"])
    if left is None or right is None:
        return None
    dx, dz = right[0] - left[0], right[1] - left[1]
    norm = math.hypot(dx, dz) or 1.0
    ox, oz = -dz / norm * 0.3, dx / norm * 0.3
    return [
        left,
        right,
        [round(right[0] + ox, 3), round(right[1] + oz, 3)],
        [round(left[0] + ox, 3), round(left[1] + oz, 3)],
    ]
