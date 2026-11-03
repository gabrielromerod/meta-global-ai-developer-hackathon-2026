"""Consumer contract from cached bundle/config, never from frontend fixture JSON."""

import hashlib
import re
from datetime import date as Date
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from vigil.api import views
from vigil.api.owner import is_owner, windows_view
from vigil.ingest.config import privacy_polygons
from vigil.ingest.review import require_privacy_review

VERSION = "vigil-ui/1"
LEGACY_CAMERAS = {"front": "doorbell", "backyard": "backyard_1", "side_right": "front_right_duo"}


def evidence(bundle) -> dict:
    fixture = bool(bundle.manifest.get("synthetic"))
    return {
        "kind": "fixture" if fixture else "real",
        "label": "Demo data" if fixture else "Recorded evidence",
        "source": "Authored synthetic ledger; camera names adapted to seven-camera inventory"
        if fixture
        else "Exported masked visit ledger",
    }


def camera_id(bundle, value: str) -> str:
    return LEGACY_CAMERAS.get(value, value) if bundle.manifest.get("synthetic") else value


def media_url(bundle, url) -> str | None:
    if not isinstance(url, str) or not url.startswith("/media/"):
        return None
    root = (bundle.root / "media").resolve()
    path = (root / url.removeprefix("/media/")).resolve()
    return url if path.is_relative_to(root) and path.is_file() else None


def visit_rows(bundle) -> list[dict]:
    rows = []
    for visit in bundle.visits:
        row = views.visit_summary(bundle, visit)
        detail = views.visit_view(bundle, visit)
        scenario = bundle.scenario(visit.scenario or "") or {}
        subjects = detail["subjects"]
        roles = sorted(set(row["roles"]))
        role_label = (
            views.ROLE_LABELS.get(roles[0], "Unknown origin")
            if len(roles) == 1
            else "Mixed origins"
            if roles
            else "Unknown origin"
        )
        excluded = detail["trace"]["rules_excluded"]
        fired = detail["rule_hits"]
        reason = (
            "The active rule excludes household activity."
            if excluded
            and all(s.actor_role == "household_insider" for s in bundle.subjects_for(visit.id))
            else "An owner rule fired for this visit."
            if fired
            else "An unresolved observation gap remains."
            if any(not g.resolved for g in bundle.gaps_for(visit.id))
            else "No owner rule fired."
        )
        clip = next(
            (
                media_url(bundle, c.get("clip_url"))
                for c in scenario.get("cameras", [])
                if media_url(bundle, c.get("clip_url"))
            ),
            None,
        )
        rows.append(
            {
                **row,
                "cameras": [camera_id(bundle, c) for c in row["cameras"]],
                "title": scenario.get("title") or row["first_sentence"] or "Recorded visit",
                "story": " ".join(s.text for s in visit.story),
                "role_label": role_label,
                "role_basis": "; ".join(
                    s.get("basis_label") or s.get("role_basis") or "" for s in subjects
                ),
                "reason": reason,
                "thumbnail_url": None,
                "clip_url": clip,
                "evidence_kind": evidence(bundle)["kind"],
            }
        )
    return rows


def clip_rows(bundle, visits: list[dict]) -> list[dict]:
    out = []
    classes = {t["id"]: t["cls"] for t in bundle.tables.get("tracks", [])}
    for visit in visits:
        scenario = bundle.scenario(visit["scenario"] or "") or {}
        for cam in visit["cameras"]:
            actual = next(
                (c for c in scenario.get("cameras", []) if camera_id(bundle, c["id"]) == cam), {}
            )
            types = {
                classes.get(e.track_id)
                for e in bundle.events_for(visit["id"])
                if camera_id(bundle, e.camera_id) == cam
            }
            out.append(
                {
                    "id": f"clip_{visit['id']}_{cam}",
                    "visit_id": visit["id"],
                    "camera_id": cam,
                    "verdict": visit["verdict"],
                    "clock": visit["clock"],
                    "t0": visit["t0"],
                    "t1": visit["t1"],
                    "title": visit["first_sentence"] or "Recorded visit evidence",
                    "kind": "vehicle"
                    if "car" in types
                    else "package"
                    if "package" in types
                    else "person",
                    "clip_url": media_url(bundle, actual.get("clip_url")),
                    "thumbnail_url": None,
                    "source_label": "Demo data"
                    if bundle.manifest.get("synthetic")
                    else bundle.manifest.get("source_label", "Event clips"),
                }
            )
    return out


def event_rows(bundle) -> list[dict]:
    names = views.camera_names(bundle)
    return [
        {
            **views.citation(bundle, e),
            "camera_id": camera_id(bundle, e.camera_id),
            "camera_name": names.get(e.camera_id, e.camera_id),
            "visit_id": e.visit_id,
        }
        for e in bundle.events
    ]


