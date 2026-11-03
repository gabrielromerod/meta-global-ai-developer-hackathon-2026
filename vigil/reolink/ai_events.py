"""Reolink TCP-push person/vehicle events as `camera_ai` events (FR-032, spec 5.13).

Reolink cameras and NVRs push Baichuan messages over TCP; reolink_aio parses cmd_id 33
(`AlarmEventList/AlarmEvent` with `channelId`, `status` "MD"/"none" and `AItype`, a comma
list of "people", "vehicle", "dog_cat", "other" or "none") and updates `Host` state
before calling registered callbacks (`host.baichuan.register_callback(id, cb, cmd_id)`,
callbacks take no arguments). Both routes converge on `PushState` snapshots:

- `parse_alarm_xml()` turns a recorded cmd_id 33 XML payload into `PushState`s (tests,
  replay of recorded sessions);
- `ReolinkAioPushAdapter` (field only, lazy reolink_aio import) snapshots
  `host.motion_detected(ch)` / `host.ai_detected(ch, type)` on every push.

`AiEventTracker` turns snapshots into `CameraAiEvent`s: it opens an event when a kind
turns on (emitted at once with `t1=None` so the UI cone pulses immediately), ignores
repeated "still on" pushes (dedupe), closes it when the kind turns off (re-emitted with
`t1`), and re-opens the same id when the kind flickers back within `debounce_s`.
Emissions are therefore upserts keyed by event id.

Times: push messages carry no usable timestamp (`timeStamp` is 0 on the cameras seen by
reolink_aio), so `t` is the edge machine's receive time on the session clock.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from vigil.models import CameraAiEvent, CameraCfg
from vigil.reolink.probe import (
    ReolinkUnavailable,
    camera_credentials,
    channel_index,
    import_reolink_host,
    redact,
)

__all__ = [
    "AiEventTracker",
    "PushAdapter",
    "PushState",
    "ReolinkAioPushAdapter",
    "ReolinkUnavailable",
    "parse_alarm_xml",
    "stream_ai_events",
]

log = logging.getLogger(__name__)

# reolink_aio AI type -> CameraAiEvent.kind
AI_KIND = {
    "people": "person",
    "person": "person",
    "vehicle": "vehicle",
    "dog_cat": "pet",
    "visitor": "doorbell_press",
}
DEFAULT_KINDS: tuple[str, ...] = ("person", "vehicle", "doorbell_press")


@dataclass(frozen=True)
class PushState:
    """One channel's detection state after a push (reolink_aio naming)."""

    host_key: str
    """The camera's `source.host_env` name: identifies the device without its address."""
    channel: int
    """0-based reolink_aio channel index."""
    t: float
    motion: bool
    ai: dict[str, bool] = field(default_factory=dict)


def parse_alarm_xml(xml: str, host_key: str, t: float) -> list[PushState]:
    """Parse a Baichuan cmd_id 33 `AlarmEventList` payload. Unparseable input gives []."""
    try:
        root = ET.fromstring(xml)  # noqa: S314 - LAN device payload, small, no DTD
    except ET.ParseError:
        log.debug("ignoring non-XML push payload")
        return []
    states: list[PushState] = []
    for event in root.iter("AlarmEvent"):
        ch_text = event.findtext("channelId")
        if ch_text is None or not ch_text.strip().lstrip("-").isdigit():
            continue
        status = (event.findtext("status") or "").strip()
        ai_text = (event.findtext("AItype") or "").strip()
        ai_list = [a.strip() for a in ai_text.split(",") if a.strip()]
        motion = "MD" in status or "other" in ai_list
        ai = {name: name in ai_list for name in ("people", "vehicle", "dog_cat")}
        if "visitor" in status:
            ai["visitor"] = True
        states.append(PushState(host_key, int(ch_text), t, motion, ai))
    return states


def _event_id(camera_id: str, kind: str, t0: float) -> str:
    digest = hashlib.sha1(f"{camera_id}|{kind}|{t0:.3f}".encode(), usedforsecurity=False)
    return f"cai_{camera_id}_{kind}_{digest.hexdigest()[:8]}"


@dataclass
class _Open:
    event: CameraAiEvent
    closed_at: float | None = None


