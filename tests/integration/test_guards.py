"""Guards (spec 12.1, P0 blocking suite 4): spend caps including the $25 judging cap, 429 on
the 11th live call a minute, 413 on oversize input, no Contributor-mode model IDs, the API key
never served, LAN-only routes.

FR-026, FR-043, NFR-004, NFR-009, NFR-013, NFR-014, NFR-015, NFR-037; spec 11.6 item 6.
"""

from __future__ import annotations

import io
import json
import wave
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import respx

from tests.integration.test_api import (
    SENTINEL_KEY,
    ExplodingBackend,
    FakeBackend,
    FakeClock,
    build,
    client_for,
    make_settings,
)
from vigil.api.guards import (
    ModelNotAllowedError,
    RateLimiter,
    check_model_allowed,
    is_lan_request,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRIBUTOR = "-" + "contributor"
LIVE_PROTECT = {"camera_id": "side_right", "point": {"x": 640, "y": 500}, "live": True}


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    with respx.mock(assert_all_called=False):
        yield


NOTICE_BUDGET = "Live budget for today used; recorded result shown"
PT = ZoneInfo("America/Los_Angeles")


def _wav(seconds: float, rate: int = 16000) -> bytes:
    """16 kHz mono 16-bit PCM, the format the browser encodes (FR-022)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def _pt(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=PT).timestamp()


def _judging(clock: FakeClock, **kw):
    """Settings for the judging period: credit window over, VIGIL_ALLOW_PAID=1, end ahead."""
    now = datetime.fromtimestamp(clock.t, tz=UTC)
    base = {"credit_window_end": now - timedelta(days=1), "allow_paid": True,
            "judging_end": now + timedelta(days=10)}  # fmt: skip
    base.update(kw)
    return make_settings(**base)


def _transcribe_live(client, seconds: float = 3) -> dict:
    r = client.post("/api/voice/transcribe?live=true", content=_wav(seconds),
                    headers={"content-type": "audio/wav"})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


def _rerun_live(client) -> dict:
    job = client.post("/api/visits/v_c/rerun", json={"stage": "story", "live": True}).json()
    return client.get(f"/api/jobs/{job['job_id']}").json()["result"]


# --- rate limit (NFR-015) ----------------------------------------------------------------


def test_rate_limiter_sliding_window() -> None:
    clock = FakeClock(100.0)
    rl = RateLimiter(10, 60.0, clock)
    assert all(rl.hit("a") is None for _ in range(10))
    assert rl.hit("a") is not None
    assert rl.hit("b") is None  # per IP
    clock.t += 30
    assert rl.hit("a") is not None
    clock.t += 30.01
    assert rl.hit("a") is None


def test_eleventh_live_call_in_a_minute_gets_429() -> None:
    clock = FakeClock()
    backend = FakeBackend(cost=0.0)
    app, client = build(backend=backend, clock=clock)
    for k in range(10):
        r = client.post("/api/protect", json=LIVE_PROTECT)
        assert r.status_code == 200, k
        assert r.json()["live"] is True
    r = client.post("/api/protect", json=LIVE_PROTECT)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    assert len(backend.calls) == 10
    # Live compile and re-run share the same per-IP budget.
    assert client.post("/api/rules/compile", json={"text": "x", "live": True}).status_code == 429
    rerun = {"stage": "story", "live": True}
    assert client.post("/api/visits/v_c/rerun", json=rerun).status_code == 429
    voice = {"fixture_id": "vf_family_bin", "live": True}
    assert client.post("/api/voice/transcribe", json=voice).status_code == 429
    spoken = client.post("/api/voice/transcribe?live=true", content=_wav(2),
                         headers={"content-type": "audio/wav"})  # fmt: skip
    assert spoken.status_code == 429
    # Another IP is unaffected; the window slides.
    assert (
        client_for(app, "198.51.100.4").post("/api/protect", json=LIVE_PROTECT).status_code == 200
    )
    clock.t += 61
    assert client.post("/api/protect", json=LIVE_PROTECT).status_code == 200


def test_cached_requests_are_not_rate_limited() -> None:
    _, client = build(backend=ExplodingBackend())
    body = {"camera_id": "backyard", "point": {"x": 5, "y": 5}}
    for _ in range(15):
        assert client.post("/api/protect", json=body).status_code == 200


# --- spend cap and credit window (NFR-013, spec 11.6) -------------------------------------


def test_spend_cap() -> None:
    """Global error scenario: spend cap reached -> live disabled, cached continues."""
    backend = FakeBackend(cost=6.0)
    _, client = build(backend=backend)
    assert client.post("/api/protect", json=LIVE_PROTECT).json()["live"] is True
    assert client.post("/api/protect", json=LIVE_PROTECT).json()["live"] is True
    health = client.get("/api/health").json()
    assert health["spend_today_usd"] == pytest.approx(12.0)
    assert health["live"]["available"] is False
    assert health["live"]["reason"] == "spend_cap"
    body = client.post("/api/protect", json=LIVE_PROTECT).json()
    assert body["live"] is False
    assert body["notice"] == NOTICE_BUDGET
    assert len(backend.calls) == 2  # the third request never reached the model


def test_spend_resets_the_next_day() -> None:
    clock = FakeClock()
    _, client = build(backend=FakeBackend(cost=11.0), clock=clock)
    client.post("/api/protect", json=LIVE_PROTECT)
    assert client.get("/api/health").json()["live"]["available"] is False
    clock.t += 86400
    assert client.get("/api/health").json()["live"]["available"] is True


def test_credit_window_end_disables_live() -> None:
    clock = FakeClock()
    ended = datetime.fromtimestamp(clock.t, tz=UTC) - timedelta(hours=1)
    backend = FakeBackend()
    _, client = build(make_settings(credit_window_end=ended), backend=backend, clock=clock)
    body = client.post("/api/protect", json=LIVE_PROTECT).json()
    assert body["live"] is False
    assert body["notice"] == NOTICE_BUDGET  # one notice everywhere (spec 11.6 item 6)
    assert client.get("/api/health").json()["live"]["reason"] == "credit_window_ended"
    assert backend.calls == []
    _, paid = build(make_settings(credit_window_end=ended, allow_paid=True), clock=clock)
    assert paid.post("/api/protect", json=LIVE_PROTECT).json()["live"] is True


def test_no_key_means_cached_with_notice() -> None:
    backend = FakeBackend()
    _, client = build(make_settings(MODEL_API_KEY=""), backend=backend)
    body = client.post("/api/protect", json=LIVE_PROTECT).json()
    assert body["live"] is False
    assert "not configured" in body["notice"]
    assert backend.calls == []


# --- size limits (NFR-015) ----------------------------------------------------------------


def test_oversized_json_gets_413() -> None:
    _, client = build(backend=ExplodingBackend())
    big = json.dumps({"text": "x" * (65 * 1024)})
    r = client.post("/api/rules/compile", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    r = client.post("/api/protect", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_oversized_audio_gets_413() -> None:
    """NFR-015: voice audio over 2 MB is refused before it is read in full."""
    _, client = build(backend=ExplodingBackend())
    blob = b"RIFF" + b"\x00" * (2 * 1024 * 1024 - 3)
    r = client.post("/api/voice/transcribe", content=blob, headers={"content-type": "audio/wav"})
    assert r.status_code == 413
    r = client.post("/api/voice/transcribe?live=true", content=blob,
                    headers={"content-type": "audio/wav"})  # fmt: skip
    assert r.status_code == 413


def test_audio_over_30_seconds_gets_413() -> None:
    """A 31 s 16 kHz mono WAV is under 2 MB (about 0.99 MB) but over the 30 s limit."""
    backend = FakeBackend()
    _, client = build(backend=backend)
    wav = _wav(31)
    assert len(wav) < 2 * 1024 * 1024
    r = client.post("/api/voice/transcribe?live=true", content=wav,
                    headers={"content-type": "audio/wav"})  # fmt: skip
    assert r.status_code == 413
    assert backend.calls == []
    ok = client.post("/api/voice/transcribe?live=true", content=_wav(30),
                     headers={"content-type": "audio/wav"})  # fmt: skip
    assert ok.status_code == 200
    assert backend.calls == ["transcribe"]


def test_audio_must_be_16khz_mono_pcm_wav() -> None:
    _, client = build(backend=ExplodingBackend())
    r = client.post("/api/voice/transcribe", content=_wav(3, rate=8000),
                    headers={"content-type": "audio/wav"})  # fmt: skip
    assert r.status_code == 415
    r = client.post("/api/voice/transcribe", content=b"\x1a\x45\xdf\xa3" + b"\x00" * 100,
                    headers={"content-type": "audio/webm"})  # fmt: skip
    assert r.status_code == 415


def test_compile_takes_text_only() -> None:
    """Transcribe and compile are separate calls, so the transcript stays editable (FR-022)."""
    _, client = build(backend=ExplodingBackend())
    r = client.post("/api/rules/compile", content=_wav(3), headers={"content-type": "audio/wav"})
    assert r.status_code == 415


# --- judging cap: $25 total, $5 per PT day, VIGIL_JUDGING_END (FR-043, NFR-037) ----------


def test_judging_cap_total_refuses_then_serves_cached() -> None:
    clock = FakeClock()
    backend = FakeBackend(cost=10.0)
    _, client = build(_judging(clock, judging_daily_cap_usd=100.0), backend=backend, clock=clock)
    for _ in range(3):  # $10 + $10 + $10: the third crosses $25 only once it is spent
        assert client.post("/api/protect", json=LIVE_PROTECT).json()["live"] is True
        clock.t += 86400  # a new PT day each time, so only the total can bind
    health = client.get("/api/health").json()
    assert health["judging_cap_remaining_usd"] == 0
    assert health["live"]["reason"] == "judging_cap"
    body = client.post("/api/protect", json=_preset_live(client)).json()
    assert body["live"] is False
    assert body["notice"] == NOTICE_BUDGET
    assert body["result"]["object"]["id"] == "po_bin"  # the recorded result, buttons still work
    assert len(backend.calls) == 3


def test_judging_cap_refuses_a_call_that_would_cross_25() -> None:
    clock = FakeClock()
    backend = FakeBackend(cost=24.999)
    _, client = build(_judging(clock, judging_daily_cap_usd=100.0), backend=backend, clock=clock)
    assert client.post("/api/protect", json=LIVE_PROTECT).json()["live"] is True
    clock.t += 86400
    body = client.post("/api/protect", json=LIVE_PROTECT).json()  # priced at $0.0025
    assert body["live"] is False
    assert body["notice"] == NOTICE_BUDGET
    assert len(backend.calls) == 1


def test_judging_daily_cap_is_5_per_pt_calendar_day() -> None:
    # Nov 5 23:30 PT is Nov 6 07:30 UTC: a UTC day would not reset at PT midnight.
    clock = FakeClock(_pt("2026-11-05T23:30:00"))
    backend = FakeBackend(cost=3.0)
    _, client = build(_judging(clock), backend=backend, clock=clock)
    assert client.post("/api/protect", json=LIVE_PROTECT).json()["live"] is True  # $3
    assert client.post("/api/protect", json=LIVE_PROTECT).json()["live"] is True  # $6
    body = client.post("/api/protect", json=LIVE_PROTECT).json()
    assert body["live"] is False
    assert body["notice"] == NOTICE_BUDGET
    assert client.get("/api/health").json()["live"]["reason"] == "judging_daily_cap"
    clock.t = _pt("2026-11-06T00:10:00")
    assert client.post("/api/protect", json=LIVE_PROTECT).json()["live"] is True
    assert len(backend.calls) == 3


def test_no_paid_call_after_judging_end() -> None:
    clock = FakeClock()
    now = datetime.fromtimestamp(clock.t, tz=UTC)
    backend = FakeBackend()
    settings = _judging(clock, judging_end=now - timedelta(minutes=1))
    _, client = build(settings, backend=backend, clock=clock)
    body = client.post("/api/protect", json=LIVE_PROTECT).json()
    assert body["live"] is False
    assert body["notice"] == NOTICE_BUDGET
    assert client.get("/api/health").json()["live"]["reason"] == "judging_ended"
    assert backend.calls == []


def test_judging_cap_applies_to_every_live_endpoint() -> None:
    """protect, transcribe, compile and re-run all degrade to cached with the same notice."""
    clock = FakeClock()
    backend = FakeBackend(cost=5.0)
    _, client = build(_judging(clock), backend=backend, clock=clock)
    assert client.post("/api/protect", json=LIVE_PROTECT).json()["live"] is True  # day's $5
    backend.calls.clear()
    assert client.post("/api/protect", json=LIVE_PROTECT).json()["notice"] == NOTICE_BUDGET
    fixture = client.post("/api/voice/transcribe",
                          json={"fixture_id": "vf_family_bin", "live": True}).json()  # fmt: skip
    assert fixture["notice"] == NOTICE_BUDGET
    assert fixture["result"]["transcript"].startswith("Tell me if anyone except family")
    spoken = _transcribe_live(client)
    assert spoken["live"] is False
    assert spoken["notice"].startswith(NOTICE_BUDGET)
    assert spoken["result"]["transcript"] == ""
    text = fixture["result"]["transcript"]
    compiled = client.post("/api/rules/compile", json={"text": text, "live": True}).json()
    assert compiled["live"] is False
    assert compiled["notice"] == NOTICE_BUDGET
    assert compiled["result"]["rule"]["applies_to"] == "non_household"
    rerun = _rerun_live(client)
    assert rerun["live"] is False
    assert rerun["notice"] == NOTICE_BUDGET
    assert backend.calls == []


def test_paid_spend_is_tagged_and_counted_apart_from_credit() -> None:
    clock = FakeClock()
    _, credit = build(backend=FakeBackend(cost=1.0), clock=clock)
    credit.post("/api/protect", json=LIVE_PROTECT)
    rows = [c for c in credit.get("/api/calls").json()["calls"] if not c["cached"]]
    assert [c["funding"] for c in rows] == ["credit"]
    health = credit.get("/api/health").json()
    assert health["phase"] == "credit"
    assert health["judging_cap_remaining_usd"] == 25
    _, paid = build(_judging(clock), backend=FakeBackend(cost=1.0), clock=clock)
    paid.post("/api/protect", json=LIVE_PROTECT)
    rows = [c for c in paid.get("/api/calls").json()["calls"] if not c["cached"]]
    assert [c["funding"] for c in rows] == ["paid"]
    health = paid.get("/api/health").json()
    assert health["phase"] == "judging"
    assert health["judging_cap_usd"] == 25
    assert health["judging_daily_cap_usd"] == 5
    assert health["judging_cap_remaining_usd"] == pytest.approx(24.0)
    assert health["judging_today_remaining_usd"] == pytest.approx(4.0)
    assert health["credit_cap_usd"] == 140


def _preset_live(client) -> dict:
    p = client.get("/api/presets").json()["protect"][0]
    return {"camera_id": p["camera_id"], "point": {"x": p["point"][0], "y": p["point"][1]},
            "live": True}  # fmt: skip


def test_live_failure_notice_names_the_recorded_date() -> None:
    _, client = build(backend=FakeBackend(error=RuntimeError("timeout after 20 s")))
    body = client.post("/api/protect", json=_preset_live(client)).json()
    assert body["notice"] == "Live call failed; recorded result from Nov 2, 2026 shown"


# --- model allowlist (NFR-004) ------------------------------------------------------------


def test_no_contributor_model_id() -> None:
    with pytest.raises(ModelNotAllowedError):
        check_model_allowed("muse-spark-1.3" + CONTRIBUTOR)
    with pytest.raises(ModelNotAllowedError):
        check_model_allowed("muse-image-1.0")
    assert check_model_allowed("sam-3.1") == "sam-3.1"


def test_contributor_id_from_a_backend_is_never_accepted() -> None:
    backend = FakeBackend(model="sam-3.1" + CONTRIBUTOR, cost=1.0)
    _, client = build(backend=backend)
    body = client.post("/api/protect", json=LIVE_PROTECT).json()
    assert body["live"] is False
    assert body["notice"].startswith("Live call failed")
    calls = client.get("/api/calls").json()["calls"]
    assert all(CONTRIBUTOR not in c["model"] for c in calls)
    assert client.get("/api/health").json()["spend_today_usd"] == 0


def test_request_cannot_choose_a_model() -> None:
    _, client = build(backend=ExplodingBackend())
    body = {**LIVE_PROTECT, "model": "sam-3.1" + CONTRIBUTOR}
    assert client.post("/api/protect", json=body).status_code == 422
    body = {"text": "x", "model": "muse-spark-1.3" + CONTRIBUTOR}
    assert client.post("/api/rules/compile", json=body).status_code == 422


# --- the key is never served (NFR-014) ----------------------------------------------------


def test_key_never_appears_in_any_served_file_or_response() -> None:
    backend = FakeBackend(error=RuntimeError(f"401 for Bearer {SENTINEL_KEY}"))
    _, client = build(make_settings(), backend=backend)
    seen: list[str] = []
    for path in ("/api/health", "/api/scenarios", "/api/scenarios/A", "/api/scenarios/B",
                 "/api/scenarios/C", "/api/visits/v_a", "/api/visits/v_b", "/api/visits/v_c",
                 "/api/visits/v_c/positions", "/api/twin", "/api/calls", "/api/eval",
                 "/api/presets", "/api/voice/fixtures", "/api/windows", "/",
                 "/media/ground.glb"):  # fmt: skip
        r = client.get(path)
        assert r.status_code == 200, path
        seen.append(r.text if "glb" not in path else r.content.decode("latin-1"))
    for f in sorted((REPO_ROOT / "web").rglob("*")):
        if f.is_file():
            r = client.get("/" + f.relative_to(REPO_ROOT / "web").as_posix())
            assert r.status_code in (200, 404)
            seen.append(r.content.decode("utf-8", errors="replace"))
    r = client.post("/api/protect", json=LIVE_PROTECT)
    seen.append(r.text)
    job = client.post("/api/visits/v_c/rerun", json={"stage": "story", "live": True}).json()
    seen.append(client.get(f"/api/jobs/{job['job_id']}").text)
    seen.append(client.post("/api/rules/compile", json={"text": "x", "live": True}).text)
    assert "Bearer ***" in r.text
    for text in seen:
        assert SENTINEL_KEY not in text


# --- LAN-only routes (spec 9.6) -----------------------------------------------------------


def test_live_routes_reject_public_clients() -> None:
    pair = {"camera_id": "side_left", "pixel": [640, 500], "world": [6.0, 0.0, 3.0]}
    app, public = build(make_settings(mode="edge"), ip="203.0.113.9")
    assert public.get("/api/live/stream").status_code == 403
    assert public.post("/api/spatial/pairs", json=pair).status_code == 403
    lan = client_for(app, "192.168.1.20")
    r = lan.post("/api/spatial/pairs", json=pair)
    assert r.status_code == 200
    assert r.json()["pairs"] == 1
    assert r.json()["needed"] == 6
    spoofed = lan.post("/api/spatial/pairs", json=pair, headers={"x-forwarded-for": "8.8.8.8"})
    assert spoofed.status_code == 403
    # The hosted sandbox never serves LAN routes, even to a private address.
    _, sandbox = build(make_settings(mode="sandbox"), ip="192.168.1.20")
    assert sandbox.post("/api/spatial/pairs", json=pair).status_code == 403
    assert sandbox.get("/api/live/stream").status_code == 403


def test_owner_routes_are_lan_only() -> None:
    """Windows (POST/DELETE), check-in and SAM landmarks: 403 from a public IP or the sandbox."""
    window = {"start": "2099-01-01T10:00:00-08:00", "end": "2099-01-01T12:00:00-08:00",
              "cameras": ["front"], "label": "plumber"}  # fmt: skip
    _, public = build(make_settings(mode="edge"), ip="203.0.113.9")
    _, sandbox = build(make_settings(mode="sandbox"), ip="192.168.1.20")
    for client in (public, sandbox):
        assert client.post("/api/windows", json=window).status_code == 403
        assert client.delete("/api/windows/w3").status_code == 403
        assert client.post("/api/checkin").status_code == 403
        assert client.post("/api/spatial/landmarks", json={"camera_id": "front"}).status_code == 403
        # Reading the windows and leaving feedback are open to everyone (spec 9.6).
        assert client.get("/api/windows").status_code == 200
        assert client.post("/api/visits/v_b/feedback", json={"kind": "expected"}).status_code == 200
    _, spoofed = build(make_settings(mode="edge"), ip="192.168.1.20")
    r = spoofed.post("/api/checkin", headers={"x-forwarded-for": "8.8.8.8"})
    assert r.status_code == 403


def test_live_stream_sends_events_to_lan_clients() -> None:
    app, lan = build(make_settings(mode="edge"), ip="10.0.0.5")
    app.state.live_hub.publish("camera_ai", {"camera_id": "backyard", "kind": "person"})
    with lan.stream("GET", "/api/live/stream?max_events=2") as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert "event: hello" in text
    assert "event: camera_ai" in text
    assert "backyard" in text


def test_is_lan_request_helper() -> None:
    class Req:
        def __init__(self, host: str, headers: dict[str, str] | None = None) -> None:
            self.client = type("C", (), {"host": host})()
            self.headers = headers or {}

    assert is_lan_request(Req("127.0.0.1"))
    assert is_lan_request(Req("10.1.2.3"))
    assert is_lan_request(Req("::1"))
    assert not is_lan_request(Req("93.184.216.34"))
    assert not is_lan_request(Req("testclient"))
    assert not is_lan_request(Req("192.168.0.2", {"forwarded": "for=93.184.216.34"}))
