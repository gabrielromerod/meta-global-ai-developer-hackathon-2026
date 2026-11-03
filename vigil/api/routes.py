"""HTTP routes over the demo bundle (spec 9.6).

Read routes serve the cached bundle. The live buttons (protect, transcribe, compile, re-run)
are cached by default; a live request is rate-limited per IP, runs only when a key is set and
the guards allow it (daily credit cap; after the credit window, VIGIL_ALLOW_PAID, the $25
judging total, $5 per PT day and VIGIL_JUDGING_END), and any live failure falls back to the
recorded result with a visible notice (FR-026, FR-043, NFR-009, NFR-010, spec 11.6 item 6).
Voice routes live in `vigil.api.voice`; windows, check-in and feedback in `vigil.api.owner`.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vigil.api import views
from vigil.api.backend import LiveResult
from vigil.api.guards import (
    LIVE_ESTIMATE_USD,
    Guards,
    LiveStatus,
    check_live_allowed,
    check_model_allowed,
    client_ip,
    notice_live_failed,
    read_bounded,
)
from vigil.models import CheckIn, ExpectedWindow, ModelCall, Rule, StorySentence, Visit
from vigil.store.export import Bundle

W_MAX, H_MAX = 1280, 720

# Draft-card wording (FR-021, UC-03). Code writes these; a model never does.
NO_TEMPLATES = (
    "Vigil places people by where they came from; it does not identify anyone and creates "
    "no face, voice or body templates."
)
APPLIES_LABELS: dict[str, str] = {
    "anyone": "Applies to everyone, including household members.",
    "non_household": "Applies to everyone except household members.",
    "external_visitor_only": (
        "Applies only to people who arrived from outside the property, except guests or "
        "deliveries inside an Expected Window you set."
    ),
}
BASIS_NOTES: dict[str, str] = {
    "anyone": (
        "This rule does not depend on where anyone came from. Vigil does not identify anyone "
        "and creates no face, voice or body templates."
    ),
    "non_household": (
        "Vigil treats someone as household only when it saw them come out of the house's own "
        "doors, or when a household member checked in on the app just before coming into view. "
        "Household members arriving from the street without checking in, and anyone Vigil "
        "loses track of, count as non-household and can trigger this rule. " + NO_TEMPLATES
    ),
    "external_visitor_only": (
        "Vigil treats someone as an expected visitor only when they arrived from the street, "
        "driveway or alley inside an Expected Window you set in advance, and as household only "
        "when it saw them come out of the house's own doors or a household member checked in "
        "on the app just before they came into view. Anyone Vigil loses track of counts as "
        "arriving from outside and can trigger this rule. " + NO_TEMPLATES
    ),
}
NAMED_PERSON_NOTICE = (
    "Vigil can't recognise individuals. It treats someone as household only if they came out "
    "of the house's own doors or checked in on the app, so {name} is exempt only in those cases."
)
_NOT_NAMES = {"family", "us", "the", "household", "me", "my", "our", "guests", "deliveries"}
_NAMED = re.compile(r"\bexcept(?:\s+for)?\s+([A-Z][a-z]+)\b")


def applies_view(applies_to: str) -> dict[str, str]:
    """The plain-words scope and basis note shown on every draft rule card."""
    return {
        "applies_label": APPLIES_LABELS.get(applies_to, APPLIES_LABELS["anyone"]),
        "basis_note": BASIS_NOTES.get(applies_to, BASIS_NOTES["anyone"]),
    }


def named_person(text: str) -> str | None:
    """'except Sam' -> 'Sam'. Family words are roles, not names (FR-021)."""
    for m in _NAMED.finditer(text):
        if m.group(1).lower() not in _NOT_NAMES:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Request models (extra fields forbidden: a request can never choose a model, NFR-004)
# ---------------------------------------------------------------------------


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PixelPoint(_Req):
    x: float = Field(ge=0, le=32768)
    y: float = Field(ge=0, le=32768)


class ProtectRequest(_Req):
    camera_id: str = Field(max_length=64)
    frame_ts: float | None = None
    point: PixelPoint
    label: str | None = Field(default=None, max_length=60)
    live: bool = False
    frame_width: int | None = Field(default=None, ge=1, le=32768)
    frame_height: int | None = Field(default=None, ge=1, le=32768)


class CompileRequest(_Req):
    text: str = Field(min_length=1, max_length=500)
    live: bool = False


class RerunRequest(_Req):
    stage: Literal["story"] = "story"
    live: bool = False


# ---------------------------------------------------------------------------
# Runtime state (in memory; the sandbox never writes the bundle)
# ---------------------------------------------------------------------------


class Runtime:
    def __init__(self, bundle: Bundle) -> None:
        self.lock = threading.Lock()
        self.rules: dict[str, dict[str, Any]] = {r["id"]: dict(r["json"]) for r in bundle.rules}
        self.protected: list[dict[str, Any]] = []
        self.live_calls: list[ModelCall] = []
        self.jobs: dict[str, dict[str, Any]] = {}
        self.pairs: dict[str, list[dict[str, Any]]] = {}
        self.windows: dict[str, ExpectedWindow] = {}
        """Owner-set Expected Windows (FR-029); persisted to the edge DB in edge mode."""
        self.checkins: dict[str, CheckIn] = {}
        self.feedback: list[dict[str, Any]] = []
        self.transcripts: dict[str, str] = {}
        """Transcript by audio SHA-256: the only trace a spoken rule leaves (NFR-002)."""


def _state(request: Request) -> tuple[Bundle, Guards, Runtime, Any]:
    s = request.app.state
    return s.bundle, s.guards, s.runtime, s.live_backend


def is_json(request: Request) -> bool:
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    return ctype == "application/json"


def require_json(request: Request) -> None:
    """415 unless the body is declared application/json.

    A cross-site form or `no-cors` fetch can only send text/plain, form or multipart bodies
    without a preflight, so insisting on JSON keeps those simple requests out (F2).
    """
    if not is_json(request):
        raise HTTPException(415, "send the body as application/json")


async def _parse(request: Request, model: type[BaseModel]) -> Any:
    settings = request.app.state.settings
    body = await read_bounded(request, int(settings.max_json_bytes))
    if body and not is_json(request):
        raise HTTPException(415, "send the body as application/json")
    try:
        return model.model_validate_json(body or b"{}")
    except ValidationError as exc:
        raise HTTPException(422, json.loads(exc.json(include_url=False))) from exc


def _accept_live(guards: Guards, runtime: Runtime, result: LiveResult) -> list[ModelCall]:
    """Validate every model call of a live result, then record spend and ledger rows.

    Each row is tagged `credit` or `paid` by the guards' phase (spec 9.3, NFR-036/037).
    """
    funding = guards.funding()
    calls = []
    for c in result.calls:
        data = c.model_dump() if isinstance(c, BaseModel) else dict(c)
        check_model_allowed(str(data.get("model", "")))
        call = ModelCall.model_validate({**data, "cached": False, "funding": funding})
        calls.append(call)
    # By call id: rows the Meta client already ledgered are skipped, new ones are added.
    guards.record_calls(calls)
    with runtime.lock:
        runtime.live_calls.extend(calls)
    return calls


def _telemetry_live(calls: list[ModelCall]) -> dict[str, Any]:
    first = calls[0] if calls else None
    return {
        "model": first.model if first else None,
        "call_id": first.id if first else None,
        "latency_ms": sum(c.latency_ms or 0 for c in calls),
        "cost_usd": round(sum(c.cost_usd for c in calls), 6),
        "cached": False,
        "funding": first.funding if first else None,
        "calls": [c.model_dump(mode="json") for c in calls],
    }


def _telemetry_cached(preset: dict[str, Any] | None) -> dict[str, Any]:
    preset = preset or {}
    return {
        "model": preset.get("model"),
        "call_id": preset.get("call_id"),
        "latency_ms": preset.get("latency_ms"),
        "cost_usd": preset.get("cost_usd", 0.0),
        "cached": True,
        "recorded_at": preset.get("recorded_at"),
    }


def _envelope(
    live: bool,
    requested: bool,
    result: Any,
    telemetry: dict[str, Any],
    notice: str | None = None,
    error: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "live": live,
        "requested_live": requested,
        "notice": notice,
        "error": error,
        "result": result,
        "telemetry": telemetry,
        **extra,
    }


def _failure(guards: Guards, exc: Exception) -> str:
    return guards.redact(f"{type(exc).__name__}: {exc}")[:300]


def _failed_notice(preset: dict[str, Any] | None) -> str:
    return notice_live_failed(views.recorded_date((preset or {}).get("recorded_at")))


def _live_gate(request: Request, guards: Guards, live: bool, kind: str) -> LiveStatus | None:
    """Rate-limit live requests (429) and report whether live can run now."""
    if not live:
        return None
    return check_live_allowed(guards, client_ip(request), LIVE_ESTIMATE_USD.get(kind, 0.0))


def _visit_or_404(bundle: Bundle, visit_id: str) -> Visit:
    visit = bundle.visit(visit_id)
    if visit is None:
        raise HTTPException(404, f"unknown visit {visit_id!r}")
    return visit


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def _catalog(request: Request, bundle: Bundle, runtime: Runtime) -> dict[str, Any]:
    objects = [
        {"id": o["id"], "label": o["label"], "camera_id": o["camera_id"]}
        for o in bundle.protected_objects + runtime.protected
    ]
    for p in bundle.presets.get("protect", []):
        o = p["object"]
        if all(x["id"] != o["id"] for x in objects):
            objects.append({"id": o["id"], "label": o["label"], "camera_id": o["camera_id"]})
    zones, lines = [], []
    cfg = request.app.state.config
    if cfg is not None:
        for cam in cfg.cameras:
            zones += [{"id": z, "camera_id": cam.id} for z in cam.zones]
            lines += [{"id": ln, "camera_id": cam.id} for ln in cam.lines]
    watches = [{"id": w["id"], "phrase": w["phrase"]} for w in bundle.watches]
    return {"protected_objects": objects, "zones": zones, "lines": lines, "watches": watches}


def _target_known(rule: Rule, catalog: dict[str, Any]) -> bool:
    kind, tid = rule.target.kind, rule.target.id
    pool = {
        "protected_object": catalog["protected_objects"],
        "zone": catalog["zones"],
        "line": catalog["lines"],
        "watch": catalog["watches"],
    }[kind]
    return (kind == "watch" and tid == "any") or any(x["id"] == tid for x in pool)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def health_view(request: Request) -> dict[str, Any]:
    """Mode, spend today, credit cap and judging cap remaining (spec 9.6)."""
    bundle, guards, _, _ = _state(request)
    status = guards.live_status()
    settings = request.app.state.settings
    end = settings.credit_window_end
    judging_end = getattr(settings, "judging_end", None)
    total_left, today_left = guards.judging_remaining()
    return {
        "status": "ok",
        "mode": settings.mode,
        "synthetic": bool(bundle.manifest.get("synthetic")),
        "bundle_label": bundle.manifest.get("label"),
        "live": status.public(),
        "phase": status.phase,
        "funding": status.funding,
        "spend_today_usd": status.spend_today_usd,
        "daily_cap_usd": status.daily_cap_usd,
        "credit_cap_usd": float(settings.total_cap_usd),
        "credit_spent_usd": guards.spend_total("credit"),
        "credit_window_end": end.isoformat() if end else None,
        "allow_paid": bool(settings.allow_paid),
        "judging_cap_usd": float(settings.judging_cap_usd),
        "judging_daily_cap_usd": float(settings.judging_daily_cap_usd),
        "judging_spent_usd": guards.spend_total("paid"),
        "judging_cap_remaining_usd": total_left,
        "judging_today_remaining_usd": today_left,
        "judging_end": judging_end.isoformat() if judging_end else None,
        "rate_limit_per_min": guards.rate.limit,
    }


def router() -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/health")
    def health(request: Request) -> dict[str, Any]:
        return health_view(request)

    @r.get("/scenarios")
    def scenarios(request: Request) -> dict[str, Any]:
        bundle = request.app.state.bundle
        out = []
        for s in bundle.scenarios:
            visits = [bundle.visit(v) for v in s["visit_ids"]]
            out.append(
                {
                    **{k: s[k] for k in ("id", "title", "t0", "t1", "visit_ids", "verdicts")},
                    "visits": [views.visit_summary(bundle, v) for v in visits if v],
                }
            )
        return {
            "summary": bundle.manifest.get("summary", {}),
            "synthetic": bool(bundle.manifest.get("synthetic")),
            "label": bundle.manifest.get("label"),
            "session_start": bundle.manifest.get("session_start"),
            "scenarios": out,
        }

    @r.get("/scenarios/{scenario_id}")
    def scenario(scenario_id: str, request: Request) -> dict[str, Any]:
        bundle = request.app.state.bundle
        s = bundle.scenario(scenario_id)
        if s is None:
            raise HTTPException(404, f"unknown scenario {scenario_id!r}")
        visit_ids = set(s["visit_ids"])
        cameras = [{**c, "pose": views.twin_camera(bundle, c["id"])} for c in s["cameras"]]
        overlays: dict[str, Any] = {}
        from vigil.perception.overlays import player_overlays

        track_visits = {tid: v.id for v in bundle.visits for tid in v.track_ids}
        for cam, tracks in player_overlays(bundle.overlays, track_visits).items():
            keep = {tid: o for tid, o in tracks.items() if o.get("visit_id") in visit_ids}
            if keep:
                overlays[cam] = keep
        visits = [bundle.visit(v) for v in s["visit_ids"]]
        return {
            **s,
            "cameras": cameras,
            "overlays": overlays,
            "visits": [views.visit_summary(bundle, v) for v in visits if v],
            "clock_t0": views.clock(bundle, s["t0"]),
        }

    @r.get("/visits/{visit_id}")
    def visit(visit_id: str, request: Request) -> dict[str, Any]:
        bundle = request.app.state.bundle
        return views.visit_view(bundle, _visit_or_404(bundle, visit_id))

    @r.get("/visits/{visit_id}/positions")
    def positions(visit_id: str, request: Request) -> dict[str, Any]:
        bundle = request.app.state.bundle
        return views.positions_view(bundle, _visit_or_404(bundle, visit_id))

    @r.get("/twin")
    def twin(request: Request) -> dict[str, Any]:
        bundle, _, runtime, _ = _state(request)
        data = dict(bundle.twin)
        data["protected_objects"] = list(data.get("protected_objects", [])) + [
            {k: o[k] for k in ("id", "label", "camera_id", "footprint")} for o in runtime.protected
        ]
        return data

    @r.get("/calls")
    def calls(request: Request, visit_id: str | None = None) -> dict[str, Any]:
        bundle, _, runtime, _ = _state(request)
        rows = bundle.calls_for(visit_id)
        with runtime.lock:
            rows += [c for c in runtime.live_calls if visit_id is None or c.visit_id == visit_id]
        return {"visit_id": visit_id, **views.telemetry(rows)}

    @r.get("/eval")
    def eval_results(request: Request) -> dict[str, Any]:
        path = request.app.state.eval_path
        if path is not None and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return request.app.state.bundle.eval

    @r.get("/presets")
    def presets(request: Request) -> dict[str, Any]:
        bundle = request.app.state.bundle
        return {
            "protect": [
                {"camera_id": p["camera_id"], "point": p["point"], "label": p["label"]}
                for p in bundle.presets.get("protect", [])
            ],
            "compile": [c["text"] for c in bundle.presets.get("compile", [])],
            "voice": [
                {"id": v["id"], "label": v.get("label")} for v in bundle.presets.get("voice", [])
            ],
        }

    # -- tap-to-protect (FR-019) ---------------------------------------------------------
    @r.post("/protect")
    async def protect(request: Request) -> dict[str, Any]:
        bundle, guards, runtime, backend = _state(request)
        req: ProtectRequest = await _parse(request, ProtectRequest)
        if req.camera_id not in views.camera_names(bundle):
            raise HTTPException(422, f"unknown camera {req.camera_id!r}")
        camera = next(c for c in bundle.cameras if c["id"] == req.camera_id)
        ref_width, ref_height = camera.get("width", W_MAX), camera.get("height", H_MAX)
        if (req.frame_width is None) != (req.frame_height is None):
            raise HTTPException(422, "Both frame dimensions are required")
        width, height = req.frame_width or ref_width, req.frame_height or ref_height
        if req.point.x > width or req.point.y > height:
            raise HTTPException(422, "Point is outside the full camera frame")
        req.point = req.point.model_copy(
            update={"x": req.point.x * ref_width / width, "y": req.point.y * ref_height / height}
        )
        status = _live_gate(request, guards, req.live, "protect")
        notice, error = None, None
        if status is not None and status.available:
            try:
                res = backend.protect(req.camera_id, req.frame_ts, req.point.x, req.point.y,
                                      req.label)  # fmt: skip
                calls = _accept_live(guards, runtime, res)
                return _envelope(True, True, _live_object(request, req, res, calls),
                                 _telemetry_live(calls))  # fmt: skip
            except Exception as exc:  # any live failure degrades, never blanks (NFR-010)
                error = _failure(guards, exc)
        elif status is not None:
            notice = status.notice
        preset = _nearest_preset(bundle, req)
        if preset is None:
            options = [
                {"camera_id": p["camera_id"], "point": p["point"], "label": p["label"]}
                for p in bundle.presets.get("protect", [])
            ]
            hint = "Nothing recorded at that point. Try another point, or a preset point."
            if error:
                notice = (
                    "Live call failed; no recorded result at that point. Try another point, "
                    "or a preset point."
                )
            return _envelope(False, req.live, None, _telemetry_cached(None), notice or hint,
                             error, presets=options, hint=hint)  # fmt: skip
        if error:
            notice = _failed_notice(preset)
        result = {"object": preset["object"], "outline": preset["outline"],
                  "camera_id": preset["camera_id"]}  # fmt: skip
        return _envelope(False, req.live, result, _telemetry_cached(preset), notice, error)

    # -- rule compile (FR-021): text only; voice is transcribed first (FR-022) ------------
    @r.post("/rules/compile")
    async def compile_rule(request: Request) -> dict[str, Any]:
        bundle, guards, runtime, backend = _state(request)
        ctype = request.headers.get("content-type", "application/json").split(";")[0].strip()
        if ctype != "application/json":
            raise HTTPException(
                415, "send JSON {text}; transcribe audio first with POST /api/voice/transcribe"
            )
        req: CompileRequest = await _parse(request, CompileRequest)
        status = _live_gate(request, guards, req.live, "compile")
        notice, error = None, None
        if status is not None and status.available:
            catalog = _catalog(request, bundle, runtime)
            try:
                res = backend.compile_rule(req.text, catalog)
                calls = _accept_live(guards, runtime, res)
                result = _live_rule(runtime, res, catalog, req.text)
                return _envelope(True, True, result, _telemetry_live(calls))
            except Exception as exc:
                error = _failure(guards, exc)
        elif status is not None:
            notice = status.notice
        preset, exact = _closest_compile(bundle, req.text)
        if preset is None:
            raise HTTPException(503, "no recorded rule drafts in this bundle")
        rule = dict(preset["rule"])
        with runtime.lock:
            runtime.rules.setdefault(rule["id"], dict(rule))
        if error:
            notice = _failed_notice(preset)
        if not exact:
            example = f'Showing the recorded example for "{preset["text"]}".'
            notice = f"{notice}. {example}" if notice else example
        result = {"text": preset["text"], "rule": rule,
                  "limits_note": list(preset.get("limits_note", [])), "question": None,
                  **applies_view(rule.get("applies_to", "anyone"))}  # fmt: skip
        return _envelope(False, req.live, result, _telemetry_cached(preset), notice, error)

    @r.post("/rules/{rule_id}/confirm")
    def confirm_rule(rule_id: str, request: Request) -> dict[str, Any]:
        runtime: Runtime = request.app.state.runtime
        with runtime.lock:
            rule = runtime.rules.get(rule_id)
            if rule is None:
                raise HTTPException(404, f"unknown rule {rule_id!r}")
            rule["state"] = "active"
        return {"id": rule_id, "state": "active", "rule": rule,
                "note": "Sandbox: kept in memory for this server session."}  # fmt: skip

    # -- story re-run (FR-014 live, NFR-007) ---------------------------------------------
    @r.post("/visits/{visit_id}/rerun")
    async def rerun(visit_id: str, request: Request, tasks: BackgroundTasks) -> dict[str, Any]:
        bundle, guards, runtime, _ = _state(request)
        req: RerunRequest = await _parse(request, RerunRequest)
        _visit_or_404(bundle, visit_id)
        status = _live_gate(request, guards, req.live, "rerun")
        job_id = uuid.uuid4().hex[:12]
        with runtime.lock:
            runtime.jobs[job_id] = {"id": job_id, "visit_id": visit_id, "status": "queued",
                                    "result": None}  # fmt: skip
        tasks.add_task(_run_rerun, request.app, job_id, visit_id, req.live, status)
        return {"job_id": job_id, "status": "queued", "poll": f"/api/jobs/{job_id}"}

    @r.get("/jobs/{job_id}")
    def job(job_id: str, request: Request) -> dict[str, Any]:
        runtime: Runtime = request.app.state.runtime
        with runtime.lock:
            found = runtime.jobs.get(job_id)
            if found is None:
                raise HTTPException(404, f"unknown job {job_id!r}")
            return dict(found)

    return r


# ---------------------------------------------------------------------------
# Helpers for the live buttons
# ---------------------------------------------------------------------------


def _nearest_preset(bundle: Bundle, req: ProtectRequest, radius: float = 90.0) -> dict | None:
    best, best_d = None, radius
    for p in bundle.presets.get("protect", []):
        if p["camera_id"] != req.camera_id:
            continue
        d = ((p["point"][0] - req.point.x) ** 2 + (p["point"][1] - req.point.y) ** 2) ** 0.5
        if d <= best_d:
            best, best_d = p, d
    return best


def _live_object(
    request: Request, req: ProtectRequest, res: LiveResult, calls: list[ModelCall]
) -> dict[str, Any]:
    bundle, _, runtime, _ = _state(request)
    mask = dict(res.payload.get("mask") or {})
    bbox = mask.get("bbox")
    if not isinstance(bbox, dict):
        raise ValueError("live mask has no bbox")
    cam = views.twin_camera(bundle, req.camera_id) or {}
    with runtime.lock:
        obj = {
            "id": f"po_live_{len(runtime.protected) + 1}",
            "camera_id": req.camera_id,
            "label": req.label or "object",
            "bbox": bbox,
            "footprint": views.ground_footprint(cam, bbox)
            if (bundle.manifest.get("synthetic") or cam.get("placement_measured") is True)
            else None,
            "call_id": calls[0].id if calls else None,
        }
        runtime.protected.append(obj)
    return {"object": obj, "outline": mask.get("outline", []), "score": mask.get("score"),
            "camera_id": req.camera_id}  # fmt: skip


def _live_rule(
    runtime: Runtime, res: LiveResult, catalog: dict[str, Any], text: str
) -> dict[str, Any]:
    """A live draft: the compiled applies_to stands; code adds the basis and name notices."""
    payload = res.payload
    notes = [str(n) for n in (payload.get("limits_note") or payload.get("limits") or [])]
    name = named_person(text)
    if name and not any("can't recognise individuals" in n for n in notes):
        notes.insert(0, NAMED_PERSON_NOTICE.format(name=name))
    raw = payload.get("rule")
    if not raw:
        question = payload.get("question") or "Which object or zone do you mean?"
        return {"text": text, "rule": None, "limits_note": notes, "question": str(question),
                **applies_view("anyone")}  # fmt: skip
    rule = Rule.model_validate({**dict(raw), "state": "draft"})
    if not _target_known(rule, catalog):
        known = ", ".join(f"{o['label']} ({o['id']})" for o in catalog["protected_objects"])
        return {"text": text, "rule": None, "limits_note": notes,
                "question": f"Which object do you mean? Known objects: {known}.",
                **applies_view(rule.applies_to)}  # fmt: skip
    data = rule.model_dump()
    with runtime.lock:
        runtime.rules[rule.id] = data
    return {"text": text, "rule": data, "limits_note": notes, "question": None,
            **applies_view(rule.applies_to)}  # fmt: skip


def _closest_compile(bundle: Bundle, text: str) -> tuple[dict | None, bool]:
    presets = bundle.presets.get("compile", [])
    if not presets:
        return None, False
    target = _norm(text)
    for p in presets:
        if _norm(p["text"]) == target:
            return p, True
    words = set(target.split())
    best = max(presets, key=lambda p: len(words & set(_norm(p["text"]).split())))
    return best, False


def _verdict_after_rerun(visit: Visit, proposal: str | None, story: list[StorySentence]) -> str:
    """Recompute with the pure verdict function when available; else keep the stored one."""
    try:
        from vigil.reasoning.verdict import compose

        cited = any(s.event_ids for s in story if s.source == "wonder")
        unresolved = False  # gaps are fixed by perception; a story re-run cannot change them
        return compose(visit.floor, unresolved, proposal, cited)
    except Exception:  # verdict module not ready (NotImplementedError) or other failure
        return visit.verdict or "normal"


def _run_rerun(app: Any, job_id: str, visit_id: str, live: bool, status: LiveStatus | None) -> None:
    bundle: Bundle = app.state.bundle
    guards: Guards = app.state.guards
    runtime: Runtime = app.state.runtime
    backend = app.state.live_backend
    visit = bundle.visit(visit_id)
    assert visit is not None
    with runtime.lock:
        runtime.jobs[job_id]["status"] = "running"
    notice, error, out = None, None, None
    if status is not None and status.available:
        try:
            res = backend.rerun_story(views.visit_ledger(bundle, visit))
            calls = _accept_live(guards, runtime, res)
            story = [StorySentence.model_validate(s) for s in res.payload["story"]]
            validation = res.payload.get("validation") or {}
            wonder = next((c for c in calls if c.purpose == "story"), calls[0] if calls else None)
            if validation.get("passed", False):
                verdict = visit.verdict
                if visit.escalated:
                    verdict = _verdict_after_rerun(visit, res.payload.get("proposal"), story)
                out = _envelope(
                    True, True,
                    {"story": views.sentences_view(bundle, visit, story,
                                                   wonder.model if wonder else None,
                                                   wonder.id if wonder else None),
                     "verdict": verdict,
                     "verdict_label": views.VERDICT_LABELS.get(verdict or "", verdict),
                     "validation": validation},
                    _telemetry_live(calls),
                )  # fmt: skip
            else:
                notice = (
                    "Re-run failed validation twice; showing the recorded story "
                    "and the validator log."
                )
                error = json.dumps(validation.get("failures", []))[:300]
        except Exception as exc:
            error = _failure(guards, exc)
    elif status is not None:
        notice = status.notice
    if out is None:
        preset = bundle.presets.get("rerun", {}).get(visit_id)
        if preset is None:
            preset = {"story": [s.model_dump() for s in visit.story], "verdict": visit.verdict,
                      "validation": {"passed": True, "attempt": 1, "failures": []}}  # fmt: skip
        if error and notice is None:
            notice = _failed_notice(preset)
        story = [StorySentence.model_validate(s) for s in preset["story"]]
        verdict = preset.get("verdict") or visit.verdict
        result = {
            "story": views.sentences_view(bundle, visit, story, preset.get("model"),
                                          preset.get("call_id")),
            "verdict": verdict,
            "verdict_label": views.VERDICT_LABELS.get(verdict or "", verdict),
            "validation": preset.get("validation"),
            "note": preset.get("note"),
        }  # fmt: skip
        out = _envelope(False, live, result, _telemetry_cached(preset), notice, error)
    with runtime.lock:
        runtime.jobs[job_id].update(status="done", result=out)
