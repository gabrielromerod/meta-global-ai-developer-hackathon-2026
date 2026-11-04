"""Recurring-visitor profiles from local face templates (spec change 2026-11-04).

Opt-in: nothing is listed unless `VIGIL_FACE_TEMPLATES` is on. Reads are LAN-only; naming,
flagging, merging and deleting are owner-only. A name lives only on the profile card: stories,
rules and roles never use it (validator check 7 still rejects names in a story).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from vigil.api.guards import require_lan
from vigil.api.owner import require_owner
from vigil.faces import DETECTOR_FILE, RECOGNIZER_FILE, FaceStore, clean_name
from vigil.faces.appearance import appearance_profiles, upper_body_crop
from vigil.faces.enroll import _VideoFrames, _window_path

FACE_ID = re.compile(r"fc_[0-9a-f]{16}")
PROFILE_ID = re.compile(r"(fp|ap)_[0-9a-z_]{1,32}")
TRACK_ID = re.compile(r"[a-z0-9_-]{1,96}")
CAPTURE_ID = re.compile(r"[a-z0-9_-]{1,128}")
NOTE = (
    "Face templates stay on this home box and are never sent to a model API. "
    "Only people inside the property are enrolled; the street is never sampled."
)


def faces_enabled() -> bool:
    return os.environ.get("VIGIL_FACE_TEMPLATES", "").strip().lower() in {"1", "true", "yes"}


def _data_dir(request: Request) -> Path:
    return Path(request.app.state.settings.data_dir)


def _store(request: Request) -> FaceStore:
    return FaceStore(_data_dir(request) / "faces.db")


def _seen(n: int) -> str:
    return "Seen once on the property" if n == 1 else f"Seen {n} times on the property"


def _view(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: profile.get(k) for k in ("id", "name", "flagged", "count", "sightings")},
        "basis": "face",
        "label": None,
        "seen_label": _seen(int(profile.get("count") or 0)),
        "crops": [f"/api/ui/faces/crops/{face_id}" for face_id in profile.get("crops") or []],
    }


def _names_path(request: Request) -> Path:
    return _data_dir(request) / "appearance" / "names.json"


def _names(request: Request) -> dict[str, str]:
    try:
        data = json.loads(_names_path(request).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _clothing(request: Request) -> list[dict[str, Any]]:
    """Clothing-signature profiles (fallback when faces are too small), as card views."""
    config = getattr(request.app.state, "config", None)
    if config is None:
        return []
    names = _names(request)
    out = []
    for p in appearance_profiles(_data_dir(request) / "results", config.cameras):
        out.append({
            "id": p["id"], "name": names.get(p["id"]), "flagged": False, "count": p["count"],
            "basis": "clothing", "label": p["label"], "seen_label": _seen(p["count"]),
            "sightings": [{"capture_id": s["capture_id"], "seen_at": s["seen_at"]}
                          for s in p["sightings"]],
            "crops": [f"/api/ui/faces/appearance/{t['capture_id']}/{t['track_id']}"
                      for t in p["thumbs"]],
        })  # fmt: skip
    return out


def _profiles(request: Request, capture_id: str | None = None) -> dict[str, Any]:
    models = _data_dir(request) / "models"
    ready = (models / DETECTOR_FILE).is_file() and (models / RECOGNIZER_FILE).is_file()
    if not faces_enabled():
        return {"enabled": False, "models_ready": ready, "profiles": [], "note": NOTE}
    path = _data_dir(request) / "faces.db"
    if not path.is_file():
        rows: list[dict[str, Any]] = []
    else:
        store = _store(request)
        rows = store.profile_for_capture(capture_id) if capture_id else store.profiles()
    views = [_view(p) for p in rows]
    clothing = [
        c
        for c in _clothing(request)
        if capture_id is None or any(s["capture_id"] == capture_id for s in c["sightings"])
    ]
    if capture_id is None or not views:
        views += clothing
    return {"enabled": True, "models_ready": ready, "profiles": views, "note": NOTE}


class _Name(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class _Flag(BaseModel):
    flagged: bool


class _Merge(BaseModel):
    drop_id: str


def _pid(profile_id: str) -> str:
    if not faces_enabled() or not PROFILE_ID.fullmatch(profile_id):
        raise HTTPException(404, "profile not found")
    return profile_id


def _crop_from_video(request: Request, thumb: dict[str, Any]) -> bytes | None:
    windows_dir = _data_dir(request) / "windows" / thumb["capture_id"]
    try:
        windows = json.loads((windows_dir / "windows.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    t = float(thumb["t"])
    window = next(
        (
            w
            for w in windows
            if isinstance(w, dict)
            and w.get("camera_id") == thumb["camera_id"]
            and float(w.get("t0", 0)) <= t <= float(w.get("t1", -1))
            and w.get("path")
        ),
        None,
    )
    if window is None:
        return None
    reader = _VideoFrames()
    try:
        frame = reader(_window_path(windows_dir, str(window["path"])), t - float(window["t0"]))
    finally:
        reader.close()
    if frame is None:
        return None
    ow, oh = thumb["overlay_size"]
    sx, sy = frame.shape[1] / ow, frame.shape[0] / oh
    x0, y0, x1, y1 = thumb["box"]
    return upper_body_crop(frame, [x0 * sx, y0 * sy, x1 * sx, y1 * sy])


def faces_router() -> APIRouter:
    r = APIRouter(prefix="/api", dependencies=[Depends(require_lan)])

    @r.get("/ui/faces")
    def list_profiles(request: Request) -> dict[str, Any]:
        return _profiles(request)

    @r.get("/ui/captures/{capture_id}/faces")
    def capture_profiles(capture_id: str, request: Request) -> dict[str, Any]:
        if not CAPTURE_ID.fullmatch(capture_id):
            raise HTTPException(404, "capture not found")
        return _profiles(request, capture_id)

    @r.get("/ui/faces/crops/{face_id}")
    def crop(face_id: str, request: Request) -> Response:
        if not faces_enabled() or not FACE_ID.fullmatch(face_id):
            raise HTTPException(404, "crop not found")
        body = _store(request).crop(face_id)
        if body is None:
            raise HTTPException(404, "crop not found")
        return Response(body, media_type="image/jpeg", headers={"cache-control": "no-store"})

    @r.get("/ui/faces/appearance/{capture_id}/{track_id}")
    def appearance_crop(capture_id: str, track_id: str, request: Request) -> Response:
        """Upper-body crop from the capture's masked parts, for a clothing profile thumbnail."""
        if (
            not faces_enabled()
            or not CAPTURE_ID.fullmatch(capture_id)
            or not TRACK_ID.fullmatch(track_id)
        ):
            raise HTTPException(404, "crop not found")
        cache = _data_dir(request) / "appearance" / "crops" / f"{capture_id}__{track_id}.jpg"
        if not cache.is_file():
            profiles = appearance_profiles(
                _data_dir(request) / "results", request.app.state.config.cameras
            )
            thumb = next(
                (
                    t
                    for p in profiles
                    for t in p["thumbs"]
                    if t["capture_id"] == capture_id and t["track_id"] == track_id
                ),
                None,
            )
            body = _crop_from_video(request, thumb) if thumb else None
            if body is None:
                raise HTTPException(404, "crop not found")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(body)
        return Response(cache.read_bytes(), media_type="image/jpeg",
                        headers={"cache-control": "no-store"})  # fmt: skip

    @r.post("/faces/{profile_id}/name", dependencies=[Depends(require_owner)])
    def rename(profile_id: str, body: _Name, request: Request) -> dict[str, Any]:
        pid = _pid(profile_id)
        if pid.startswith("ap_"):
            try:
                name = clean_name(body.name)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            names = _names(request)
            if name:
                names[pid] = name
            else:
                names.pop(pid, None)
            _names_path(request).parent.mkdir(parents=True, exist_ok=True)
            _names_path(request).write_text(json.dumps(names, indent=1), encoding="utf-8")
            return {"id": pid, "name": name}
        try:
            name = clean_name(body.name)
            _store(request).rename(pid, name)
        except KeyError as exc:
            raise HTTPException(404, "profile not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": pid, "name": name}

    @r.post("/faces/{profile_id}/flag", dependencies=[Depends(require_owner)])
    def flag(profile_id: str, body: _Flag, request: Request) -> dict[str, Any]:
        pid = _pid(profile_id)
        try:
            _store(request).flag(pid, body.flagged)
        except KeyError as exc:
            raise HTTPException(404, "profile not found") from exc
        return {"id": pid, "flagged": body.flagged}

    @r.post("/faces/{profile_id}/merge", dependencies=[Depends(require_owner)])
    def merge(profile_id: str, body: _Merge, request: Request) -> dict[str, Any]:
        pid, drop = _pid(profile_id), _pid(body.drop_id)
        try:
            _store(request).merge(pid, drop)
        except KeyError as exc:
            raise HTTPException(404, "profile not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": pid, "merged": drop}

    @r.delete("/faces/{profile_id}", dependencies=[Depends(require_owner)])
    def delete(profile_id: str, request: Request) -> dict[str, Any]:
        pid = _pid(profile_id)
        store = _store(request)
        if not any(p["id"] == pid for p in store.profiles()):
            raise HTTPException(404, "profile not found")
        store.delete_profile(pid)
        return {"id": pid, "deleted": True}

    return r
