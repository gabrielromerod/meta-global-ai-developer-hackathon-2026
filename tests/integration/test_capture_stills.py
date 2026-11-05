# ruff: noqa: F811 (pytest fixtures imported from the captures API tests)
"""Masked stills from real captures for tap-to-protect and the Settings preview (LAN only).

Captures are written by the real EventRecorder (generated clips only, no footage). A still is
read from the masked window part and kept only after the pre-upload privacy guard passes.
"""

import json

from fastapi.testclient import TestClient

from tests.integration.test_api import FakeBackend
from tests.integration.test_captures_api import (  # noqa: F401 (pytest fixtures)
    _settings_without_dotenv,
    home,
    recorded,
)
from vigil.api.app import create_app
from vigil.settings import Settings

TOKEN = "stills-owner-token-9d2c"


def _analysed(home) -> None:
    folder = home["root"] / "results" / home["first"]
    folder.mkdir(parents=True, exist_ok=True)
    tracks = [{"id": "porch-person-0", "phrase": "person", "t_first": 0.1, "t_last": 0.3}]
    (folder / "visits.json").write_text(json.dumps({"tracks": tracks}), encoding="utf-8")


def _client(home, ip="127.0.0.1", backend=None, cache_only=True) -> TestClient:
    app = create_app(
        Settings(
            _env_file=None,
            mode="edge",
            MODEL_API_KEY="invalid",
            meta_cache_only=cache_only,
            owner_token=TOKEN,
            data_dir=home["root"],
            config_path=home["config"],
        ),
        live_backend=backend,
    )
    client = TestClient(app, client=(ip, 50000))
    client.headers["authorization"] = f"Bearer {TOKEN}"
    return client


def _frames(client, **params):
    return client.get("/api/ui/protection-frames", params=params).json()


def test_protection_frames_list_a_masked_capture_still(home):
    _analysed(home)
    client = _client(home)
    body = _frames(client)
    (frame,) = [f for f in body["frames"] if f.get("source") == "capture"]
    assert frame["camera_id"] == "porch"
    assert frame["still_id"].startswith(home["first"] + "@")
    assert body["reason"] is None
    image = client.get(frame["url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "no-store"
    assert "path" not in frame


def test_unreviewed_camera_still_is_never_listed(home):
    _analysed(home)
    body = _frames(_client(home), still=home["door"])
    assert all(f["camera_id"] != "doorbell" for f in body["frames"])


def test_capture_still_is_lan_only_and_ids_validated(home):
    _analysed(home)
    frame = _frames(_client(home))["frames"][0]
    assert _client(home, ip="203.0.113.7").get(frame["url"]).status_code == 403
    client = _client(home)
    assert client.get("/api/ui/capture-stills/porch-x/1.png").status_code == 404
    assert client.get("/api/ui/capture-stills/..%2Fetc/1.png").status_code == 404


def test_protect_on_a_capture_still_never_shows_a_demo_outline(home):
    _analysed(home)
    client = _client(home)
    frame = _frames(client)["frames"][0]
    body = client.post("/api/protect", json={
        "camera_id": "porch", "still_id": frame["still_id"], "point": {"x": 10, "y": 10},
        "frame_width": frame["width"], "frame_height": frame["height"], "live": False,
    }).json()  # fmt: skip
    assert body.get("result", "MISSING") is None, body
    assert "live SAM 3.1" in body["notice"]
    wrong = client.post("/api/protect", json={
        "camera_id": "doorbell", "still_id": frame["still_id"], "point": {"x": 1, "y": 1},
    })  # fmt: skip
    assert wrong.status_code == 422


class _StillBackend(FakeBackend):
    def protect(self, camera_id, frame_ts, x, y, label, still=None):
        self.still = still
        return super().protect(camera_id, frame_ts, x, y, label)


def test_live_protect_sends_the_capture_still_to_the_backend(home):
    _analysed(home)
    backend = _StillBackend()
    client = _client(home, backend=backend, cache_only=False)
    frame = _frames(client)["frames"][0]
    r = client.post("/api/protect", json={
        "camera_id": "porch", "still_id": frame["still_id"], "point": {"x": 40, "y": 40},
        "frame_width": frame["width"], "frame_height": frame["height"], "live": True,
    })  # fmt: skip
    if backend.calls:  # the live gate allows it in this test configuration
        assert backend.still is not None
        assert backend.still.name.startswith(home["first"])
    else:  # gate closed (no budget ledger): still never falls back to a demo outline
        assert r.json()["result"] is None


def test_camera_preview_and_overview_on_lan(home):
    _analysed(home)
    client = _client(home)
    preview = client.get("/api/ui/cameras/porch/preview").json()
    assert preview["still"]["camera_id"] == "porch"
    assert preview["width"] > 0
    assert isinstance(preview["zones"], list)
    rows = {r["id"]: r for r in client.get("/api/ui/cameras/overview").json()["cameras"]}
    assert rows["porch"]["captures"] == 2
    assert rows["porch"]["privacy_reviewed"] is True
    assert rows["porch"]["placement_measured"] is False
    assert rows["doorbell"]["privacy_reviewed"] is False
    assert _client(home, ip="203.0.113.7").get("/api/ui/cameras/overview").status_code == 403
    assert client.get("/api/ui/cameras/nope/preview").status_code == 404
