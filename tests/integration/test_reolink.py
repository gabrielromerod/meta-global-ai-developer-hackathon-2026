"""Integration: Reolink probe and TCP-push AI events, offline (FR-030, FR-032, NFR-031).

Spec 12.1 row "Integration: Reolink": recorded TCP-push payloads become `camera_ai` events;
capture restarts after a dropped stream (simulated; see tests/unit/test_capture.py).

No camera, no network and no reolink_aio: every test drives the modules through fake
adapters. The XML payloads below are authored to match the Baichuan cmd_id 33
`AlarmEventList` messages that reolink_aio parses (reolink_aio/baichuan/baichuan.py,
`_parse_xml`, cmd_id 33): `<channelId>` (0-based), `<status>` ("MD" or "none") and
`<AItype>` (comma list of "people", "vehicle", "dog_cat", "none", "other").
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from vigil.models import CameraAiEvent, CameraCfg, CameraSource
from vigil.reolink import ai_events, probe
from vigil.reolink.ai_events import (
    AiEventTracker,
    PushState,
    parse_alarm_xml,
    stream_ai_events,
)
from vigil.reolink.probe import (
    HostInfo,
    ProbeReport,
    StreamUrl,
    camera_credentials,
    flv_url,
    redact,
    rtsp_url,
)

USER = "vigil_ro"
PASSWORD = "S3cr3t!pa:ss@word"
HOST = "192.0.2.10"  # RFC 5737 documentation address, never a real camera


def _alarm_xml(channel: int, status: str, ai: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" ?>\n<body>\n'
        '<AlarmEventList version="1.1">\n'
        '<AlarmEvent version="1.1">\n'
        f"<channelId>{channel}</channelId>\n<status>{status}</status>\n"
        "<recording>0</recording>\n<timeStamp>0</timeStamp>\n"
        f"<AItype>{ai}</AItype>\n</AlarmEvent>\n</AlarmEventList>\n</body>\n"
    )


def test_doorbell_press_is_a_separate_camera_event():
    camera = CameraCfg(id="doorbell", name="Doorbell", source=CameraSource(host_env="DOORBELL"))
    tracker = AiEventTracker([camera])
    states = parse_alarm_xml(_alarm_xml(0, "visitor", "none"), "DOORBELL", 10)
    events = tracker.update(states[0])
    assert len(events) == 1
    assert events[0].kind == "doorbell_press"
    assert events[0].camera_id == "doorbell"
    assert events[0].t1 is None
    closed = tracker.update(parse_alarm_xml(_alarm_xml(0, "none", "none"), "DOORBELL", 10.1)[0])
    assert closed[0].id == events[0].id
    assert closed[0].t1 == 10.1


@pytest.fixture
def cams() -> list[CameraCfg]:
    return [
        CameraCfg(id="front", name="Front entrance", source=CameraSource(host_env="RL_FRONT")),
        CameraCfg(id="backyard", name="Backyard", source=CameraSource(host_env="RL_BACK")),
    ]


@pytest.fixture
def nvr_cams() -> list[CameraCfg]:
    return [
        CameraCfg(id="front", name="Front", source=CameraSource(host_env="RL_NVR", channel=1)),
        CameraCfg(id="side_left", name="Left", source=CameraSource(host_env="RL_NVR", channel=2)),
    ]


@pytest.fixture
def creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REOLINK_USER", USER)
    monkeypatch.setenv("REOLINK_PASSWORD", PASSWORD)
    monkeypatch.setenv("RL_FRONT", HOST)
    monkeypatch.setenv("RL_BACK", "192.0.2.11")
    monkeypatch.setenv("RL_NVR", "192.0.2.20")


# ---------------------------------------------------------------------------
# URLs and redaction (spec 6 "Streams", NFR-031)
# ---------------------------------------------------------------------------


def test_rtsp_url_standalone_camera_uses_preview_01() -> None:
    url = rtsp_url(HOST, USER, PASSWORD)
    assert url.secret().startswith(f"rtsp://{USER}:")
    assert url.secret().endswith(f"@{HOST}:554/Preview_01_main")


def test_rtsp_url_nvr_channel_and_sub_stream() -> None:
    assert rtsp_url(HOST, USER, PASSWORD, channel=3).secret().endswith("/Preview_03_main")
    assert (
        rtsp_url(HOST, USER, PASSWORD, channel=2, stream="sub").secret().endswith("/Preview_02_sub")
    )


def test_rtsp_url_password_is_percent_encoded() -> None:
    secret = rtsp_url(HOST, USER, PASSWORD).secret()
    assert PASSWORD not in secret  # raw ':' and '@' would break the URL
    assert "S3cr3t%21pa%3Ass%40word" in secret


def test_stream_url_str_and_repr_are_redacted() -> None:
    url = rtsp_url(HOST, USER, PASSWORD)
    for shown in (str(url), repr(url), f"{url}", f"{url!r}"):
        assert "S3cr3t" not in shown
        assert USER not in shown
        assert HOST in shown
        assert "Preview_01_main" in shown


def test_flv_url_redacts_query_credentials() -> None:
    url = flv_url(HOST, USER, PASSWORD, channel=None, stream="main")
    assert "app=bcs" in url.secret()
    assert "stream=channel0_main.bcs" in url.secret()
    assert "S3cr3t" not in str(url)
    assert f"user={USER}" not in str(url)


@pytest.mark.parametrize(
    "text",
    [
        f"rtsp://{USER}:{PASSWORD}@{HOST}:554/Preview_01_main",
        f"http://{HOST}/flv?port=1935&app=bcs&user={USER}&password={PASSWORD}",
        f"connect failed for {USER} with {PASSWORD}",
    ],
)
def test_redact_removes_known_secrets_and_url_credentials(text: str) -> None:
    out = redact(text, secrets=[USER, PASSWORD])
    assert PASSWORD not in out
    assert "S3cr3t" not in out
    assert USER not in out


def test_redact_reads_secrets_from_env(creds: None) -> None:
    assert PASSWORD not in redact(f"oops {PASSWORD}")


def test_stream_url_formatting_paths_are_all_redacted() -> None:
    url = rtsp_url(HOST, USER, PASSWORD)
    shown = [format(url), "%s" % url, f"{url}", str([url]), str({"u": url})]  # noqa: UP031
    assert all("S3cr3t" not in s for s in shown)


# ---------------------------------------------------------------------------
# Probe (FR-030)
# ---------------------------------------------------------------------------


class FakeProbeAdapter:
    """Stands in for reolink_aio.api.Host. Logs and raises like a careless library would."""

    def __init__(self, *, fail_rtsp: bool = False, crash: bool = False) -> None:
        self.fail_rtsp = fail_rtsp
        self.crash = crash
        self.calls: list[tuple[str, str]] = []

    async def host_info(self, host: str, username: str, password: str) -> HostInfo:
        self.calls.append(("host_info", host))
        logging.getLogger("vigil.reolink.probe").warning(
            "login to http://%s:%s@%s/api.cgi", username, password, host
        )
        if self.crash:
            raise ConnectionError(f"Login failed for rtsp://{username}:{password}@{host}:554/")
        return HostInfo(
            is_nvr=host.endswith(".20"),
            model="RLN8-410" if host.endswith(".20") else "RLC-811A",
            firmware="v3.1.0.2347_23061923",
            channels=[0, 1, 2, 3] if host.endswith(".20") else [0],
            channel_models={0: "RLC-811A", 1: "RLC-510A"},
            channel_firmware={0: "v3.1.0.2347", 1: "v3.0.0.2033"},
            ai_types={0: ["people", "vehicle", "dog_cat"], 1: ["people", "vehicle"]},
        )

    async def check_stream(self, url: StreamUrl) -> bool:
        self.calls.append(("check_stream", url.protocol))
        if url.protocol == "rtsp":
            return not self.fail_rtsp
        return True


def test_probe_reports_model_firmware_streams_and_ai(cams, creds) -> None:
    report = asyncio.run(probe.probe(cams[0], FakeProbeAdapter()))
    assert isinstance(report, ProbeReport)
    assert report.camera_id == "front"
    assert report.ok
    assert report.model == "RLC-811A"
    assert report.firmware.startswith("v3.1.0")
    assert report.rtsp_main
    assert report.rtsp_sub
    assert report.flv
    assert report.ai_person
    assert report.ai_vehicle
    assert report.channel == 0
    assert report.nvr is False


def test_probe_nvr_channel_maps_to_zero_based_index(nvr_cams, creds) -> None:
    report = asyncio.run(probe.probe(nvr_cams[1], FakeProbeAdapter()))
    assert report.nvr is True
    assert report.channel == 1  # config channel 2 -> reolink_aio channel index 1
    assert report.model == "RLC-510A"
    assert report.firmware == "v3.0.0.2033"
    assert "Preview_02_main" in report.rtsp_url


def test_probe_rtsp_unreachable_falls_back_to_flv_note(cams, creds) -> None:
    report = asyncio.run(probe.probe(cams[0], FakeProbeAdapter(fail_rtsp=True)))
    assert report.rtsp_main is False
    assert report.flv is True
    assert report.ok is True  # FLV is the documented fallback (spec 6 "Streams")
    assert any("FLV" in n for n in report.notes)


def test_probe_missing_credentials_is_a_clear_error(cams, monkeypatch) -> None:
    monkeypatch.delenv("REOLINK_USER", raising=False)
    monkeypatch.delenv("REOLINK_PASSWORD", raising=False)
    monkeypatch.setenv("RL_FRONT", HOST)
    report = asyncio.run(probe.probe(cams[0], FakeProbeAdapter()))
    assert report.ok is False
    assert "REOLINK_USER" in (report.error or "")


def test_probe_missing_host_env_is_a_clear_error(cams, monkeypatch) -> None:
    monkeypatch.setenv("REOLINK_USER", USER)
    monkeypatch.setenv("REOLINK_PASSWORD", PASSWORD)
    monkeypatch.delenv("RL_FRONT", raising=False)
    report = asyncio.run(probe.probe(cams[0], FakeProbeAdapter()))
    assert report.ok is False
    assert "RL_FRONT" in (report.error or "")


def test_credentials_never_appear_in_logs(cams, creds, caplog) -> None:
    """NFR-031 log grep test: success, failure, repr and exceptions all stay redacted."""
    caplog.set_level(logging.DEBUG)
    good = asyncio.run(probe.probe(cams[0], FakeProbeAdapter()))
    bad = asyncio.run(probe.probe(cams[0], FakeProbeAdapter(crash=True)))
    logging.getLogger("vigil.reolink").info("report %r / %s", good, bad)
    assert bad.ok is False
    assert "Login failed" in (bad.error or "")
    everything = caplog.text + repr(good) + repr(bad) + good.model_dump_json()
    everything += bad.model_dump_json() + str(camera_credentials(cams[0]))
    assert PASSWORD not in everything
    assert "S3cr3t" not in everything
    assert "S3cr3t%21" not in everything
    assert f"{USER}:" not in everything


def test_probe_all_runs_every_camera(cams, creds) -> None:
    reports = asyncio.run(probe.probe_all(cams, FakeProbeAdapter()))
    assert [r.camera_id for r in reports] == ["front", "backyard"]


def test_real_adapter_without_reolink_aio_is_blocked(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "reolink_aio.api", None)
    with pytest.raises(probe.ReolinkUnavailable, match="reolink"):
        probe.ReolinkAioAdapter()


# ---------------------------------------------------------------------------
# TCP push AI events (FR-032)
# ---------------------------------------------------------------------------


def test_parse_alarm_xml_reads_channel_motion_and_ai_types() -> None:
    states = parse_alarm_xml(_alarm_xml(0, "MD", "people,vehicle"), host_key="RL_FRONT", t=5.0)
    assert states == [
        PushState(
            host_key="RL_FRONT",
            channel=0,
            t=5.0,
            motion=True,
            ai={"people": True, "vehicle": True, "dog_cat": False},
        )
    ]


def test_parse_alarm_xml_none_and_other() -> None:
    (s,) = parse_alarm_xml(_alarm_xml(1, "none", "none"), host_key="h", t=1.0)
    assert s.motion is False
    assert not any(s.ai.values())
    (o,) = parse_alarm_xml(_alarm_xml(1, "none", "other"), host_key="h", t=1.0)
    assert o.motion is True  # "other" implies motion, as in reolink_aio


def test_parse_alarm_xml_ignores_garbage() -> None:
    assert parse_alarm_xml("<body><nope/></body>", host_key="h", t=0) == []
    assert parse_alarm_xml("not xml at all", host_key="h", t=0) == []


def _recorded_walk_in() -> list[tuple[float, str, str]]:
    """A person walks into the front camera, a car arrives, the person lingers, all leave."""
    return [
        (100.0, "RL_FRONT", _alarm_xml(0, "MD", "people")),
        (100.5, "RL_FRONT", _alarm_xml(0, "MD", "people")),  # repeated push: dedupe
        (101.0, "RL_FRONT", _alarm_xml(0, "MD", "people")),
        (104.0, "RL_FRONT", _alarm_xml(0, "MD", "people,vehicle")),
        (109.0, "RL_FRONT", _alarm_xml(0, "MD", "vehicle")),  # person closes at 109
        (110.0, "RL_FRONT", _alarm_xml(0, "MD", "people,vehicle")),  # flicker: debounced
        (118.0, "RL_FRONT", _alarm_xml(0, "none", "none")),
        (200.0, "RL_BACK", _alarm_xml(0, "MD", "people")),
        (230.0, "RL_BACK", _alarm_xml(0, "none", "none")),
    ]


def _events_from(recorded, cams) -> list[CameraAiEvent]:
    tracker = AiEventTracker(cams, debounce_s=3.0)
    out: list[CameraAiEvent] = []
    for t, host_key, xml in recorded:
        for state in parse_alarm_xml(xml, host_key=host_key, t=t):
            out.extend(tracker.update(state))
    return out


def test_recorded_payloads_become_camera_ai_events(cams) -> None:
    emitted = _events_from(_recorded_walk_in(), cams)
    final = {e.id: e for e in emitted}  # emissions are upserts keyed by id
    events = sorted(final.values(), key=lambda e: (e.t0, e.kind))
    assert [(e.camera_id, e.kind, e.t0, e.t1) for e in events] == [
        ("front", "person", 100.0, 118.0),
        ("front", "vehicle", 104.0, 118.0),
        ("backyard", "person", 200.0, 230.0),
    ]
    assert all(isinstance(e, CameraAiEvent) for e in emitted)


def test_open_event_is_emitted_immediately_with_t1_none(cams) -> None:
    """The UI cone must pulse at once (spec 5.13), before the event closes."""
    first = _events_from(_recorded_walk_in()[:1], cams)
    assert len(first) == 1
    assert first[0].t1 is None
    assert first[0].kind == "person"


def test_repeated_pushes_are_deduplicated(cams) -> None:
    emitted = _events_from(_recorded_walk_in()[:3], cams)
    assert len(emitted) == 1


def test_event_ids_are_stable_and_unique(cams) -> None:
    a = {e.id for e in _events_from(_recorded_walk_in(), cams)}
    b = {e.id for e in _events_from(_recorded_walk_in(), cams)}
    assert a == b
    assert len(a) == 3


def test_unknown_host_or_channel_is_ignored(cams) -> None:
    tracker = AiEventTracker(cams)
    stray = PushState(host_key="RL_UNKNOWN", channel=0, t=1.0, motion=True, ai={"people": True})
    assert tracker.update(stray) == []


def test_nvr_channels_map_to_cameras(nvr_cams) -> None:
    tracker = AiEventTracker(nvr_cams)
    (state,) = parse_alarm_xml(_alarm_xml(1, "MD", "people"), host_key="RL_NVR", t=3.0)
    (ev,) = tracker.update(state)
    assert ev.camera_id == "side_left"


def test_pet_and_motion_are_off_by_default(cams) -> None:
    tracker = AiEventTracker(cams)
    (state,) = parse_alarm_xml(_alarm_xml(0, "MD", "dog_cat"), host_key="RL_FRONT", t=3.0)
    assert tracker.update(state) == []
    wide = AiEventTracker(cams, kinds=("person", "vehicle", "pet", "motion"))
    kinds = {e.kind for e in wide.update(state)}
    assert kinds == {"pet", "motion"}


def test_flush_closes_open_events(cams) -> None:
    tracker = AiEventTracker(cams)
    (state,) = parse_alarm_xml(_alarm_xml(0, "MD", "people"), host_key="RL_FRONT", t=3.0)
    tracker.update(state)
    (closed,) = tracker.flush(t=9.0)
    assert closed.t1 == 9.0


class FakePushAdapter:
    def __init__(self, recorded) -> None:
        self.recorded = recorded
        self.closed = False

    async def states(self, cams):
        for t, host_key, xml in self.recorded:
            for state in parse_alarm_xml(xml, host_key=host_key, t=t):
                yield state
            await asyncio.sleep(0)
        self.closed = True


def test_stream_ai_events_over_fake_adapter(cams) -> None:
    adapter = FakePushAdapter(_recorded_walk_in())

    async def collect() -> list[CameraAiEvent]:
        return [e async for e in stream_ai_events(cams, adapter)]

    emitted = asyncio.run(collect())
    final = {e.id: e for e in emitted}
    assert len(final) == 3
    assert all(e.t1 is not None for e in final.values())
    assert adapter.closed


def test_stream_ai_events_without_reolink_aio_is_blocked(cams, monkeypatch) -> None:
    monkeypatch.setattr(
        ai_events,
        "import_reolink_host",
        lambda: (_ for _ in ()).throw(ai_events.ReolinkUnavailable("reolink-aio missing")),
    )

    async def first():
        async for _ in stream_ai_events(cams):
            return

    with pytest.raises(ai_events.ReolinkUnavailable):
        asyncio.run(first())


# ---------------------------------------------------------------------------
# Restreamer config (infra/go2rtc.yaml)
# ---------------------------------------------------------------------------


def test_go2rtc_config_has_only_ac_cameras_and_no_literal_credentials() -> None:
    import re
    from pathlib import Path

    import yaml

    from vigil.ingest.config import load_config

    path = Path(__file__).resolve().parents[2] / "infra" / "go2rtc.yaml"
    text = path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(text)
    home = load_config(path.parents[1] / "config/cameras.yaml")
    ac = [c for c in home.cameras if c.power_profile in {"plugin_wifi", "doorbell"}]
    expected = {name for c in ac for name in (c.id, c.id + "_sub")}
    assert set(cfg["streams"]) == expected
    for cam in ac:
        for name in (cam.id, f"{cam.id}_sub"):
            (src,) = cfg["streams"][name]
            assert src.startswith("rtsp://${REOLINK_USER}:${REOLINK_PASSWORD}@${REOLINK_")
            assert "#media=video" in src  # no audio track requested (FR-003, NFR-002)
    # every userinfo in a URL is an env reference, never a literal secret
    for m in re.finditer(r"://([^@\s/]+)@", text):
        assert re.fullmatch(r"\$\{\w+\}:\$\{\w+\}", m.group(1)), m.group(1)
    assert cfg["rtsp"]["listen"].startswith("127.0.0.1:")
    assert "candidates" not in cfg["webrtc"]
