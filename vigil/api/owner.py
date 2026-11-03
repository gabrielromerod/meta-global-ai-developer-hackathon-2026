"""Owner routes: Expected Windows, "I'm outside" check-in, visit feedback (FR-029, FR-044).

- `GET /api/windows` lists Expected Guest / Delivery Windows: the recorded ones from the
  bundle (the sandbox's presets) to anyone, plus the ones the owner set, to the owner only.
- `POST /api/windows` and `DELETE /api/windows/{id}` are owner only. A window is set before it
  starts (a few seconds of clock skew at most), lasts at most 12 h, names known cameras or
  zones (none means every perimeter zone), records when it was set (`created_at`), and can be
  cancelled. States follow the clock: scheduled, active, expired; or cancelled.
- `POST /api/checkin` is owner only: a single-use check-in that the pipeline may bind to at
  most one subject chain starting in the next 120 s (FR-044 step 2); unused, it expires in
  30 min. It is never retroactive.

Owner only (`require_owner`) means all of: LAN peer and not the sandbox (`require_lan`);
`VIGIL_OWNER_TOKEN` configured (else 403, owner endpoints disabled); a same-origin request
(Sec-Fetch-Site and Origin, against cross-site forms and `no-cors` fetches); and the token in
`Authorization: Bearer <token>` or `X-Vigil-Owner`, compared in constant time (else 401). The
app also checks the Host header against `VIGIL_TRUSTED_HOSTS` (DNS rebinding). The token is
never logged or echoed.
- `POST /api/visits/{id}/feedback` stores "This was expected" and never changes a verdict.

In edge mode windows and check-ins persist to the edge database (`VIGIL_DB_PATH`), where the
pipeline's `assign_roles` reads them. The hosted sandbox writes nothing.
"""

from __future__ import annotations

import hmac
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, ValidationError

from vigil.api.guards import client_ip, require_lan
from vigil.api.routes import Runtime, _parse, _Req, _state, _visit_or_404
from vigil.models import CheckIn, ExpectedWindow
from vigil.store import db

CHECKIN_BIND_S = 120
CHECKIN_EXPIRES_S = 30 * 60
START_SKEW_S = 5
"""Clock skew only: a window must be set before it starts (FR-029, F11)."""
OWNER_DISABLED = "owner endpoints disabled: set VIGIL_OWNER_TOKEN on the edge machine"
CROSS_SITE = "cross-site request refused: use the Vigil app on this server"
SAME_SITE_VALUES = {"same-origin", "none"}
FEEDBACK_NOTE = (
    "Thanks. This is feedback only: it never changes a verdict. To exempt a future guest or "
    "delivery, set an Expected Window before they arrive."
)
CHECKIN_NOTE = (
    "Checked in. If exactly one person comes into view in the next 120 s, and nobody else "
    "but household members is in view, Vigil treats that person as household. It is single "
    "use, never retroactive, and expires unused after 30 minutes."
)


class WindowRequest(_Req):
    start: datetime
    end: datetime
    cameras: list[str] = Field(default_factory=list, max_length=8)
    zones: list[str] = Field(default_factory=list, max_length=16)
    label: str | None = Field(default=None, max_length=60)


class FeedbackRequest(_Req):
    kind: Literal["expected"]


# ---------------------------------------------------------------------------
# Owner authentication (F2)
# ---------------------------------------------------------------------------


