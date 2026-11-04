"""FR-030 setup: find Reolink cameras on the LAN, identify them, map them to cameras.yaml."""

import asyncio
import typing

import httpx
import pytest
import respx

from vigil.reolink import setup as rs

ARP = """\
? (10.99.4.1) at 50:27:a9:f3:10:d on en0 ifscope [ethernet]
? (10.99.4.52) at d0:76:2:0a:0b:01 on en0 ifscope [ethernet]
? (10.99.5.174) at d0:76:2:0a:0b:02 on en0 ifscope [ethernet]
? (10.99.4.90) at (incomplete) on en0 ifscope [ethernet]
10.99.4.77 ether ec:71:db:00:11:22 C wlan0
"""

CAMERAS = [
    {"id": "front_left_duo", "name": "Front left Duo", "model": "Duo Floodlight Wi-Fi",
     "host_env": "REOLINK_FRONT_LEFT_DUO_HOST"},
    {"id": "front_right_duo", "name": "Front right Duo", "model": "Duo Floodlight Wi-Fi",
     "host_env": "REOLINK_FRONT_RIGHT_DUO_HOST"},
    {"id": "doorbell", "name": "Doorbell", "model": "Video doorbell Wi-Fi",
     "host_env": "REOLINK_DOORBELL_HOST"},
    {"id": "porch", "name": "Porch", "model": None, "host_env": "REOLINK_PORCH_HOST"},
]  # fmt: skip


def _device(ip, model, name):
    return rs.Device(ip=ip, model=model, name=name)


def test_reolink_setup_arp_finds_reolink_macs():
    found = rs.reolink_from_arp(ARP)
    assert found == {
        "10.99.4.52": "d0:76:02:0a:0b:01",
        "10.99.5.174": "d0:76:02:0a:0b:02",
        "10.99.4.77": "ec:71:db:00:11:22",
    }


@respx.mock
def test_reolink_setup_identify_reads_model_and_name(monkeypatch):
    monkeypatch.setenv("REOLINK_USER", "admin")
    monkeypatch.setenv("REOLINK_PASSWORD", "s3cret-pw")
    login = respx.post("https://10.99.4.52/cgi-bin/api.cgi", params={"cmd": "Login"}).respond(
        json=[{"cmd": "Login", "code": 0, "value": {"Token": {"name": "tok123"}}}]
    )
    respx.post("https://10.99.4.52/cgi-bin/api.cgi", params={"cmd": "GetDevInfo"}).respond(
        json=[
            {
                "cmd": "GetDevInfo",
                "code": 0,
                "value": {
                    "DevInfo": {"model": "Reolink Duo Floodlight WiFi", "name": "Front Left"}
                },
            }
        ]
    )
    respx.post("https://10.99.4.52/cgi-bin/api.cgi", params={"cmd": "GetNetPort"}).respond(
        json=[
            {
                "cmd": "GetNetPort",
                "code": 0,
                "value": {"NetPort": {"rtspEnable": 0, "rtspPort": 554, "httpEnable": 1}},
            }
        ]
    )
    respx.post("https://10.99.4.52/cgi-bin/api.cgi", params={"cmd": "Logout"}).respond(json=[])
    dev = asyncio.run(rs.identify("10.99.4.52", mac="d0:76:02:0a:0b:01"))
    assert (dev.model, dev.name, dev.rtsp_enabled, dev.error) == (
        "Reolink Duo Floodlight WiFi",
        "Front Left",
        False,
        None,
    )
    body = login.calls[0].request.content.decode()
    assert "s3cret-pw" in body  # sent in the POST body, never in the URL
    assert "s3cret-pw" not in str(login.calls[0].request.url)
    assert "s3cret-pw" not in repr(dev)
    assert "tok123" not in repr(dev)


@respx.mock
def test_reolink_setup_bad_login_is_reported_without_secret(monkeypatch):
    monkeypatch.setenv("REOLINK_USER", "admin")
    monkeypatch.setenv("REOLINK_PASSWORD", "s3cret-pw")
    respx.post("https://10.99.4.52/cgi-bin/api.cgi").respond(
        json=[{"cmd": "Login", "code": 1, "error": {"detail": "login failed", "rspCode": -7}}]
    )
    dev = asyncio.run(rs.identify("10.99.4.52"))
    assert dev.model is None
    assert "login" in dev.error
    assert "s3cret-pw" not in dev.error


def test_reolink_setup_identify_needs_credentials(monkeypatch):
    monkeypatch.delenv("REOLINK_USER", raising=False)
    monkeypatch.delenv("REOLINK_PASSWORD", raising=False)
    dev = asyncio.run(rs.identify("10.99.4.52"))
    assert "REOLINK_USER" in dev.error


def test_reolink_setup_match_assigns_by_model_and_name():
    devices = [
        _device("10.99.4.52", "Reolink Duo Floodlight WiFi", "Front Left"),
        _device("10.99.4.60", "Reolink Duo Floodlight WiFi", "Garage right"),
        _device("10.99.5.174", "Reolink Video Doorbell WiFi", "Front Door"),
        _device("10.99.4.70", "E1 Outdoor", "Porch"),
    ]
    plan = rs.match(devices, CAMERAS)
    assert {a.camera_id: a.ip for a in plan.assigned} == {
        "front_left_duo": "10.99.4.52",
        "front_right_duo": "10.99.4.60",
        "doorbell": "10.99.5.174",
        "porch": "10.99.4.70",
    }
    assert plan.unmatched == []
    assert plan.missing == []


