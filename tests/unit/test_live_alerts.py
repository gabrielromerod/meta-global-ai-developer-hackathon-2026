"""FR-032/FR-034: Reolink push alerts reach the LAN live stream (presence only, no pixels)."""

import asyncio
import json

from vigil.api.live import LiveHub
from vigil.models import CameraAiEvent
from vigil.reolink import live_alerts


async def _events(*items):
    for item in items:
        yield item


def test_live_alerts_publish_camera_ai_and_log(tmp_path):
    hub = LiveHub()
    log = tmp_path / "live" / "alerts.jsonl"
    opened = CameraAiEvent(id="e1", camera_id="porch", kind="person", t0=2.0)
    closed = opened.model_copy(update={"t1": 9.5})
    asyncio.run(
        live_alerts.publish_alerts(
            _events(opened, closed),
            hub,
            log,
            names={"porch": "Porch"},
            session_start=1_762_200_000.0,
        )
    )

    async def recent_messages():
        queue, recent = hub.subscribe()
        hub.unsubscribe(queue)
        return recent

    recent = asyncio.run(recent_messages())
    assert [k for k, _ in recent] == ["camera_ai", "camera_ai"]
    first, last = recent[0][1], recent[1][1]
    assert first == {
        "id": "e1",
        "camera_id": "porch",
        "camera_name": "Porch",
        "kind": "person",
        "started_at": "2025-11-03T20:00:02Z",
        "ended_at": None,
        "open": True,
    }
    assert last["ended_at"] == "2025-11-03T20:00:09.500000Z"
    assert last["open"] is False
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows == [first, last]
    assert not set(first) & {"box", "position", "image", "frame", "track"}


def test_live_alerts_only_ac_cameras_with_hosts(sample_config):
    cams = live_alerts.alert_cameras(sample_config.cameras, env={})
    assert cams == []
    cam = next(c for c in sample_config.cameras if c.source and c.source.host_env)
    env = {cam.source.host_env: "192.168.1.20"}
    assert [c.id for c in live_alerts.alert_cameras(sample_config.cameras, env=env)] == [cam.id]


def test_live_alerts_off_unless_enabled(monkeypatch):
    monkeypatch.delenv("VIGIL_LIVE_ALERTS", raising=False)
    assert live_alerts.enabled(mode="edge") is False
    monkeypatch.setenv("VIGIL_LIVE_ALERTS", "1")
    assert live_alerts.enabled(mode="edge") is True
    assert live_alerts.enabled(mode="sandbox") is False


def test_live_alerts_start_with_the_server(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from vigil.api.app import create_app
    from vigil.settings import Settings

    started = []

    async def fake_run(cameras, hub, data_dir):
        started.append(data_dir)
        hub.publish("camera_ai", {"id": "e1", "kind": "person"})

    monkeypatch.setattr(live_alerts, "run", fake_run)
    monkeypatch.setenv("VIGIL_LIVE_ALERTS", "1")
    settings = Settings(
        _env_file=None,
        mode="edge",
        MODEL_API_KEY="invalid",
        meta_cache_only=True,
        data_dir=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        client.get("/healthz")
    assert started == [tmp_path]

    started.clear()
    monkeypatch.delenv("VIGIL_LIVE_ALERTS")
    with TestClient(create_app(settings)):
        pass
    assert started == []


def test_live_alerts_load_only_reolink_lines(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MODEL_API_KEY=not-copied\nREOLINK_USER=admin\nREOLINK_PORCH_HOST=192.168.1.9\n"
        "REOLINK_DOORBELL_HOST=\n",
        encoding="utf-8",
    )
    environ = {"REOLINK_USER": "kept"}
    live_alerts.load_reolink_env(env_file, environ)
    assert environ == {"REOLINK_USER": "kept", "REOLINK_PORCH_HOST": "192.168.1.9"}
