"""The closed loop (FR-020, NFR-016, spec 5.7 and 5.10): Wonder proposes, code disposes.

A watch proposal becomes an active watch only when it comes from a validated draft, its
camera exists, its phrase (normalised: trimmed, lower case, single spaces) is exactly an
allowlist entry, the same phrase is not already watched on that camera, and the camera has
fewer than 4 active watches. Accepted watches expire after 24 h; the owner can undo them.
Every rejection is returned with its reason and logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from vigil.models import Watch, WatchProposal

log = logging.getLogger(__name__)

ALLOWLIST_PATH = Path(__file__).resolve().parents[2] / "config" / "allowlist.json"
MAX_WATCHES_PER_CAMERA = 4
WATCH_TTL = timedelta(hours=24)


class LoopResult(BaseModel):
    """Accepted and rejected proposals (module-local; requested for vigil.models)."""

    model_config = ConfigDict(extra="forbid")

    accepted: list[Watch] = Field(default_factory=list)
    rejected: list[Watch] = Field(default_factory=list)


def load_allowlist(path: Path | str = ALLOWLIST_PATH) -> set[str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw["phrases"] if isinstance(raw, dict) else raw
    return {normalise(p) for p in items}


def normalise(phrase: str) -> str:
    return " ".join(phrase.split()).lower()


def is_active(w: Watch, now: datetime) -> bool:
    if w.origin == "wonder" and w.expires_at is not None and now < w.expires_at - WATCH_TTL:
        return False
    return w.status == "watching" and (w.expires_at is None or w.expires_at > now)


def _watch_id(camera_id: str, phrase: str, visit_id: str | None, now: datetime) -> str:
    key = f"{camera_id}|{phrase}|{visit_id}|{now.isoformat()}"
    return "w_" + hashlib.sha256(key.encode()).hexdigest()[:10]


def accept_watches(
    proposals: Sequence[WatchProposal],
    cameras: Collection[str],
    allowlist: Collection[str],
    active: Iterable[Watch],
    now: datetime,
    source_visit_id: str | None,
    *,
    validated: bool,
    visit_event_ids: Collection[str] | None = None,
    origin: str = "wonder",
) -> LoopResult:
    """Turn proposals into watches. `validated` must say the draft passed the validator."""
    allowed = {normalise(p) for p in allowlist}
    current = [w for w in active if is_active(w, now)]
    per_camera: dict[str, int] = {}
    watched: set[tuple[str, str]] = set()
    for w in current:
        per_camera[w.camera_id] = per_camera.get(w.camera_id, 0) + 1
        watched.add((w.camera_id, normalise(w.phrase)))

    result = LoopResult()
    for p in proposals:
        phrase = normalise(p.phrase)
        reason: str | None = None
        if not validated:
            reason = "proposal is not from a validated draft"
        elif p.camera_id not in cameras:
            reason = f"unknown camera {p.camera_id!r}"
        elif phrase not in allowed:
            reason = "phrase is not in the watch allowlist"
        elif visit_event_ids is not None and p.reason_event_id not in visit_event_ids:
            reason = f"reason event {p.reason_event_id!r} is not in this visit"
        elif (p.camera_id, phrase) in watched:
            reason = f"already watching {phrase!r} on {p.camera_id}"
        elif per_camera.get(p.camera_id, 0) >= MAX_WATCHES_PER_CAMERA:
            reason = f"cap of {MAX_WATCHES_PER_CAMERA} active watches on {p.camera_id} reached"

        wid = _watch_id(p.camera_id, phrase, source_visit_id, now)
        if reason is not None:
            log.warning(
                "watch proposal rejected: camera=%r phrase=%r reason=%s",
                p.camera_id,
                p.phrase[:80],
                reason,
            )
            result.rejected.append(
                Watch(
                    id=wid,
                    camera_id=p.camera_id,
                    phrase=p.phrase[:200],
                    origin=origin,
                    status="rejected",
                    source_visit_id=source_visit_id,
                    reason=reason,
                )
            )
            continue
        watch = Watch(
            id=wid,
            camera_id=p.camera_id,
            phrase=phrase,
            origin=origin,
            status="watching",
            expires_at=now + WATCH_TTL,
            source_visit_id=source_visit_id,
            reason=f"proposed from event {p.reason_event_id}",
        )
        log.info("watch accepted: %s %r on %s", wid, phrase, p.camera_id)
        result.accepted.append(watch)
        per_camera[p.camera_id] = per_camera.get(p.camera_id, 0) + 1
        watched.add((p.camera_id, phrase))
    return result


def revoke(watch: Watch) -> Watch:
    """Owner taps undo (spec 5.10 Watching -> Revoked). Returns a new Watch."""
    if watch.status != "watching":
        raise ValueError(f"only a watching watch can be revoked (status {watch.status})")
    return watch.model_copy(update={"status": "revoked"})


def expire(watches: Iterable[Watch], now: datetime) -> list[Watch]:
    """Mark watching watches past their expiry as expired (spec 5.10 Watching -> Expired)."""
    out = []
    for w in watches:
        if w.status == "watching" and w.expires_at is not None and w.expires_at <= now:
            w = w.model_copy(update={"status": "expired"})
        out.append(w)
    return out
