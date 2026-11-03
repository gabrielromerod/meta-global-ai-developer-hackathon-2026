"""LAN-only routes: live server-sent events (FR-034), SAM landmark proposals and calibration
pairs (FR-037).

All are refused in the hosted sandbox and for any non-private client (spec 9.6). The hub is
an in-process broadcaster: the edge pipeline (capture, Reolink events, SAM, locate) publishes
`camera_ai`, `tracks`, `positions` and `visits` messages; phones on the home Wi-Fi subscribe.
Capture itself is blocked on field hardware (T-26), so nothing publishes yet outside tests.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from vigil.api.backend import LandmarksBlockedError, LiveUnavailableError
from vigil.api.guards import (
    LIVE_ESTIMATE_USD,
    check_live_allowed,
    client_ip,
    read_bounded,
    require_lan,
)

PAIRS_NEEDED = 6  # PnP with RANSAC on 6 points; 2 more are held out (spec 7)
KINDS = {"camera_ai", "tracks", "positions", "visits", "lag"}


class LiveHub:
    """Thread-safe fan-out with a short replay buffer for clients that connect late."""

    def __init__(self, replay: int = 50) -> None:
        self._recent: deque[tuple[str, dict[str, Any]]] = deque(maxlen=replay)
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()
        self.closed = False

    def publish(self, kind: str, data: dict[str, Any]) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown live event kind {kind!r}")
        item = (kind, data)
        with self._lock:
            self._recent.append(item)
            subs = list(self._subs)
        for loop, queue in subs:
            loop.call_soon_threadsafe(queue.put_nowait, item)

    def subscribe(self) -> tuple[asyncio.Queue, list[tuple[str, dict[str, Any]]]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.append((loop, queue))
            return queue, list(self._recent)

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [(lp, q) for lp, q in self._subs if q is not queue]

    def close(self) -> None:
        self.closed = True
        with self._lock:
            subs = list(self._subs)
        for loop, queue in subs:
            loop.call_soon_threadsafe(queue.put_nowait, None)


LANDMARKS_BLOCKED = (
    "SAM 3.1 landmark proposals are not available yet (FR-037, spatial workstream). Pick 6 "
    "fixed landmarks by hand instead: door frames, gate posts, shed or window corners."
)


class LandmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera_id: str = Field(max_length=64)


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera_id: str = Field(max_length=64)
    pixel: tuple[float, float]
    world: tuple[float, float, float]


def live_router() -> APIRouter:
    r = APIRouter(prefix="/api", dependencies=[Depends(require_lan)])

    @r.get("/live/stream")
    async def stream(request: Request, max_events: int | None = None) -> EventSourceResponse:
        hub: LiveHub = request.app.state.live_hub

        async def events():
            queue, recent = hub.subscribe()
            sent = 0
            try:
                yield {"event": "hello", "data": json.dumps({"mode": "edge"})}
                sent += 1
                for kind, data in recent:
                    if max_events is not None and sent >= max_events:
                        return
                    yield {"event": kind, "data": json.dumps(data)}
                    sent += 1
                while not hub.closed and (max_events is None or sent < max_events):
                    if await request.is_disconnected():
                        return
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        continue
                    if item is None:
                        return
                    yield {"event": item[0], "data": json.dumps(item[1])}
                    sent += 1
            finally:
                hub.unsubscribe(queue)

        return EventSourceResponse(events(), ping=15)

    @r.post("/spatial/landmarks")
    async def landmarks(request: Request) -> dict[str, Any]:
        """SAM 3.1 proposes fixed landmarks on a camera still (UC-10 step 3)."""
        from vigil.api.routes import _accept_live, _failure, _telemetry_live

        settings = request.app.state.settings
        body = await read_bounded(request, int(settings.max_json_bytes))
        try:
            req = LandmarkRequest.model_validate_json(body or b"{}")
        except ValueError as exc:
            raise HTTPException(422, "expected {camera_id}") from exc
        names = {c["id"] for c in request.app.state.bundle.cameras}
        if req.camera_id not in names:
            raise HTTPException(422, f"unknown camera {req.camera_id!r}")
        out: dict[str, Any] = {"camera_id": req.camera_id, "blocked": False, "proposals": [],
                               "notice": None, "error": None, "telemetry": None}  # fmt: skip
        backend = request.app.state.live_backend
        if not callable(getattr(backend, "propose_landmarks", None)):
            return {**out, "blocked": True, "notice": LANDMARKS_BLOCKED}
        guards = request.app.state.guards
        status = check_live_allowed(guards, client_ip(request), LIVE_ESTIMATE_USD["landmarks"])
        if not status.available:
            return {**out, "notice": status.notice}
        try:
            res = backend.propose_landmarks(req.camera_id)
        except LandmarksBlockedError:
            return {**out, "blocked": True, "notice": LANDMARKS_BLOCKED}
        except LiveUnavailableError as exc:  # e.g. no still frame for this camera yet
            return {**out, "notice": f"Landmark proposals unavailable: {exc}. Click them by hand."}
        except Exception as exc:  # degrade with a notice, never a blank tool
            return {**out, "notice": "Live call failed; click the landmarks by hand.",
                    "error": _failure(guards, exc)}  # fmt: skip
        calls = _accept_live(guards, request.app.state.runtime, res)
        proposals = list(res.payload.get("proposals") or [])
        return {**out, "proposals": proposals, "telemetry": _telemetry_live(calls)}

    @r.post("/spatial/pairs")
    async def pairs(request: Request) -> dict[str, Any]:
        settings = request.app.state.settings
        body = await read_bounded(request, int(settings.max_json_bytes))
        try:
            pair = PairRequest.model_validate_json(body or b"{}")
        except ValueError as exc:
            raise HTTPException(
                422, "expected {camera_id, pixel: [u, v], world: [x, y, z]}"
            ) from exc
        names = {c["id"] for c in request.app.state.bundle.cameras}
        if pair.camera_id not in names:
            raise HTTPException(422, f"unknown camera {pair.camera_id!r}")
        runtime = request.app.state.runtime
        with runtime.lock:
            rows = runtime.pairs.setdefault(pair.camera_id, [])
            rows.append({"pixel": list(pair.pixel), "world": list(pair.world)})
            count = len(rows)
            snapshot = list(rows)
        out: dict[str, Any] = {
            "camera_id": pair.camera_id,
            "pairs": count,
            "needed": PAIRS_NEEDED,
            "extrinsics": None,
            "note": None,
        }
        if count >= PAIRS_NEEDED:
            out.update(_solve(request, pair.camera_id, snapshot))
        return out

    return r


def _solve(request: Request, camera_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Hand the pairs to the extrinsic solver (FR-037) if it is available."""
    try:
        import math

        from vigil.models import Intrinsics
        from vigil.spatial.calibrate import calibrate_extrinsics

        cam = next(
            (c for c in request.app.state.bundle.twin.get("cameras", []) if c["id"] == camera_id),
            {},
        )
        w, h = cam.get("width", 1280), cam.get("height", 720)
        fx = (w / 2) / math.tan(math.radians(cam.get("hfov_deg", 90.0)) / 2)
        k = Intrinsics(k=[[fx, 0, w / 2], [0, fx, h / 2], [0, 0, 1]], width=w, height=h,
                       fov_fallback=True)  # fmt: skip
        pairs = [(tuple(r["pixel"]), tuple(r["world"])) for r in rows]
        ext = calibrate_extrinsics(pairs, k)
        return {"extrinsics": ext.model_dump(), "note": "Intrinsics from the lens field of view."}
    except Exception as exc:  # solver not ready yet, or the pairs are degenerate
        return {"note": f"Extrinsic solver unavailable: {type(exc).__name__}: {exc}"[:300]}
