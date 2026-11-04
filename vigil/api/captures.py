"""LAN-only list of recorded event clips, before any analysis (FR-031/032, spec 9.6).

Reads the folders `EventRecorder.finish` writes under `data/windows/<camera>-<key>-<attempt>/`
(`capture.json`, `session.json`, `part-NNN.mp4`). Rows are the camera's own AI event layer
(`camera_ai`): presence and timing only, never a story. Responses carry no host, credential
or filesystem path.

Owner decision (Nov 3): on the LAN the owner sees clips unmasked. Masking stays where frames
leave the machine (Meta uploads, exports). The clip route serves the raw main-stream clip
that `run_event_capture` keeps pinned in `data/capture/ring/event-<key>-NNN.mp4` when it is
provably this capture's source, else the masked part; each row says which (`masked`).

Recording a public demo: `VIGIL_MASKED_VIEW=1` serves only the masked parts (street, far side
and neighbours black), never the raw ring clip.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from vigil.api.guards import require_lan
from vigil.models import CameraCfg, Config

CAPTURE_ID = re.compile(r"[a-z0-9_]{1,64}-[0-9a-f]{20}-[0-9a-f]{12}")
"""Folder name written by `EventRecorder.finish`: camera id, event key, attempt key."""
PART = re.compile(r"part-\d{3}\.mp4")
RAW_MAIN = re.compile(r"event-[0-9a-f]{20}-\d{3}\.mp4")
WINDOW_ID = re.compile(r"[a-z0-9_]{1,64}")
"""Window id of a tag-burned clip in `data/results/<capture>/tagged/<window id>.mp4`."""
TRACK_NOTE_FIELDS = ("upper_color", "lower_color", "vehicle_color", "vehicle_body", "carrying")


def _windows_root(request: Request) -> Path:
    return (Path(request.app.state.settings.data_dir) / "windows").resolve()


def _capture_dir(root: Path, capture_id: str) -> Path | None:
    """The capture folder for a strictly shaped id, never a link or a path outside root."""
    if not CAPTURE_ID.fullmatch(capture_id):
        return None
    folder = root / capture_id
    if folder.is_symlink() or not folder.is_dir():
        return None
    if folder.resolve().parent != root or not (folder / "capture.json").is_file():
        return None
    return folder


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _camera(request: Request, camera_id: str) -> CameraCfg | None:
    config: Config | None = request.app.state.config
    if config is None:
        return None
    try:
        return config.camera(camera_id)
    except KeyError:
        return None


def _main_part(folder: Path, capture: dict) -> Path | None:
    """The main-stream part, else the longest part; only `part-NNN.mp4` inside the folder."""
    best: tuple[int, float, str] | None = None
    for part in capture.get("parts") or []:
        if not isinstance(part, dict):
            continue
        name = Path(str(part.get("path", ""))).name
        if not PART.fullmatch(name) or not (folder / name).is_file():
            continue
        try:
            length = float(part["t1"]) - float(part["t0"])
        except (KeyError, TypeError, ValueError):
            length = 0.0
        rank = (int(part.get("source_quality") == "main"), length, name)
        best = rank if best is None or rank > best else best
    if best is not None:
        return folder / best[2]
    parts = sorted(p for p in folder.glob("part-*.mp4") if PART.fullmatch(p.name))
    return parts[-1] if parts else None


def _raw_main(request: Request, folder: Path, capture: dict) -> Path | None:
    """The unmasked ring clip this capture was cut from, proven by the folder's attempt key.

    `EventRecorder.finish` names the folder `<camera>-<sha256(event id)[:20]>-<attempt>`
    with `attempt = sha256(f"{main_start}|{main.name}")[:12]`; the main part's `t0` is
    `main_start`. A ring file with the same event key but another attempt is not served.
    """
    _, key, attempt = folder.name.rsplit("-", 2)
    starts: set[str] = set()
    for part in capture.get("parts") or []:
        if isinstance(part, dict) and part.get("source_quality") == "main":
            value = part.get("t0")
            if isinstance(value, int | float) and not isinstance(value, bool):
                starts |= {str(value), str(float(value))}
                if float(value).is_integer():
                    starts.add(str(int(value)))
    if not starts:
        return None
    ring = (Path(request.app.state.settings.data_dir) / "capture" / "ring").resolve()
    if not ring.is_dir():
        return None
    for candidate in sorted(ring.glob(f"event-{key}-*.mp4")):
        if (
            not RAW_MAIN.fullmatch(candidate.name)
            or candidate.is_symlink()
            or not candidate.is_file()
            or candidate.resolve().parent != ring
        ):
            continue
        for start in starts:
            digest = hashlib.sha256(f"{start}|{candidate.name}".encode()).hexdigest()[:12]
            if digest == attempt:
                return candidate
    return None


def masked_view() -> bool:
    """True while recording for an audience: only masked media leaves the clip route."""
    return os.environ.get("VIGIL_MASKED_VIEW", "").strip().lower() in {"1", "true", "yes"}


def _clip(request: Request, folder: Path, capture: dict) -> tuple[Path | None, bool | None]:
    """(clip, masked): the raw main clip when kept, else the masked main part."""
    raw = None if masked_view() else _raw_main(request, folder, capture)
    if raw is not None:
        return raw, False
    part = _main_part(folder, capture)
    if part is None or part.is_symlink() or part.resolve().parent != folder.resolve():
        return None, None
    return part, True


def _row(request: Request, folder: Path) -> dict[str, Any] | None:
    capture, session = _read_json(folder / "capture.json"), _read_json(folder / "session.json")
    if not isinstance(capture, dict) or not isinstance(session, dict):
        return None
    events = session.get("camera_ai_events") or []
    event = events[0] if events and isinstance(events[0], dict) else None
    try:
        start = datetime.fromisoformat(str(session["session_start"]))
        t0 = float(event["t0"])  # type: ignore[index]
        t1 = None if event.get("t1") is None else float(event["t1"])  # type: ignore[union-attr]
    except (KeyError, TypeError, ValueError):
        return None
    if start.tzinfo is None:
        return None
    start = start.astimezone(UTC)
    camera_id = str(capture.get("camera_id") or event.get("camera_id") or "")
    camera = _camera(request, camera_id)
    clip, masked = _clip(request, folder, capture)
    results = Path(request.app.state.settings.data_dir) / "results" / folder.name
    return {
        "id": folder.name,
        "camera_id": camera_id,
        "camera_name": camera.name if camera else None,
        "kind": event.get("kind"),
        "started_at": (start + timedelta(seconds=t0)).isoformat(),
        "ended_at": None if t1 is None else (start + timedelta(seconds=t1)).isoformat(),
        "partial": bool(capture.get("partial")),
        "clip_url": f"/api/ui/captures/{folder.name}/clip" if clip is not None else None,
        "masked": masked,
        "analysis": "analysed" if results.is_dir() else "not_analysed",
        "layer": "camera_ai",
    }


def _results_dir(request: Request, capture_id: str) -> Path | None:
    """`data/results/<capture id>` for a recorded capture, never a link or outside path."""
    if _capture_dir(_windows_root(request), capture_id) is None:
        return None
    root = (Path(request.app.state.settings.data_dir) / "results").resolve()
    folder = root / capture_id
    if folder.is_symlink() or not folder.is_dir() or folder.resolve().parent != root:
        return None
    return folder


def _clip_window(capture_folder: Path) -> tuple[float, float] | None:
    """(start, duration) of the served camera clip, in seconds of the session timeline.

    The LAN clip is the main part (raw or masked), so story times are shifted by the main
    part's start to land on the right frame of the video the owner is watching.
    """
    capture = _read_json(capture_folder / "capture.json")
    session = _read_json(capture_folder / "session.json")
    if not isinstance(capture, dict) or not isinstance(session, dict):
        return None
    part = _main_part(capture_folder, capture)
    meta = next(
        (
            x
            for x in capture.get("parts") or []
            if isinstance(x, dict)
            and part is not None
            and Path(str(x.get("path"))).name == part.name
        ),
        None,
    )
    try:
        start = datetime.fromisoformat(str(session["session_start"])).timestamp()
        return float(meta["t0"]) - start, float(meta["t1"]) - float(meta["t0"])  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        return None


def _seconds(value: Any, start: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(max(0.0, float(value) - start), 2)


def _analysis(capture_id: str, folder: Path, capture_folder: Path) -> dict[str, Any] | None:
    """What Vigil made of a capture: verdict, cited story, roles and SAM tags with notes.

    Only fields the UI needs; appearance notes are the FR-009 allowlist (clothing and
    vehicle colours, carried items), so nothing here can identify a person (NFR-003).
    """
    data = _read_json(folder / "visits.json")
    if not isinstance(data, dict):
        return None
    visits = [v for v in data.get("visits") or [] if isinstance(v, dict)]
    visit = visits[0] if visits else {}
    notes = data.get("appearance") or {}
    clip = _clip_window(capture_folder)
    start = clip[0] if clip else 0.0
    track_rows = {t.get("id"): t for t in data.get("tracks") or [] if isinstance(t, dict)}
    events = {e.get("id"): e for e in data.get("events") or [] if isinstance(e, dict)}
    windows = {w.get("id"): w for w in data.get("windows") or [] if isinstance(w, dict)}

    def kind(track_id: Any) -> str | None:
        phrase = (track_rows.get(track_id) or {}).get("phrase")
        return {"car": "vehicle", "person": "person"}.get(str(phrase), phrase)

    def moment(event_ids: list) -> tuple[float | None, str | None]:
        cited = [events[e] for e in event_ids if e in events]
        if not cited or clip is None:
            return None, None
        first = min(cited, key=lambda e: e.get("t0") or 0)
        return _seconds(first.get("t0"), start), kind(first.get("track_id"))

    tracks = []
    for track in data.get("tracks") or []:
        if not isinstance(track, dict) or not track.get("tag"):
            continue
        note = notes.get(track.get("id")) or {}
        tracks.append(
            {
                "tag": track["tag"],
                "phrase": track.get("phrase"),
                "class": note.get("class"),
                **{k: note.get(k) for k in TRACK_NOTE_FIELDS},
                "from": _seconds(track.get("t_first"), start) if clip else None,
                "to": _seconds(track.get("t_last"), start) if clip else None,
            }
        )
    tagged = sorted(
        p.stem
        for p in (folder / "tagged").glob("*.mp4")
        if WINDOW_ID.fullmatch(p.stem) and not p.is_symlink()
    )
    return {
        "id": capture_id,
        "verdict": visit.get("verdict"),
        "story_source": visit.get("story_source"),
        "clip": {"duration": round(clip[1], 2)} if clip else None,
        "story": [
            {
                "text": s.get("text"),
                "source": s.get("source"),
                "event_ids": s.get("event_ids") or [],
                "gap_id": s.get("gap_id"),
                "at": moment(s.get("event_ids") or [])[0],
                "kind": moment(s.get("event_ids") or [])[1],
            }
            for s in visit.get("story") or []
            if isinstance(s, dict)
        ],
        "subjects": [
            {
                **{k: s.get(k) for k in ("id", "actor_role", "role_basis")},
                "kind": kind((s.get("track_ids") or [None])[0]),
            }
            for s in visit.get("subjects") or []
            if isinstance(s, dict)
        ],
        "gaps": [
            {k: g.get(k) for k in ("id", "kind", "resolved")}
            for g in visit.get("gaps") or []
            if isinstance(g, dict)
        ],
        "visits": len(visits),
        "tracks": tracks,
        "tagged": [
            {
                "window_id": w,
                "url": f"/api/ui/captures/{capture_id}/tagged/{w}",
                "offset": _seconds((windows.get(w) or {}).get("t0"), start) if clip else None,
            }
            for w in tagged
        ],
    }


MOMENT_ID = re.compile(r"moment-[0-9a-f]{16}")


def _moment(request: Request, capture_id: str) -> dict[str, Any] | None:
    """The merged multi-camera moment this clip belongs to, with its combined story."""
    windows = _windows_root(request)
    results = (Path(request.app.state.settings.data_dir) / "results").resolve()
    if not windows.is_dir():
        return None
    for folder in sorted(windows.glob("moment-*")):
        if not MOMENT_ID.fullmatch(folder.name) or folder.is_symlink():
            continue
        session = _read_json(folder / "session.json")
        merged = session.get("merged_from") if isinstance(session, dict) else None
        if not isinstance(merged, list) or capture_id not in merged:
            continue
        data = _read_json(results / folder.name / "visits.json")
        if not isinstance(data, dict):
            continue
        visits = [v for v in data.get("visits") or [] if isinstance(v, dict)]
        visit = visits[0] if visits else {}
        cameras = sorted({str(t.get("camera_id")) for t in data.get("tracks") or []
                          if isinstance(t, dict) and t.get("camera_id")})  # fmt: skip
        return {
            "id": folder.name,
            "clips": [str(c) for c in merged],
            "cameras": cameras,
            "verdict": visit.get("verdict"),
            "story": [str(s.get("text")) for s in visit.get("story") or []
                      if isinstance(s, dict) and s.get("text")],
        }  # fmt: skip
    return None


def captures_router() -> APIRouter:
    r = APIRouter(prefix="/api", dependencies=[Depends(require_lan)])

    @r.get("/ui/captures")
    def list_captures(request: Request) -> dict[str, list[dict[str, Any]]]:
        root = _windows_root(request)
        rows = []
        if root.is_dir():
            for child in root.iterdir():
                folder = _capture_dir(root, child.name)
                row = _row(request, folder) if folder is not None else None
                if row is not None:
                    rows.append(row)
        rows.sort(
            key=lambda row: (datetime.fromisoformat(row["started_at"]), row["id"]), reverse=True
        )
        return {"captures": rows}

    @r.get("/ui/captures/{capture_id}/clip")
    def capture_clip(capture_id: str, request: Request) -> FileResponse:
        root = _windows_root(request)
        folder = _capture_dir(root, capture_id)
        capture = _read_json(folder / "capture.json") if folder is not None else None
        if folder is None or not isinstance(capture, dict):
            raise HTTPException(404, "capture not found")
        clip, _ = _clip(request, folder, capture)
        if clip is None:
            raise HTTPException(404, "capture has no clip")
        return FileResponse(clip, media_type="video/mp4")

    @r.get("/ui/captures/{capture_id}/analysis")
    def capture_analysis(capture_id: str, request: Request) -> dict[str, Any]:
        folder = _results_dir(request, capture_id)
        capture_folder = _capture_dir(_windows_root(request), capture_id)
        body = (
            _analysis(capture_id, folder, capture_folder)
            if folder is not None and capture_folder is not None
            else None
        )
        if body is None:
            raise HTTPException(404, "capture not analysed")
        body["moment"] = _moment(request, capture_id)
        return body

    @r.get("/ui/captures/{capture_id}/tagged/{window_id}")
    def capture_tagged(capture_id: str, window_id: str, request: Request) -> FileResponse:
        """The masked clip with SAM's tags burned in: what Spark was shown (FR-009)."""
        folder = _results_dir(request, capture_id)
        if folder is None or not WINDOW_ID.fullmatch(window_id):
            raise HTTPException(404, "tagged clip not found")
        clip = folder / "tagged" / f"{window_id}.mp4"
        if (
            clip.is_symlink()
            or not clip.is_file()
            or clip.resolve().parent != (folder / "tagged").resolve()
        ):
            raise HTTPException(404, "tagged clip not found")
        return FileResponse(clip, media_type="video/mp4")

    return r
