"""FIXTURE: standalone Reolink Wi-Fi settings, telemetry and battery refusal."""

import asyncio

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from vigil.cli import app
from vigil.models import CameraCfg, CameraSource
from vigil.reolink import capture, probe


def camera(stream="sub"):
    return CameraCfg(
        id="front", name="Front", source=CameraSource(host_env="TEST_WIFI_HOST", stream=stream)
    )


class WifiAdapter:
    def __init__(self, battery=False):
        self.battery = battery
        self.checked = []

    async def host_info(self, *args):
        return probe.HostInfo(
            channels=[0],
            battery={0: self.battery},
            wifi_signal={0: -75},
            stream_sources={0: {"sub": SecretStr("rtsp://viewer:fixture@192.0.2.10/custom_sub")}},
            stream_stats={0: {"sub": {"codec": "h264", "bitrate": 3000000, "fps": 15}}},
        )

    async def check_stream(self, url):
        self.checked.append(url)
        return True


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("TEST_WIFI_HOST", "192.0.2.10")
    monkeypatch.setenv("REOLINK_USER", "viewer")
    monkeypatch.setenv("REOLINK_PASSWORD", "fixture")


def test_reolink_wifi_probe_profile(creds):
    adapter = WifiAdapter()
    result = asyncio.run(probe.probe(camera(), adapter))
    assert result.ok
    assert result.stream == "sub"
    assert result.codec == "h264"
    assert result.bitrate == 3000000
    assert result.fps == 15
    assert result.wifi_signal == -75
    assert result.wifi_weak
    assert "custom_sub" in result.rtsp_url


def test_reolink_wifi_probe_refuses_battery(creds):
    adapter = WifiAdapter(battery=True)
    result = asyncio.run(probe.probe(camera(), adapter))
    assert not result.ok
    assert "battery" in result.error
    assert not adapter.checked


def test_reolink_ext_stream_is_valid():
    assert camera("ext").source.stream == "ext"


def test_reolink_camera_filter(tmp_path, monkeypatch):
    config = tmp_path / "cameras.yaml"
    config.write_text(
        "cameras:\n- id: front\n  name: Front\n  source: {host_env: TEST_WIFI_HOST}\n"
        "- id: back\n  name: Back\n  source: {host_env: TEST_BACK_HOST}\n"
    )
    monkeypatch.setenv("TEST_WIFI_HOST", "192.0.2.10")
    seen = []

    async def fake_probe(cams):
        seen.extend(c.id for c in cams)
        return []

    monkeypatch.setattr(probe, "probe_all", fake_probe)
    result = CliRunner().invoke(
        app,
        [
            "reolink",
            "probe",
            "--config",
            str(config),
            "--env-file",
            str(tmp_path / "none"),
            "--camera",
            "front",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == ["front"]


def test_capture_refuses_battery_before_starting_ffmpeg(tmp_path, creds):
    with pytest.raises(ValueError, match="battery"):
        asyncio.run(
            capture.run_capture(
                [camera()],
                tmp_path,
                via_restreamer=False,
                adapter=WifiAdapter(battery=True),
                ffmpeg="fake-ffmpeg",
            )
        )


def test_capture_passes_selected_sub_stream_to_ffmpeg(tmp_path, creds):
    from tests.unit.test_capture import FakeClock, FakeRunner

    clock = FakeClock()
    runner = FakeRunner(clock, [(1, 0)])
    asyncio.run(
        capture.run_capture(
            [camera()],
            tmp_path,
            via_restreamer=False,
            adapter=WifiAdapter(),
            runner=runner,
            clock=clock,
            sleep=clock.sleep,
            max_restarts=0,
            ffmpeg="fake-ffmpeg",
        )
    )
    assert "/custom_sub" in runner.cmds[0][runner.cmds[0].index("-i") + 1]


def test_reolink_adapter_uses_sdk_stream_source_and_wifi_dbm(monkeypatch):
    calls = []

    class Host:
        channels = (0,)
        is_nvr = False
        model = "synthetic Wi-Fi"
        sw_version = "fixture"
        rtsp_port, port, rtmp_port = 554, 80, 1935

        def __init__(self, *args):
            pass

        async def get_host_data(self):
            pass

        async def logout(self):
            calls.append("logout")

        def supported(self, *args):
            return False

        async def get_rtsp_stream_source(self, channel, stream, check=True):
            calls.append((channel, stream, check))
            return f"rtsp://viewer:fixture@192.0.2.10/sdk_{stream}"

        def encoding(self, *args):
            return "h264"

        def bit_rate(self, *args):
            return 3000

        def frame_rate(self, *args):
            return 15

        def wifi_connection(self):
            return True

        async def get_state(self, command):
            calls.append(command)

        def wifi_signal(self, *args):
            return -75

        def camera_model(self, *args):
            return self.model

        def camera_sw_version(self, *args):
            return self.sw_version

        def ai_supported_types(self, *args):
            return ["people"]

    monkeypatch.setattr(probe, "import_reolink_host", lambda: Host)
    info = asyncio.run(probe.ReolinkAioAdapter().host_info("192.0.2.10", "viewer", "fixture"))
    assert (0, "sub", False) in calls
    assert "GetWifiSignal" in calls
    assert calls[-1] == "logout"
    assert info.wifi_signal[0] == -75
    assert info.stream_stats[0]["main"].bitrate == 3000000
    assert "sdk_sub" in info.stream_sources[0]["sub"].get_secret_value()