def camera_event_rows(bundle) -> list[dict]:
    rows = {event["id"]: event for event in bundle.tables.get("camera_ai_events", [])}
    return [
        {
            **row,
            "camera_id": camera_id(bundle, row["camera_id"]),
            "layer": "camera_ai",
            "clock": views.clock(bundle, row["t0"]),
        }
        for row in sorted(rows.values(), key=lambda r: (r["t0"], r["id"]))
    ]


def ui_state(request: Request) -> dict:
    bundle = request.app.state.bundle
    cfg = request.app.state.config
    runtime = request.app.state.runtime
    settings = request.app.state.settings
    visits = visit_rows(bundle)
    clips = clip_rows(bundle, visits)
    cameras = []
    for cam in cfg.cameras if cfg else []:
        try:
            require_privacy_review(
                cam, privacy_polygons(cfg, cam.id, settings.config_path.parent / "privacy")
            )
            status = "not_connected"
        except ValueError:
            status = "privacy_blocked"
        imported = cam.power_profile in {"battery_wifi", "import"} and cam.hub_present is not True
        cameras.append(
            {
                "id": cam.id,
                "name": cam.name,
                "model": cam.model,
                "power_profile": cam.power_profile,
                "stream": cam.source.stream if cam.source else "main",
                "status": status,
                "privacy_reviewed": status != "privacy_blocked" and cam.evidence_kind == "real",
                "source_label": "Imported clips"
                if imported
                else "Privacy review required"
                if status == "privacy_blocked"
                else "Not connected",
                "hub_present": cam.hub_present,
                "wifi_signal_dbm": None,
                "clock_offset_s": cam.clock_offset_s,
                "clip_url": next(
                    (c["clip_url"] for c in clips if c["camera_id"] == cam.id and c["clip_url"]),
                    None,
                ),
                "thumbnail_url": None,
            }
        )
    groups = [
        ("overview", "Overview", [c["id"] for c in cameras]),
        ("day", "Day", [c["id"] for c in cameras]),
        ("night", "Night", [c["id"] for c in cameras]),
        (
            "front-garden",
            "Front garden",
            [c["id"] for c in cameras if c["id"].startswith("front_")],
        ),
        ("porch", "Porch", [c["id"] for c in cameras if c["id"] in {"porch", "doorbell"}]),
        ("left-passage", "Left passage", [c["id"] for c in cameras if c["id"] == "side_left"]),
        ("backyard", "Backyard", [c["id"] for c in cameras if c["id"].startswith("backyard")]),
    ]
    rank = {"needs_attention": 0, "cant_confirm": 1, "noteworthy": 2, "normal": 3}
    attention = sorted(visits, key=lambda v: (rank.get(v["verdict"], 3), -v["t0"]))
    enabled = is_owner(request)
    notifications = [
        {
            "id": "notice_" + v["id"],
            "visit_id": v["id"],
            "verdict": v["verdict"],
            "story": v["first_sentence"],
            "clock": v["clock"],
            "thumbnail_url": v["thumbnail_url"],
            "unread": True,
        }
        for v in sorted(visits, key=lambda v: -v["t0"])
    ]
    measured = bundle.manifest.get("prefilter_counts") or {}
    return {
        "contract_version": VERSION,
        "evidence": evidence(bundle),
        "mode": settings.mode,
        "household": {"name": "Home", "avatar_url": None},
        "session": {
            "id": bundle.manifest.get(
                "session_id", "synthetic" if bundle.manifest.get("synthetic") else "recorded"
            ),
            "start": bundle.manifest.get("session_start"),
        },
        "cameras": cameras,
        "views": [{"id": id, "label": label, "camera_ids": ids} for id, label, ids in groups]
        + [
            {"id": "camera-" + c["id"], "label": c["name"], "camera_ids": [c["id"]]}
            for c in cameras
        ],
        "summary": {
            "camera_events": measured.get("camera_events"),
            "on_property": measured.get("on_property"),
            "visits": len(visits),
            "needs_attention": sum(v["verdict"] == "needs_attention" for v in visits),
            "street_events": measured.get("street_events"),
            "note": "Recorded session; camera prefilter and street counts are unmeasured."
            if not measured
            else "Counts from the recorded camera event ledger.",
        },
        "visits": visits,
        "attention_ids": [v["id"] for v in attention if v["verdict"] != "normal"][:5],
        "notifications": notifications,
        "clips": clips,
        "events": event_rows(bundle),
        "camera_events": camera_event_rows(bundle),
        "rules": _rules(runtime),
        "protected_objects": bundle.protected_objects,
        "benchmark": {
            "measured": False,
            "metrics": [],
            "note": "No real-camera benchmark has been measured.",
        },
        "owner": {
            "enabled": enabled,
            "reason": "Owner controls available" if enabled else "Owner-only on the home box",
            "checkin_duration_s": 120,
            "windows": windows_view(request, owner=enabled),
        },
        "capabilities": {
            "ask_home": True,
            "household_messaging": "local_mock",
            "snapshot": any(c["clip_url"] for c in clips),
            "recording": False,
            "owner": enabled,
        },
    }


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(max_length=64)
    text: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(max_length=128)


