"""Local demo convenience: the owner token is handed only to a browser on this machine.

Opt-in with VIGIL_OWNER_AUTOLOGIN=1. Loopback peer and a loopback Host header only (no LAN
peer, no DNS-rebinding host), and never when no owner token is configured.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.test_api import OWNER_TOKEN, FakeClock, build, make_settings, owner_settings


def _client(tmp_path, monkeypatch, ip="127.0.0.1", on=True, token=True):
    if on:
        monkeypatch.setenv("VIGIL_OWNER_AUTOLOGIN", "1")
    else:
        monkeypatch.delenv("VIGIL_OWNER_AUTOLOGIN", raising=False)
    settings = (owner_settings(tmp_path) if token
                else make_settings(mode="edge", db_path=tmp_path / "edge.db"))  # fmt: skip
    _, client = build(settings, clock=FakeClock(), ip=ip)
    return client


def test_loopback_browser_gets_the_owner_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/owner/local-session", headers={"host": "127.0.0.1:8000"})
    assert r.status_code == 200
    assert r.json() == {"token": OWNER_TOKEN}
    assert r.headers["cache-control"] == "no-store"


def test_autologin_is_off_by_default(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, on=False)
    assert client.get("/api/owner/local-session").status_code == 404


def test_lan_peer_never_gets_the_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, ip="192.168.1.20")
    assert client.get("/api/owner/local-session").status_code == 404


def test_rebinding_host_never_gets_the_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/api/owner/local-session", headers={"host": "evil.example:8000"})
    assert r.status_code in {400, 404}  # the host guard may refuse it first


def test_no_token_configured_gives_nothing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, token=False)
    r = client.get("/api/owner/local-session", headers={"host": "127.0.0.1:8000"})
    assert r.status_code == 404
    assert isinstance(client, TestClient)
