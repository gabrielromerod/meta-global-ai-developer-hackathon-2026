"""Face profiles over the LAN API (spec change 2026-11-04, face templates).

Opt-in with VIGIL_FACE_TEMPLATES; reads are LAN-only, every change is owner-only.
Synthetic embeddings and crop bytes; no images of people.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_api import FakeClock, as_owner, build, owner_settings
from vigil.faces import FaceBox, FaceStore, TrackFace


def _face(seed: int) -> TrackFace:
    v = np.zeros(128, np.float32)
    v[seed] = 1.0
    box = FaceBox(box=(0, 0, 40, 40), landmarks=((1.0, 1.0),) * 5, score=0.9)
    return TrackFace(1.0, box, v, b"\xff\xd8crop\xff\xd9")


def _client(tmp_path, monkeypatch, enabled=True):
    if enabled:
        monkeypatch.setenv("VIGIL_FACE_TEMPLATES", "1")
    else:
        monkeypatch.delenv("VIGIL_FACE_TEMPLATES", raising=False)
    store = FaceStore(tmp_path / "data" / "faces.db")
    for n, capture in enumerate(("cap-a", "cap-b", "cap-c", "cap-d")):
        store.add_track_faces(capture, "t1", f"2026-11-0{n + 1}T17:00:00+00:00", [_face(0)])
    store.add_track_faces("cap-d", "t2", "2026-11-04T17:01:00+00:00", [_face(5)])
    settings = owner_settings(tmp_path, data_dir=tmp_path / "data")
    _, client = build(settings, clock=FakeClock(), ip="192.168.1.20")
    return client, store


def test_faces_off_by_default_lists_nothing(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, enabled=False)
    body = client.get("/api/ui/faces").json()
    assert body["enabled"] is False
    assert body["profiles"] == []


def test_recurring_visitor_profile_counts_sightings(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/api/ui/captures/cap-d/faces").json()
    counts = sorted(p["count"] for p in body["profiles"])
    assert counts == [1, 4]
    recurring = next(p for p in body["profiles"] if p["count"] == 4)
    assert recurring["seen_label"] == "Seen 4 times on the property"
    assert recurring["sightings"][0]["capture_id"] == "cap-d"
    crop = client.get(recurring["crops"][0])
    assert crop.status_code == 200
    assert crop.headers["content-type"] == "image/jpeg"


def test_faces_are_lan_only(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    outside = TestClient(client.app, client=("203.0.113.7", 50000))
    assert outside.get("/api/ui/faces").status_code in {403, 404}


def test_owner_names_flags_merges_and_deletes(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)
    profiles = {p["count"]: p["id"] for p in client.get("/api/ui/faces").json()["profiles"]}
    four, one = profiles[4], profiles[1]
    assert client.post(f"/api/faces/{four}/name", json={"name": "Brother"}).status_code in {
        401,
        403,
    }
    owner = as_owner(client)
    assert owner.post(f"/api/faces/{four}/name", json={"name": "Brother"}).status_code == 200
    assert owner.post(f"/api/faces/{four}/flag", json={"flagged": True}).status_code == 200
    named = next(p for p in store.profiles() if p["id"] == four)
    assert (named["name"], named["flagged"]) == ("Brother", True)
    assert owner.post(f"/api/faces/{four}/name", json={"name": "\x00bad"}).status_code == 422
    assert owner.post(f"/api/faces/{four}/merge", json={"drop_id": one}).status_code == 200
    assert [p["count"] for p in store.profiles()] == [4]
    assert owner.delete(f"/api/faces/{four}").status_code == 200
    assert store.profiles() == []
    assert owner.delete("/api/faces/fp_missing").status_code == 404


@pytest.mark.parametrize("path", ["/api/ui/faces/crops/../../etc", "/api/ui/faces/crops/nope"])
def test_crop_rejects_unknown_ids(tmp_path, monkeypatch, path):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.get(path).status_code == 404


def test_owner_can_flag_a_clothing_profile(tmp_path, monkeypatch):
    import json

    import vigil.api.faces as faces_api

    client, _ = _client(tmp_path, monkeypatch)
    profile = {"id": "ap_0123456789", "basis": "clothing", "label": "white top, black bottoms",
               "count": 2, "sightings": [], "thumbs": []}  # fmt: skip
    monkeypatch.setattr(faces_api, "appearance_profiles", lambda *_a, **_k: [profile])
    client.app.state.config = client.app.state.config or type("C", (), {"cameras": []})()
    assert client.post("/api/faces/ap_0123456789/flag", json={"flagged": True}).status_code in {
        401,
        403,
    }
    owner = as_owner(client)
    assert owner.post("/api/faces/ap_0123456789/flag", json={"flagged": True}).status_code == 200
    flags = json.loads((tmp_path / "data" / "appearance" / "flags.json").read_text())
    assert flags == {"ap_0123456789": True}
    listed = next(p for p in client.get("/api/ui/faces").json()["profiles"]
                  if p["id"] == "ap_0123456789")  # fmt: skip
    assert listed["flagged"] is True
    assert owner.post("/api/faces/ap_0123456789/flag", json={"flagged": False}).status_code == 200
    assert json.loads((tmp_path / "data" / "appearance" / "flags.json").read_text()) == {}