def _supplied_token(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    header = request.headers.get("x-vigil-owner", "").strip()
    return header or None


def _cross_site(request: Request) -> bool:
    """True for a request a browser marks as coming from another site or origin."""
    site = request.headers.get("sec-fetch-site")
    if site is not None and site.strip().lower() not in SAME_SITE_VALUES:
        return True
    origin = request.headers.get("origin")
    if origin is not None:
        own = f"{request.url.scheme}://{request.headers.get('host', '')}".lower()
        if origin.strip().rstrip("/").lower() != own:
            return True
    return False


def require_owner(request: Request) -> None:
    """Dependency for owner endpoints: LAN, token configured, same origin, token matches."""
    require_lan(request)
    secret = getattr(request.app.state.settings, "owner_token", None)
    expected = secret.get_secret_value() if secret is not None else ""
    if not expected:
        raise HTTPException(403, OWNER_DISABLED)
    if _cross_site(request):
        raise HTTPException(403, CROSS_SITE)
    supplied = _supplied_token(request)
    if supplied is None or not hmac.compare_digest(
        supplied.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            401,
            "owner token required: send Authorization: Bearer <VIGIL_OWNER_TOKEN>",
            headers={"WWW-Authenticate": "Bearer"},
        )


def is_owner(request: Request) -> bool:
    try:
        require_owner(request)
    except HTTPException:
        return False
    return True


# ---------------------------------------------------------------------------
# Persistence (edge mode only) and state
# ---------------------------------------------------------------------------


def _tz(request: Request) -> ZoneInfo:
    cfg = request.app.state.config
    name = cfg.timezone if cfg is not None else "America/Los_Angeles"
    return ZoneInfo(name or "America/Los_Angeles")


def _persist(request: Request) -> sqlite3.Connection | None:
    settings = request.app.state.settings
    if settings.mode != "edge":
        return None
    return db.open_db(settings.db_path)


def load_owner_state(settings: Any, runtime: Runtime) -> None:
    """Edge mode: read windows and check-ins already in the edge database (no file created)."""
    path = getattr(settings, "db_path", None)
    if settings.mode != "edge" or path is None or not path.exists():
        return
    conn = db.connect(path)
    try:
        windows, checkins = db.expected_windows(conn), db.checkins(conn)
    except (sqlite3.Error, ValueError, KeyError):
        return  # an older or foreign database: the owner can still set new windows
    finally:
        conn.close()
    with runtime.lock:
        runtime.windows.update({w.id: w for w in windows})
        runtime.checkins.update({c.id: c for c in checkins})


def window_state(w: ExpectedWindow, now: datetime) -> str:
    if w.state == "cancelled":
        return "cancelled"
    if now < w.start:
        return "scheduled"
    return "active" if now < w.end else "expired"


def window_view(w: ExpectedWindow, state: str, recorded: bool) -> dict[str, Any]:
    return {**w.model_dump(mode="json"), "state": state, "recorded": recorded}


def windows_view(request: Request, owner: bool = False) -> list[dict[str, Any]]:
    """Recorded windows for anyone; the owner-set ones only for the owner (F2)."""
    bundle, guards, runtime, _ = _state(request)
    now = guards.now()
    out = [window_view(w, w.state, True) for w in bundle.expected_windows]
    if not owner:
        return out
    with runtime.lock:
        live = sorted(runtime.windows.values(), key=lambda w: (w.start, w.id))
    out += [window_view(w, window_state(w, now), False) for w in live]
    return out


def _aware(dt: datetime, tz: ZoneInfo) -> datetime:
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt


def _known_zones(request: Request) -> set[str] | None:
    cfg = request.app.state.config
    if cfg is None:
        return None
    return {z for cam in cfg.cameras for z in cam.zones}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def owner_router() -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/windows")
    def list_windows(request: Request) -> dict[str, Any]:
        mode = request.app.state.settings.mode
        note = (
            "Sandbox: the recorded evening's windows; owners set windows on the home network."
            if mode == "sandbox"
            else None
        )
        return {"windows": windows_view(request, owner=is_owner(request)), "note": note}

    @r.post("/windows", dependencies=[Depends(require_owner)])
    async def create_window(request: Request) -> dict[str, Any]:
        bundle, guards, runtime, _ = _state(request)
        req: WindowRequest = await _parse(request, WindowRequest)
        tz = _tz(request)
        start, end = _aware(req.start, tz), _aware(req.end, tz)
        now = guards.now()
        if start < now - timedelta(seconds=START_SKEW_S):
            raise HTTPException(422, "Expected Windows are set before they start (FR-029).")
        cfg = request.app.state.config
        cameras = {c.id for c in cfg.cameras} if cfg else {c["id"] for c in bundle.cameras}
        # Recorded examples retain their legacy identifiers; new owner windows use
        # the configured home inventory even when the loaded demo bundle is older.
        if bundle.manifest.get("synthetic"):
            cameras.update(c["id"] for c in bundle.cameras)
        unknown = [c for c in req.cameras if c not in cameras]
        zones = _known_zones(request)
        if zones is not None:
            unknown += [z for z in req.zones if z not in zones]
        if unknown:
            raise HTTPException(422, f"unknown cameras or zones: {', '.join(unknown)}")
        try:
            window = ExpectedWindow(id=f"w_{uuid.uuid4().hex[:8]}", label=req.label,
                                    start=start, end=end, cameras=req.cameras, zones=req.zones,
                                    state="scheduled",
                                    created_at=now.astimezone(tz))  # fmt: skip
        except ValidationError as exc:
            raise HTTPException(422, exc.errors()[0]["msg"]) from exc
        conn = _persist(request)
        if conn is not None:
            with conn:
                created = window.created_at.isoformat() if window.created_at else None
                db.insert_expected_window(conn, window, created_at=created)
            conn.close()
        with runtime.lock:
            runtime.windows[window.id] = window
        return {"window": window_view(window, window_state(window, now), False)}

    @r.delete("/windows/{window_id}", dependencies=[Depends(require_owner)])
    def cancel_window(window_id: str, request: Request) -> dict[str, Any]:
        _, guards, runtime, _ = _state(request)
        now = guards.now()
        with runtime.lock:
            window = runtime.windows.get(window_id)
            if window is None:
                raise HTTPException(404, f"unknown or recorded window {window_id!r}")
            if window_state(window, now) == "expired":
                raise HTTPException(409, "this window has already ended")
            window = window.model_copy(update={"state": "cancelled"})
            runtime.windows[window_id] = window
        conn = _persist(request)
        if conn is not None:
            with conn:
                db.cancel_expected_window(conn, window_id)
            conn.close()
        return {"window": window_view(window, "cancelled", False)}

    @r.post("/checkin", dependencies=[Depends(require_owner)])
    def checkin(request: Request) -> dict[str, Any]:
        _, guards, runtime, _ = _state(request)
        start = guards.now().astimezone(_tz(request))
        session = request.headers.get("x-vigil-session") or request.cookies.get("vigil_session")
        item = CheckIn(
            id=f"c_{uuid.uuid4().hex[:8]}",
            session_id=(session or "lan_owner")[:64],
            start=start,
            expires=start + timedelta(seconds=CHECKIN_EXPIRES_S),
        )
        conn = _persist(request)
        if conn is not None:
            with conn:
                db.insert_checkin(conn, item)
            conn.close()
        with runtime.lock:
            runtime.checkins[item.id] = item
        return {"checkin": item.model_dump(mode="json"), "binds_within_s": CHECKIN_BIND_S,
                "expires_in_s": CHECKIN_EXPIRES_S, "note": CHECKIN_NOTE}  # fmt: skip

    @r.post("/visits/{visit_id}/feedback")
    async def feedback(visit_id: str, request: Request) -> dict[str, Any]:
        bundle, guards, runtime, _ = _state(request)
        guards.check_rate(client_ip(request), guards.feedback_rate)
        req: FeedbackRequest = await _parse(request, FeedbackRequest)
        visit = _visit_or_404(bundle, visit_id)
        with runtime.lock:
            runtime.feedback.append({"visit_id": visit_id, "kind": req.kind,
                                     "at": guards.now().isoformat()})  # fmt: skip
        return {"visit_id": visit_id, "kind": req.kind, "stored": True,
                "verdict": visit.verdict, "note": FEEDBACK_NOTE}  # fmt: skip

    return r