def test_reolink_setup_match_leaves_ties_for_the_owner():
    devices = [
        _device("10.99.4.52", "Reolink Duo Floodlight WiFi", "Duo 1"),
        _device("10.99.4.60", "Reolink Duo Floodlight WiFi", "Duo 2"),
    ]
    plan = rs.match(devices, CAMERAS)
    assert plan.assigned == []
    assert sorted(d.ip for d in plan.unmatched) == ["10.99.4.52", "10.99.4.60"]
    assert "front_left_duo" in plan.missing


def test_reolink_setup_match_never_crosses_model_families():
    plan = rs.match([_device("10.99.4.52", "Reolink Video Doorbell WiFi", "Front left")], CAMERAS)
    assert [(a.camera_id, a.ip) for a in plan.assigned] == [("doorbell", "10.99.4.52")]


def test_reolink_setup_env_update_rewrites_only_host_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "MODEL_API_KEY=keep-me\nREOLINK_DOORBELL_HOST=\n# comment\nREOLINK_PORCH_HOST=1.2.3.4\n",
        encoding="utf-8",
    )
    changed = rs.update_env(
        env,
        {"REOLINK_DOORBELL_HOST": "10.99.5.174", "REOLINK_FRONT_LEFT_DUO_HOST": "10.99.4.52"},
    )
    text = env.read_text(encoding="utf-8")
    assert text.splitlines() == [
        "MODEL_API_KEY=keep-me",
        "REOLINK_DOORBELL_HOST=10.99.5.174",
        "# comment",
        "REOLINK_PORCH_HOST=1.2.3.4",
        "REOLINK_FRONT_LEFT_DUO_HOST=10.99.4.52",
    ]
    assert changed == ["REOLINK_DOORBELL_HOST", "REOLINK_FRONT_LEFT_DUO_HOST"]


def test_reolink_setup_env_update_refuses_non_host_keys(tmp_path):
    with pytest.raises(ValueError, match="HOST"):
        rs.update_env(tmp_path / ".env", {"REOLINK_PASSWORD": "x"})


def test_reolink_setup_port_scan_finds_open_hosts():
    async def run():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            return await rs.scan_port(["127.0.0.1", "192.0.2.1"], port=port, timeout=0.3)

    assert asyncio.run(run()) == ["127.0.0.1"]


def test_reolink_setup_http_errors_become_messages():
    err = rs._describe(httpx.ConnectTimeout("timed out"))
    assert "timed out" in err.lower() or "unreachable" in err.lower()


class _FakeBaichuanHost:
    """reolink_aio.Host stand-in for a camera whose HTTP API is off."""

    seen: typing.ClassVar[dict] = {}

    def __init__(self, host, username, password, **kwargs):
        _FakeBaichuanHost.seen = {"host": host, **kwargs}

    async def get_host_data(self):
        pass

    def camera_model(self, ch):
        return "Reolink Video Doorbell WiFi"

    def camera_name(self, ch):
        return "Timbre"

    async def logout(self):
        pass


@respx.mock
def test_reolink_setup_identify_falls_back_to_baichuan(monkeypatch):
    monkeypatch.setenv("REOLINK_USER", "admin")
    monkeypatch.setenv("REOLINK_PASSWORD", "s3cret-pw")
    respx.post("https://10.99.5.174/cgi-bin/api.cgi").mock(side_effect=httpx.ConnectError("no"))
    respx.post("http://10.99.5.174/cgi-bin/api.cgi").mock(side_effect=httpx.ConnectError("no"))
    dev = asyncio.run(rs.identify("10.99.5.174", host_cls=_FakeBaichuanHost))
    assert (dev.model, dev.name, dev.error) == ("Reolink Video Doorbell WiFi", "Timbre", None)
    assert _FakeBaichuanHost.seen == {"host": "10.99.5.174", "bc_only": True}


def test_reolink_setup_spanish_app_names_match():
    devices = [_device("10.99.5.174", "Reolink Video Doorbell WiFi", "Timbre")]
    duo = [_device("10.99.4.52", "Reolink Duo Floodlight WiFi", "Frente izquierda")]
    plan = rs.match(devices + duo, CAMERAS)
    assert {a.camera_id: a.ip for a in plan.assigned} == {
        "doorbell": "10.99.5.174",
        "front_left_duo": "10.99.4.52",
    }


def test_reolink_setup_owner_pins_resolve_ties():
    devices = [
        _device("10.99.4.52", "Reolink Duo Floodlight WiFi", "Reolink Duo Floodlight WiFi"),
        _device("10.99.5.71", "Reolink Duo Floodlight WiFi", "Reolink Duo Floodlight WiFi"),
    ]
    plan = rs.match(devices, CAMERAS, pins={"front_left_duo": "10.99.4.52"})
    assert {a.camera_id: a.ip for a in plan.assigned} == {
        "front_left_duo": "10.99.4.52",
        "front_right_duo": "10.99.5.71",
    }
    with pytest.raises(ValueError, match="unknown"):
        rs.match(devices, CAMERAS, pins={"garage": "10.99.4.52"})


class _HttpOffHost:
    """Fails over HTTP (the API is off) and connects with ``bc_only``."""

    made: typing.ClassVar[list] = []

    def __init__(self, host, username, password, **kwargs):
        self.bc_only = kwargs.get("bc_only", False)
        _HttpOffHost.made.append(self.bc_only)

    async def get_host_data(self):
        if not self.bc_only:
            raise ConnectionRefusedError("HTTP off")

    async def logout(self):
        pass


def test_reolink_push_connects_over_baichuan_when_http_is_off():
    from vigil.reolink.ai_events import connect_host

    _HttpOffHost.made = []
    host = asyncio.run(connect_host(_HttpOffHost, "10.99.5.73", "u", "p"))
    assert host.bc_only is True
    assert _HttpOffHost.made == [False, True]
