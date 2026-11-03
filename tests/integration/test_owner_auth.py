"""Owner (LAN) endpoints need the owner token and a same-origin request (F2, FR-029, FR-044).

Reproduces the cross-site attack on the home server: a page on another origin fires a
`no-cors` POST at /api/checkin (a CORS simple request: no body, no custom header), posts a
window as text/plain, or rebinds its DNS name to the LAN address (Host: evil.example). Each
must be refused and leave no check-in or window behind. Windows are set before they start
and carry the time they were set (F11).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_api import (
    FakeBackend,
    FakeClock,
    build,
    client_for,
    make_settings,
)
from vigil.api.backend import LiveResult

OWNER_TOKEN = "owner-test-token-3b9d1c"
AUTH = {"authorization": f"Bearer {OWNER_TOKEN}"}
CROSS_SITE = {
    "origin": "http://evil.example",
    "sec-fetch-site": "cross-site",
    "sec-fetch-mode": "no-cors",
}


def _iso(clock: FakeClock, offset_s: float) -> str:
    t = datetime.fromtimestamp(clock.t + offset_s, tz=UTC)
    return t.astimezone(ZoneInfo("America/Los_Angeles")).isoformat()


def _owner(tmp_path, token: str | None = OWNER_TOKEN, clock: FakeClock | None = None, **kw: Any):
    settings = make_settings(mode="edge", db_path=tmp_path / "edge.db", owner_token=token, **kw)
    return build(settings, clock=clock or FakeClock(), ip="192.168.1.20")


def _window(clock: FakeClock) -> dict[str, Any]:
    return {"start": _iso(clock, 600), "end": _iso(clock, 3600), "cameras": ["front"],
            "label": "plumber"}  # fmt: skip


def _db_count(tmp_path, table: str) -> int:
    path = tmp_path / "edge.db"
    if not path.exists():
        return 0
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def test_owner_window_accepts_current_inventory_with_an_older_demo_bundle(tmp_path):
    clock = FakeClock()
    app, lan = _owner(
        tmp_path,
        clock=clock,
        config_path=Path(__file__).resolve().parents[2] / "config/cameras.yaml",
    )
    ids = [camera.id for camera in app.state.config.cameras]
    assert len(ids) == 7
    response = lan.post("/api/windows", headers=AUTH, json={**_window(clock), "cameras": ids})
    assert response.status_code == 200
    assert response.json()["window"]["cameras"] == ids
    refused = lan.post(
        "/api/windows", headers=AUTH, json={**_window(clock), "cameras": ["unknown-camera"]}
    )
    assert refused.status_code == 422


# --- the attack from the finding --------------------------------------------------------------


def test_checkin_no_cors_post_without_token_is_refused(tmp_path) -> None:
    app, lan = _owner(tmp_path)
    r = lan.post("/api/checkin", headers={**CROSS_SITE, "content-type": "text/plain"})
    assert r.status_code in (401, 403)
    r = lan.post("/api/checkin")  # no Origin at all, still no token
    assert r.status_code == 401
    assert app.state.runtime.checkins == {}
    assert _db_count(tmp_path, "checkins") == 0


def test_checkin_cross_site_is_refused_even_with_the_token(tmp_path) -> None:
    app, lan = _owner(tmp_path)
    assert lan.post("/api/checkin", headers={**AUTH, **CROSS_SITE}).status_code == 403
    evil = {**AUTH, "origin": "http://evil.example"}
    assert lan.post("/api/checkin", headers=evil).status_code == 403
    assert lan.post("/api/checkin", headers={**AUTH, "origin": "null"}).status_code == 403
    assert app.state.runtime.checkins == {}


def test_checkin_with_token_from_the_same_origin_works(tmp_path) -> None:
    app, lan = _owner(tmp_path)
    same = {**AUTH, "origin": "http://testserver", "sec-fetch-site": "same-origin"}
    assert lan.post("/api/checkin", headers=same).status_code == 200
    typed = {"x-vigil-owner": OWNER_TOKEN, "sec-fetch-site": "none"}
    assert lan.post("/api/checkin", headers=typed).status_code == 200
    assert len(app.state.runtime.checkins) == 2
    assert _db_count(tmp_path, "checkins") == 2


def test_wrong_token_is_401_and_never_echoed(tmp_path) -> None:
    app, lan = _owner(tmp_path)
    for headers in ({"authorization": "Bearer nope"}, {"x-vigil-owner": "nope"},
                    {"authorization": OWNER_TOKEN}):  # fmt: skip
        r = lan.post("/api/checkin", headers=headers)
        assert r.status_code == 401
        assert OWNER_TOKEN not in r.text
        assert "nope" not in r.text
    assert app.state.runtime.checkins == {}


def test_owner_endpoints_disabled_without_a_configured_token(tmp_path) -> None:
    clock = FakeClock()
    _, lan = _owner(tmp_path, token=None, clock=clock)
    r = lan.post("/api/checkin", headers=AUTH)
    assert r.status_code == 403
    assert "owner endpoints disabled" in r.json()["detail"]
    assert lan.post("/api/windows", json=_window(clock), headers=AUTH).status_code == 403
    assert lan.delete("/api/windows/w_x", headers=AUTH).status_code == 403
    pair = {"camera_id": "side_left", "pixel": [640, 500], "world": [6.0, 0.0, 3.0]}
    assert lan.post("/api/spatial/pairs", json=pair, headers=AUTH).status_code == 403
    landmarks = {"camera_id": "side_left"}
    assert lan.post("/api/spatial/landmarks", json=landmarks, headers=AUTH).status_code == 403


def test_owner_routes_stay_lan_only_with_the_token(tmp_path) -> None:
    settings = make_settings(mode="edge", db_path=tmp_path / "edge.db", owner_token=OWNER_TOKEN)
    _, public = build(settings, ip="203.0.113.9")
    assert public.post("/api/checkin", headers=AUTH).status_code == 403
    _, sandbox = build(make_settings(mode="sandbox", owner_token=OWNER_TOKEN), ip="192.168.1.20")
    assert sandbox.post("/api/checkin", headers=AUTH).status_code == 403


def test_windows_text_plain_post_is_rejected(tmp_path) -> None:
    clock = FakeClock()
    app, lan = _owner(tmp_path, clock=clock)

    body = json.dumps(_window(clock))
    plain = {"content-type": "text/plain"}
    assert lan.post("/api/windows", content=body, headers={**plain, **CROSS_SITE}).status_code in (
        401,
        403,
    )
    r = lan.post("/api/windows", content=body, headers={**plain, **AUTH})
    assert r.status_code == 415
    r = lan.post("/api/windows", content=body, headers=AUTH)  # no content type at all
    assert r.status_code == 415
    assert app.state.runtime.windows == {}
    assert _db_count(tmp_path, "expected_windows") == 0


def test_windows_post_and_delete_need_the_token(tmp_path) -> None:
    clock = FakeClock()
    app, lan = _owner(tmp_path, clock=clock)
    assert lan.post("/api/windows", json=_window(clock)).status_code == 401
    r = lan.post("/api/windows", json=_window(clock), headers=AUTH)
    assert r.status_code == 200, r.text
    wid = r.json()["window"]["id"]
    assert lan.delete(f"/api/windows/{wid}").status_code == 401
    assert app.state.runtime.windows[wid].state == "scheduled"
    assert lan.delete(f"/api/windows/{wid}", headers=AUTH).status_code == 200


def test_get_windows_shows_owner_windows_only_to_the_owner(tmp_path) -> None:
    clock = FakeClock()
    _, lan = _owner(tmp_path, clock=clock)
    wid = lan.post("/api/windows", json=_window(clock), headers=AUTH).json()["window"]["id"]
    anonymous = [w["id"] for w in lan.get("/api/windows").json()["windows"]]
    assert wid not in anonymous
    assert all(w["recorded"] for w in lan.get("/api/windows").json()["windows"])
    owner = [w["id"] for w in lan.get("/api/windows", headers=AUTH).json()["windows"]]
    assert wid in owner
    cross = lan.get("/api/windows", headers={**AUTH, **CROSS_SITE}).json()["windows"]
    assert wid not in [w["id"] for w in cross]


def test_spatial_routes_need_the_token(tmp_path) -> None:
    _, lan = _owner(tmp_path)
    pair = {"camera_id": "side_left", "pixel": [640, 500], "world": [6.0, 0.0, 3.0]}
    assert lan.post("/api/spatial/pairs", json=pair).status_code == 401
    assert lan.post("/api/spatial/pairs", json=pair, headers=AUTH).status_code == 200
    landmarks = {"camera_id": "side_left"}
    assert lan.post("/api/spatial/landmarks", json=landmarks).status_code == 401
    assert lan.post("/api/spatial/landmarks", json=landmarks, headers=AUTH).status_code == 200
    plain = {**AUTH, "content-type": "text/plain"}

    assert lan.post("/api/spatial/pairs", content=json.dumps(pair), headers=plain).status_code == (
        415
    )


# --- DNS rebinding: the Host header is checked ----------------------------------------------


def test_host_header_dns_rebinding_is_rejected(tmp_path) -> None:
    app, lan = _owner(tmp_path)
    evil = {"host": "evil.example"}
    assert lan.get("/api/health", headers=evil).status_code == 400
    assert lan.post("/api/checkin", headers={**AUTH, **evil}).status_code == 400
    assert app.state.runtime.checkins == {}


@pytest.mark.parametrize(
    "base", ["http://testserver", "http://127.0.0.1:8000", "http://localhost:8000"]
)
def test_trusted_hosts_still_served(base: str) -> None:
    app, _ = build(make_settings(mode="sandbox"))
    client = TestClient(app, base_url=base, client=("203.0.113.7", 50000))
    assert client.get("/api/health").status_code == 200


def test_hosted_sandbox_answers_on_its_public_hostname() -> None:
    """The public sandbox has no owner or LAN route, so its deploy hostname is never refused."""
    app, _ = build(make_settings(mode="sandbox"))
    client = TestClient(app, base_url="https://vigil-sandbox.example.app")
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200


@pytest.mark.parametrize("host", ["192.168.1.10:8000", "10.0.0.5", "[::1]:8000", "127.0.0.1"])
def test_edge_box_opened_by_lan_ip_is_served(tmp_path, host: str) -> None:
    """A phone opens the edge box by its LAN IP (FR-034); rebinding needs a hostname."""
    _, lan = _owner(tmp_path)
    assert lan.get("/api/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "8.8.8.8", "192.168.1.10.evil.example", ""])
def test_edge_box_refuses_public_ip_and_foreign_names(tmp_path, host: str) -> None:
    _, lan = _owner(tmp_path)
    assert lan.get("/api/health", headers={"host": host}).status_code == 400


# --- F11: windows are set before they start, and carry created_at ---------------------------


def test_window_start_in_the_past_is_rejected(tmp_path) -> None:
    clock = FakeClock()
    app, lan = _owner(tmp_path, clock=clock)
    for offset in (-30, -59, -3600):
        body = {"start": _iso(clock, offset), "end": _iso(clock, 3600)}
        assert lan.post("/api/windows", json=body, headers=AUTH).status_code == 422, offset
    assert app.state.runtime.windows == {}


def test_window_records_created_at_and_persists_it(tmp_path) -> None:
    clock = FakeClock()
    app, lan = _owner(tmp_path, clock=clock)
    r = lan.post("/api/windows", json=_window(clock), headers=AUTH)
    assert r.status_code == 200, r.text
    created = r.json()["window"]
    now = datetime.fromtimestamp(clock.t, tz=UTC)
    assert datetime.fromisoformat(created["created_at"]) == now
    assert app.state.runtime.windows[created["id"]].created_at == now
    conn = sqlite3.connect(tmp_path / "edge.db")
    try:
        (stored,) = conn.execute(
            "SELECT created_at FROM expected_windows WHERE id = ?", (created["id"],)
        ).fetchone()
    finally:
        conn.close()
    assert datetime.fromisoformat(stored) == now


# --- spatial: nominal-FOV intrinsics and SAM landmark proposals -----------------------------


def test_pairs_solve_with_nominal_fov_intrinsics(tmp_path, monkeypatch) -> None:
    import vigil.spatial.calibrate as calibrate

    seen: list[Any] = []

    def fake_solve(pairs, k, **kw):
        seen.append(k)
        raise ValueError("stop here")

    monkeypatch.setattr(calibrate, "calibrate_extrinsics", fake_solve)
    _, lan = _owner(tmp_path)
    for i in range(6):
        pair = {"camera_id": "side_left", "pixel": [100 + 50 * i, 400 + 10 * i],
                "world": [float(i), 0.0, float(i % 3)]}  # fmt: skip
        r = lan.post("/api/spatial/pairs", json=pair, headers=AUTH)
        assert r.status_code == 200
    (k,) = seen
    assert k.source == "fov_nominal"
    assert k.width > 0
    assert k.height > 0


def test_landmarks_with_a_live_backend_need_the_token(tmp_path) -> None:
    class Landmarks(FakeBackend):
        def propose_landmarks(self, camera_id):
            self._start("landmarks")
            return LiveResult.model_construct(
                payload={"proposals": [{"label": "gate post", "pixel": [812, 410]}]},
                calls=self._call("landmarks", "sam-3.1"),
            )

    backend = Landmarks()
    settings = make_settings(mode="edge", db_path=tmp_path / "edge.db", owner_token=OWNER_TOKEN)
    app, _ = build(settings, backend=backend)
    lan = client_for(app, "10.0.0.8")
    assert lan.post("/api/spatial/landmarks", json={"camera_id": "side_left"}).status_code == 401
    assert backend.calls == []
    body = lan.post("/api/spatial/landmarks", json={"camera_id": "side_left"}, headers=AUTH).json()
    assert backend.calls == ["landmarks"]
    assert body["proposals"][0]["label"] == "gate post"