def _rules(runtime) -> list[dict]:
    with runtime.lock:
        return [dict(rule) for rule in runtime.rules.values()]


def consumer_router() -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/ui/state")
    def state(request: Request):
        return ui_state(request)

    @r.get("/ui/twin")
    def twin(request: Request):
        from vigil.spatial.public import public_twin

        cfg = request.app.state.config
        bundle = request.app.state.bundle
        result = (
            public_twin(cfg) if cfg else {"generic_massing": True, "glb_url": None, "cameras": []}
        )
        if bundle.manifest.get("synthetic"):
            result["blind_regions"] = bundle.twin.get("blind_regions", [])
        result["evidence"] = evidence(bundle)
        return result

    @r.get("/ui/visits/{visit_id}/positions")
    def positions(visit_id: str, request: Request):
        bundle = request.app.state.bundle
        visit = bundle.visit(visit_id)
        if visit is None:
            raise HTTPException(404, "Unknown visit")
        result = views.positions_view(bundle, visit)
        for position in result["positions"]:
            position["cameras"] = [camera_id(bundle, c) for c in position["cameras"]]
        for gap in result["gaps"]:
            for key in ("from_camera", "to_camera"):
                if gap.get(key):
                    gap[key] = camera_id(bundle, gap[key])
        result["events"] = [e for e in event_rows(bundle) if e["visit_id"] == visit_id]
        return result

    @r.get("/ui/visits/{visit_id}")
    def visit_detail(visit_id: str, request: Request):
        from vigil.perception.overlays import player_overlays

        bundle = request.app.state.bundle
        visit = bundle.visit(visit_id)
        if visit is None:
            raise HTTPException(404, "Unknown visit")
        result = views.visit_view(bundle, visit)
        scenario = bundle.scenario(visit.scenario or "") or {}
        state = ui_state(request)
        inventory = {c["id"]: c for c in state["cameras"]}

        def normalize(value):
            if isinstance(value, list):
                return [normalize(v) for v in value]
            if not isinstance(value, dict):
                return value
            return {
                key: camera_id(bundle, child)
                if key in {"camera_id", "from_camera", "to_camera"} and isinstance(child, str)
                else [camera_id(bundle, c) for c in child]
                if key == "cameras" and isinstance(child, list)
                else normalize(child)
                for key, child in value.items()
            }

        result = normalize(result)
        playback = []
        for camera in scenario.get("cameras", []):
            cid = camera_id(bundle, camera["id"])
            if cid not in inventory:
                continue
            pose = views.twin_camera(bundle, camera["id"]) or {}
            playback.append(
                {
                    "id": cid,
                    "name": inventory[cid]["name"],
                    "clip_t0": camera.get("clip_t0", scenario.get("t0", visit.t0)),
                    "clip_url": media_url(bundle, camera.get("clip_url")),
                    "width": pose.get("width", 1280),
                    "height": pose.get("height", 720),
                    "source_label": state["evidence"]["label"],
                }
            )
        track_visits = {tid: v.id for v in bundle.visits for tid in v.track_ids}
        overlays = {}
        for cid, tracks in player_overlays(bundle.overlays, track_visits).items():
            keep = {tid: row for tid, row in tracks.items() if row.get("visit_id") == visit_id}
            if keep:
                overlays[camera_id(bundle, cid)] = keep
        return {
            **result,
            "evidence": state["evidence"],
            "playback_cameras": playback,
            "overlays": overlays,
            "playback_t0": scenario.get("t0", visit.t0),
            "playback_t1": scenario.get("t1", visit.t1),
        }

    @r.get("/ui/search")
    def search(
        request: Request,
        q: str = "",
        camera: str = "",
        verdict: str = "",
        start: str = "",
        end: str = "",
        kind: str = "",
    ):
        state = ui_state(request)
        try:
            lo = datetime.fromisoformat(start) if start else None
            hi = datetime.fromisoformat(end) if end else None
            if any(t.utcoffset() is None for t in (lo, hi) if t) or (lo and hi and lo > hi):
                raise ValueError
        except ValueError:
            raise HTTPException(
                422, "Time filters need timezone-aware ISO-8601 values in increasing order"
            ) from None
        base = views.session_start(request.app.state.bundle)

        def matches(v):
            stamp = base + timedelta(seconds=v["t0"]) if base else None
            return (
                (not q or q.casefold() in (v["story"] + " " + v["title"]).casefold())
                and (not camera or camera in v["cameras"])
                and (not verdict or verdict == v["verdict"])
                and (not lo or (stamp is not None and stamp >= lo))
                and (not hi or (stamp is not None and stamp <= hi))
            )

        visits = [v for v in state["visits"] if matches(v)]
        ids = {v["id"] for v in visits}
        clips = [
            c
            for c in state["clips"]
            if c["visit_id"] in ids
            and (not camera or c["camera_id"] == camera)
            and (not kind or c["kind"] == kind)
        ]
        if kind:
            ids = {c["visit_id"] for c in clips}
            visits = [v for v in visits if v["id"] in ids]
        return {
            "contract_version": VERSION,
            "evidence": state["evidence"],
            "visits": visits,
            "clips": clips,
        }

    @r.get("/ui/events")
    def today_events(request: Request, date: Date | None = None):
        bundle = request.app.state.bundle
        tz = ZoneInfo(bundle.manifest.get("timezone", "America/Los_Angeles"))
        day = date or request.app.state.guards.now().astimezone(tz).date()
        start = views.session_start(bundle)
        events = [
            e
            for e in event_rows(bundle)
            if start and (start + timedelta(seconds=e["t"])).astimezone(tz).date() == day
        ]
        sensor_events = [
            e
            for e in camera_event_rows(bundle)
            if start and (start + timedelta(seconds=e["t0"])).astimezone(tz).date() == day
        ]
        counts = bundle.manifest.get("prefilter_counts")
        ids = {e["id"] for e in sensor_events}
        street = None
        if counts is not None and not ids.intersection(counts.get("unclassified_event_ids", [])):
            street = len(ids.intersection(counts.get("street_event_ids", [])))
        return {
            "date": day.isoformat(),
            "evidence": evidence(bundle),
            "events": events,
            "street_events": street,
            "camera_events": sensor_events,
        }

    @r.get("/ui/notifications")
    def notifications(request: Request):
        return {"notifications": ui_state(request)["notifications"]}

    @r.get("/ui/clips")
    def clips(request: Request):
        return {"clips": ui_state(request)["clips"]}

    @r.get("/ui/chat")
    def chat(request: Request):
        return {
            "contract_version": VERSION,
            "evidence": evidence(request.app.state.bundle),
            "threads": [
                {
                    "id": "ask-home",
                    "title": "Ask your home",
                    "kind": "assistant",
                    "note": "Answers use the cached visit ledger.",
                    "messages": [],
                },
                {
                    "id": "household",
                    "title": "Household",
                    "kind": "local_mock",
                    "note": "Local to this browser. Messages are not sent to other people.",
                    "messages": [],
                },
            ],
        }

    @r.post("/chat/ask")
    def ask(body: AskRequest, request: Request):
        if body.thread_id != "ask-home":
            raise HTTPException(400, "Household messages stay local to the browser")
        bundle = request.app.state.bundle
        terms = {
            word
            for word in re.findall(r"[\w]+", body.text.casefold())
            if len(word) > 2
            and word
            not in {
                "what",
                "when",
                "where",
                "happened",
                "about",
                "show",
                "tell",
                "the",
                "was",
                "did",
                "home",
                "your",
            }
        }
        matches = []
        for visit in bundle.visits:
            for sentence in visit.story:
                words = set(re.findall(r"[\w]+", sentence.text.casefold()))
                score = len(terms & words)
                if score and sentence.event_ids:
                    matches.append((score, visit, sentence))
        matches.sort(key=lambda row: (-row[0], -row[1].t0))
        selected = matches[:3]
        text = (
            " ".join(s.text for _, _, s in selected)
            if selected
            else "No matching observations were found in the cached visit ledger."
        )
        cites = [
            {"visit_id": v.id, "event_id": eid}
            for _, v, s in selected
            for eid in s.event_ids
            if any(e.id == eid for e in bundle.events_for(v.id))
        ]
        key = hashlib.sha256((body.session_id + "\0" + body.text).encode()).hexdigest()[:20]
        return {
            "message": {
                "id": "answer_" + key,
                "author": "vigil",
                "text": text,
                "citations": cites,
                "clip_id": None,
            }
        }

    return r
