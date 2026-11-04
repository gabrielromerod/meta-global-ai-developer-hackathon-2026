"""One moment seen by several cameras, as one session on one clock (FR-010, FR-031).

`run_event_capture` writes one folder per camera alert, each a single-camera session with
its own `session_start`. A visit that crosses cameras (a car parks on the driveway camera,
the person walks up past the walkway camera) can only be linked by `assign_visits` when
the windows of both cameras share one timeline. `merge_captures` writes that session under
`data/windows/moment-<hash>/`: the earliest `session_start`, every window, AI event,
truncation and capture gap shifted onto it, and the media paths left pointing at the
original (already masked) parts. Nothing is re-encoded and nothing leaves the machine.

A moment folder has no `capture.json`, so the captures list never shows it as a clip.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

PERSON_KINDS = frozenset({"person", "doorbell_press"})
MOMENT_GAP_S = 60.0
"""Person alerts on different cameras this close together belong to one moment."""


def moment_name(capture_ids: Iterable[str]) -> str:
    """Stable session name for a set of captures (order does not matter)."""
    digest = hashlib.sha256("|".join(sorted(capture_ids)).encode()).hexdigest()[:16]
    return f"moment-{digest}"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _shift(row: Mapping[str, Any], dt: float, keys: Sequence[str] = ("t0", "t1")) -> dict:
    out = dict(row)
    for k in keys:
        if isinstance(out.get(k), int | float) and not isinstance(out.get(k), bool):
            out[k] = round(float(out[k]) + dt, 6)
    return out


def merge_captures(folders: Sequence[Path], windows_root: Path) -> Path:
    """Write one session for several capture folders; return its folder.

    Raises ValueError when two captures share a window id (the same camera recorded twice
    with overlapping ids) or a capture lacks its session files.
    """
    if not folders:
        raise ValueError("no captures to merge")
    loaded = []
    for folder in folders:
        folder = Path(folder)
        session, windows = folder / "session.json", folder / "windows.json"
        if not session.is_file() or not windows.is_file():
            raise ValueError(f"{folder.name}: missing session.json or windows.json")
        meta = _read(session)
        loaded.append((folder, meta, _read(windows), datetime.fromisoformat(meta["session_start"])))
    start = min(s for *_, s in loaded)

    windows: list[dict] = []
    events: list[dict] = []
    gaps: list[dict] = []
    truncated: dict[str, float] = {}
    seen: set[str] = set()
    for _folder, meta, rows, s in loaded:
        dt = (s - start).total_seconds()
        for w in rows:
            if w["id"] in seen:
                raise ValueError(f"window id {w['id']} appears in two captures")
            seen.add(w["id"])
            windows.append(_shift(w, dt))
        events += [_shift(e, dt) for e in meta.get("camera_ai_events") or []]
        gaps += [_shift(g, dt) for g in meta.get("capture_gaps") or []]
        for cam, t in (meta.get("truncated_after") or {}).items():
            shifted = round(float(t) + dt, 6)
            truncated[cam] = min(truncated.get(cam, shifted), shifted)

    names = sorted(f.name for f, *_ in loaded)
    out = Path(windows_root) / moment_name(names)
    out.mkdir(parents=True, exist_ok=True)
    windows.sort(key=lambda w: (w["t0"], w["camera_id"], w["id"]))
    events.sort(key=lambda e: (e["t0"], e["camera_id"], e["id"]))
    first = loaded[0][1]
    session = {
        "session_start": start.isoformat(),
        "camera_ai_events": events,
        "camera_ai_events_measured": all(m.get("camera_ai_events_measured") for _, m, *_ in loaded),
        "source_label": first.get("source_label", "Event clips"),
        "truncated_after": truncated,
        "capture_gaps": gaps,
        "illumination_basis": first.get("illumination_basis"),
        "merged_from": names,
    }
    (out / "windows.json").write_text(json.dumps(windows, indent=1), encoding="utf-8")
    (out / "session.json").write_text(json.dumps(session, indent=1), encoding="utf-8")
    return out


def group_moments(
    rows: Sequence[Mapping[str, Any]], gap_s: float = MOMENT_GAP_S
) -> list[list[str]]:
    """Capture ids per multi-camera moment, from `/api/ui/captures` rows.

    Person (and doorbell) alerts chain while each starts within ``gap_s`` of the previous
    one's end; vehicle alerts join a moment they overlap. Moments seen by only one camera
    are left out: they are already one session.
    """

    def t(row: Mapping[str, Any], key: str) -> float:
        value = row.get(key) or row["started_at"]
        return datetime.fromisoformat(str(value)).timestamp()

    people = sorted(
        (r for r in rows if r.get("kind") in PERSON_KINDS), key=lambda r: t(r, "started_at")
    )
    clusters: list[list[Mapping[str, Any]]] = []
    for r in people:
        if clusters and t(r, "started_at") - max(t(x, "ended_at") for x in clusters[-1]) <= gap_s:
            clusters[-1].append(r)
        else:
            clusters.append([r])
    out = []
    for cluster in clusters:
        lo = min(t(x, "started_at") for x in cluster) - gap_s
        hi = max(t(x, "ended_at") for x in cluster)
        cars = [r for r in rows if r.get("kind") == "vehicle"
                and t(r, "ended_at") >= lo and t(r, "started_at") <= hi]  # fmt: skip
        members = cluster + cars
        if len({m["camera_id"] for m in members}) < 2:
            continue
        out.append([m["id"] for m in sorted(members, key=lambda m: (t(m, "started_at"), m["id"]))])
    return out