class AiEventTracker:
    """State machine from push snapshots to `CameraAiEvent` upserts (FR-032)."""

    def __init__(
        self,
        cams: Iterable[CameraCfg],
        *,
        debounce_s: float = 3.0,
        kinds: Iterable[str] = DEFAULT_KINDS,
    ) -> None:
        self.debounce_s = debounce_s
        self.kinds = tuple(kinds)
        self._cam_by_key: dict[tuple[str, int], str] = {}
        for cam in cams:
            if cam.source and cam.source.host_env:
                self._cam_by_key[(cam.source.host_env, channel_index(cam))] = cam.id
        self._state: dict[tuple[str, str], _Open] = {}

    def camera_for(self, host_key: str, channel: int) -> str | None:
        return self._cam_by_key.get((host_key, channel))

    def _active_kinds(self, s: PushState) -> set[str]:
        active = {AI_KIND[k] for k, on in s.ai.items() if on and k in AI_KIND}
        if s.motion:
            active.add("motion")
        return active & set(self.kinds)

    def update(self, s: PushState) -> list[CameraAiEvent]:
        cam_id = self.camera_for(s.host_key, s.channel)
        if cam_id is None:
            log.debug("push for unconfigured device channel %s/%s ignored", s.host_key, s.channel)
            return []
        active = self._active_kinds(s)
        out: list[CameraAiEvent] = []
        for kind in self.kinds:
            key = (cam_id, kind)
            cur = self._state.get(key)
            if kind in active:
                if cur is None or (
                    cur.closed_at is not None
                    and s.t - cur.closed_at > (0 if kind == "doorbell_press" else self.debounce_s)
                ):
                    ev = CameraAiEvent(
                        id=_event_id(cam_id, kind, s.t), camera_id=cam_id, kind=kind, t0=s.t
                    )
                    self._state[key] = _Open(ev)
                    out.append(ev.model_copy())
                elif cur.closed_at is not None:  # flicker inside the debounce: re-open
                    cur.closed_at = None
                    cur.event.t1 = None
                    out.append(cur.event.model_copy())
                # else: still on, duplicate push -> nothing
            elif cur is not None and cur.closed_at is None:
                cur.closed_at = s.t
                cur.event.t1 = s.t
                out.append(cur.event.model_copy())
        for ev in out:
            log.info("camera_ai %s %s t0=%.1f t1=%s", ev.camera_id, ev.kind, ev.t0, ev.t1)
        return out

    def flush(self, t: float) -> list[CameraAiEvent]:
        """Close every open event at `t` (stream ended or capture stopped)."""
        out: list[CameraAiEvent] = []
        for cur in self._state.values():
            if cur.closed_at is None:
                cur.closed_at = t
                cur.event.t1 = t
                out.append(cur.event.model_copy())
        return out


class PushAdapter(Protocol):
    def states(self, cams: list[CameraCfg]) -> AsyncIterator[PushState]: ...


async def stream_ai_events(
    cams: list[CameraCfg],
    adapter: PushAdapter | None = None,
    *,
    debounce_s: float = 3.0,
    kinds: Iterable[str] = DEFAULT_KINDS,
) -> AsyncIterator[CameraAiEvent]:
    """Yield `CameraAiEvent` upserts as pushes arrive; closes open events at the end."""
    if adapter is None:
        adapter = ReolinkAioPushAdapter()
    tracker = AiEventTracker(cams, debounce_s=debounce_s, kinds=kinds)
    last_t = 0.0
    async for state in adapter.states(cams):
        last_t = max(last_t, state.t)
        for ev in tracker.update(state):
            yield ev
    for ev in tracker.flush(last_t):
        yield ev


class ReolinkAioPushAdapter:
    """Field adapter: one reolink_aio Host per device, Baichuan TCP push subscription."""

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        session_start: float | None = None,
    ) -> None:
        self._host_cls = import_reolink_host()
        self.clock = clock
        self.session_start = clock() if session_start is None else session_start

    async def states(self, cams: list[CameraCfg]) -> AsyncIterator[PushState]:
        queue: asyncio.Queue[PushState] = asyncio.Queue()
        hosts: dict[str, object] = {}
        channels: dict[str, set[int]] = {}
        for cam in cams:
            creds = camera_credentials(cam)
            key = cam.source.host_env  # type: ignore[union-attr]
            channels.setdefault(key, set()).add(channel_index(cam))
            if key in hosts:
                continue
            host = self._host_cls(
                creds.host, creds.user.get_secret_value(), creds.password.get_secret_value()
            )
            hosts[key] = host
        try:
            for key, host in hosts.items():
                await host.get_host_data()  # type: ignore[attr-defined]

                def snapshot(key: str = key, host: object = host) -> None:
                    t = self.clock() - self.session_start
                    for ch in sorted(channels[key]):
                        types = host.ai_supported_types(ch)  # type: ignore[attr-defined]
                        ai = {a: bool(host.ai_detected(ch, a)) for a in types}  # type: ignore[attr-defined]
                        if hasattr(host, "visitor_detected") and host.visitor_detected(ch):
                            ai["visitor"] = True
                        motion = bool(host.motion_detected(ch))  # type: ignore[attr-defined]
                        queue.put_nowait(PushState(key, ch, t, motion, ai))

                host.baichuan.register_callback(f"vigil_{key}", snapshot, 33)  # type: ignore[attr-defined]
                await host.baichuan.subscribe_events()  # type: ignore[attr-defined]
                log.info("subscribed to TCP push for %s", key)
            while True:
                yield await queue.get()
        except Exception as err:
            log.error("TCP push stream failed: %s", redact(err))
            raise
        finally:
            for host in hosts.values():
                try:
                    await host.baichuan.unsubscribe_events()  # type: ignore[attr-defined]
                    await host.logout()  # type: ignore[attr-defined]
                except Exception as err:  # pragma: no cover - field cleanup
                    log.warning("logout failed: %s", redact(err))
