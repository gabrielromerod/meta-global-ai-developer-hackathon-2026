"""Reolink push alerts on the LAN live stream (FR-032, FR-034).

The camera's own person, vehicle, pet and doorbell alerts arrive over Baichuan TCP push
(port 9000) and are published to the in-process `LiveHub` as `camera_ai` messages, so a phone
or laptop on the home Wi-Fi sees "Person · Porch" while the person is still outside.

Presence only: camera, kind and times. No pixels, boxes or positions, so this layer needs no
privacy review of footage and works with RTSP off. Each upsert is also appended to
``data/live/alerts.jsonl`` (gitignored) so the alerts survive a restart.

Off unless ``VIGIL_LIVE_ALERTS=1``; never in the hosted sandbox.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from vigil.models import CameraAiEvent, CameraCfg
from vigil.reolink.probe import redact

log = logging.getLogger(__name__)

ENABLE_ENV = "VIGIL_LIVE_ALERTS"
LIVE_KINDS = ("person", "vehicle", "pet", "doorbell_press")


def load_reolink_env(env_file: Path, environ: dict | None = None) -> None:
    """Copy only the ``REOLINK_*`` lines of ``.env`` into the process environment.

    ``vigil serve`` reads its own settings through pydantic and does not export ``.env``; the
    camera connection needs the hosts and the shared login. Existing variables win.
    """
    environ = os.environ if environ is None else environ
    if not env_file.is_file():
        return
    from dotenv import dotenv_values

    for key, value in dotenv_values(env_file).items():
        if key.startswith("REOLINK_") and value and key not in environ:
            environ[key] = value


def enabled(mode: str) -> bool:
    return mode != "sandbox" and os.environ.get(ENABLE_ENV) == "1"


def alert_cameras(cameras: Iterable[CameraCfg], env: Mapping[str, str] | None = None):
    """Always-on cameras whose host is set; battery cameras sleep and push nothing."""
    env = os.environ if env is None else env
    return [
        c
        for c in cameras
        if c.power_profile in {"plugin_wifi", "doorbell"}
        and c.source
        and c.source.host_env
        and env.get(c.source.host_env, "").strip()
    ]


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def alert_row(ev: CameraAiEvent, names: Mapping[str, str], session_start: float) -> dict:
    return {
        "id": ev.id,
        "camera_id": ev.camera_id,
        "camera_name": names.get(ev.camera_id, ev.camera_id),
        "kind": ev.kind,
        "started_at": _iso(session_start + ev.t0),
        "ended_at": _iso(None if ev.t1 is None else session_start + ev.t1),
        "open": ev.t1 is None,
    }


async def publish_alerts(
    events: AsyncIterator[CameraAiEvent],
    hub,
    log_path: Path,
    *,
    names: Mapping[str, str],
    session_start: float,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    async for ev in events:
        row = alert_row(ev, names, session_start)
        hub.publish("camera_ai", row)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")


async def run(cameras: Iterable[CameraCfg], hub, data_dir: Path) -> None:
    """Field entry point: subscribe to every always-on camera and publish until cancelled."""
    from vigil.reolink.ai_events import ReolinkAioPushAdapter, stream_ai_events
    from vigil.settings import REPO_ROOT

    load_reolink_env(REPO_ROOT / ".env")
    cams = alert_cameras(cameras)
    if not cams:
        log.warning("live alerts: no always-on camera has a REOLINK_*_HOST set")
        return
    start = time.time()
    try:
        events = stream_ai_events(
            cams, adapter=ReolinkAioPushAdapter(session_start=start), kinds=LIVE_KINDS
        )
        await publish_alerts(
            events,
            hub,
            data_dir / "live" / "alerts.jsonl",
            names={c.id: c.name for c in cams},
            session_start=start,
        )
    except Exception as err:  # the API keeps serving; the alert layer reports and stops
        log.error("live alerts stopped: %s", redact(err))
        hub.publish("lag", {"layer": "camera_ai", "error": "camera alerts disconnected"})
