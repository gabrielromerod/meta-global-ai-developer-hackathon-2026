"""Sandbox API over the demo bundle (spec 9.6; FR-017, FR-019, FR-021, FR-023, FR-026, FR-027).

No test here touches the network: live paths go through injected fakes, and respx blocks
every httpx request as a safety net. The helpers at the top are shared with test_guards.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from vigil.api.app import create_app
from vigil.api.backend import LiveResult
from vigil.models import ModelCall, VisitLedger
from vigil.settings import Settings

SENTINEL_KEY = "sk-vigil-sentinel-7f3a9c2e1d"


def make_settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {"mode": "sandbox", "MODEL_API_KEY": SENTINEL_KEY}
    base.update(kw)
    return Settings(**base)


class FakeClock:
    def __init__(self, t: float = 1_793_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeBackend:
    """Records calls; returns a canned result with a configurable cost and model ID."""

    def __init__(
        self, cost: float = 0.0025, model: str | None = None, error: Exception | None = None
    ) -> None:
        self.cost = cost
        self.model = model
        self.error = error
        self.calls: list[str] = []

    def _call(self, purpose: str, model: str) -> list[ModelCall]:
        return [
            ModelCall.model_construct(
                id=f"call_live_{len(self.calls):03d}",
                model=self.model or model,
                purpose=purpose,
                visit_id=None,
                req_hash="fake",
                latency_ms=1234,
                cost_usd=self.cost,
                cached=False,
                ok=True,
            )
        ]

    def _start(self, name: str) -> None:
        self.calls.append(name)
        if self.error is not None:
            raise self.error

    def protect(self, camera_id, frame_ts, x, y, label) -> LiveResult:
        self._start("protect")
        return LiveResult.model_construct(
            payload={
                "mask": {
                    "bbox": {"x1": x - 20, "y1": y - 30, "x2": x + 20, "y2": y + 30},
                    "outline": [[x - 20, y - 30], [x + 20, y - 30], [x + 20, y + 30]],
                    "score": 0.93,
                }
            },
            calls=self._call("protect", "sam-3.1"),
        )

    def compile_rule(self, text, catalog) -> LiveResult:
        self._start("compile")
        return LiveResult.model_construct(
            payload={
                "rule": {
                    "id": "r20",
                    "name": "Side gate after 11 PM",
                    "target": {"kind": "protected_object", "id": "po_side_gate"},
                    "trigger": "touch",
                    "active": {"start": "23:00", "end": "06:00"},
                    "severity": "needs_attention",
                    "state": "draft",
                },
                "limits_note": ["Vigil doesn't identify people, so this applies to anyone."],
            },
            calls=self._call("rule_compile", "muse-spark-1.3"),
        )

    def transcribe(self, audio, content_type) -> LiveResult:
        self._start("transcribe")
        self.audio = audio
        return LiveResult.model_construct(
            payload={"transcript": "tell me if anyone touches the bin after 9 PM"},
            calls=self._call("transcribe", "muse-voice-transcribe-1.0"),
        )

    def rerun_story(self, ledger: VisitLedger) -> LiveResult:
        self._start("rerun")
        sentences = [
            {"text": s.text, "event_ids": s.event_ids, "source": s.source, "gap_id": s.gap_id}
            for s in ledger.visit.story
        ]
        return LiveResult.model_construct(
            payload={
                "story": sentences,
                "proposal": "normal",
                "validation": {"passed": True, "attempt": 1, "failures": []},
            },
            calls=self._call("story", "muse-wonder-1.0"),
        )


class ExplodingBackend(FakeBackend):
    """Fails the test if any live path is taken (cached flows must never call it)."""

    def _start(self, name: str) -> None:
        raise AssertionError(f"live backend called for {name} in a cached flow")


def client_for(app, ip: str = "203.0.113.7") -> TestClient:
    return TestClient(app, client=(ip, 50000))


def build(
    settings: Settings | None = None,
    backend: Any = None,
    clock: Any = None,
    ip: str = "203.0.113.7",
    **app_kw: Any,
):
    app = create_app(
        settings or make_settings(),
        live_backend=backend if backend is not None else FakeBackend(),
        clock=clock or FakeClock(),
        **app_kw,
    )
    return app, client_for(app, ip)


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    with respx.mock(assert_all_called=False):
        yield


@pytest.fixture
def api() -> TestClient:
    return build(backend=ExplodingBackend())[1]


def _preset_body(client: TestClient, live: bool = False) -> dict[str, Any]:
    p = client.get("/api/presets").json()["protect"][0]
    return {"camera_id": p["camera_id"], "point": {"x": p["point"][0], "y": p["point"][1]},
            "live": live}  # fmt: skip


# --- read routes --------------------------------------------------------------------------


def test_health_reports_mode_spend_and_cap(api: TestClient) -> None:
    body = api.get("/api/health").json()
    assert body["mode"] == "sandbox"
    assert body["spend_today_usd"] == 0
    assert body["daily_cap_usd"] == 10
    assert body["live"]["available"] is True
    assert body["synthetic"] is True
    # Credit cap and judging cap remaining (spec 9.6, NFR-037).
    assert body["credit_cap_usd"] == 140
    assert body["judging_cap_usd"] == 25
    assert body["judging_daily_cap_usd"] == 5
    assert body["judging_cap_remaining_usd"] == 25
    assert body["phase"] == "credit"
    assert "judging_end" in body


def test_scenarios_list_with_evening_summary(api: TestClient) -> None:
    body = api.get("/api/scenarios").json()
    assert [s["id"] for s in body["scenarios"]] == ["A", "A-prime", "B", "B-prime", "C"]
    assert body["summary"]["visits"] == 5
    assert body["summary"]["alerts"] == 1
    assert body["summary"]["motion_triggers"] > 3
    c = body["scenarios"][4]
    assert c["visits"][0]["verdict"] == "needs_attention"
    assert c["visits"][0]["first_sentence"]


def test_scenario_detail_has_cameras_and_overlays(api: TestClient) -> None:
    body = api.get("/api/scenarios/C").json()
    assert {c["id"] for c in body["cameras"]} == {"front", "side_left", "side_right", "backyard"}
    side = next(c for c in body["cameras"] if c["id"] == "side_left")
    assert side["pose"]["hfov_deg"] > 0
    assert body["overlays"]["side_left"]
    frame = next(iter(body["overlays"]["side_left"].values()))["frames"][0]
    assert len(frame["box"]) == 4
    assert len(frame["outline"]) >= 3
    assert api.get("/api/scenarios/Z").status_code == 404


def test_visit_card_c_has_citations_badges_gap_and_trace(api: TestClient) -> None:
    body = api.get("/api/visits/v_c").json()
    assert body["verdict"] == "needs_attention"
    assert body["verdict_label"] == "Needs your attention"
    for sentence in body["sentences"]:
        assert sentence["citations"], sentence
        assert sentence["badge"]["label"]
    wonder = [s for s in body["sentences"] if s["source"] == "wonder"]
    assert wonder
    assert all(s["badge"]["model"] == "muse-wonder-1.0" for s in wonder)
    assert all(s["badge"]["call_id"].startswith("call_") for s in wonder)
    code = [s for s in body["sentences"] if s["source"] == "code"]
    assert code[0]["gap_id"] == "g4"
    gap = body["gaps"][0]
    assert gap["label"] == "Not observed · 41 s"
    assert gap["region_name"] == "behind the shed"
    assert body["rule_hits"][0]["rule_id"] == "r7"
    trace = body["trace"]
    assert trace["triage"]["forced"] is True
    assert [d["passed"] for d in trace["drafts"]] == [False, True]
    assert trace["drafts"][0]["failures"]
    assert trace["verdict_inputs"]["result"] == "needs_attention"
    assert {c["camera_id"] for c in trace["calibration"]} == {"front", "side_left"}
    ledger = api.get("/api/calls", params={"visit_id": "v_c"}).json()
    assert body["telemetry"]["totals"]["cost_usd"] == pytest.approx(ledger["totals"]["cost_usd"])
    assert body["telemetry"]["totals"]["count"] == len(ledger["calls"])


def test_visit_card_b_shows_the_activated_watch(api: TestClient) -> None:
    body = api.get("/api/visits/v_b").json()
    assert body["verdict"] == "noteworthy"
    assert body["watches"][0]["notice"] == "Now watching: package on porch"


def test_visit_card_a_is_templated(api: TestClient) -> None:
    body = api.get("/api/visits/v_a").json()
    assert body["verdict"] == "normal"
    assert body["escalated"] is False
    assert all(s["badge"]["kind"] == "template" for s in body["sentences"])


def test_unknown_visit_is_404(api: TestClient) -> None:
    assert api.get("/api/visits/nope").status_code == 404
    assert api.get("/api/visits/nope/positions").status_code == 404


def test_positions_encode_methods_and_never_enter_the_gap(api: TestClient) -> None:
    body = api.get("/api/visits/v_c/positions").json()
    gap = body["gaps"][0]
    assert gap["label"] == "Not observed · 41 s"
    assert gap["from"] is not None
    assert gap["to"] is not None
    for p in body["positions"]:
        assert not (gap["t0"] < p["t"] < gap["t1"])
        assert p["r95"] > 0
    methods = {p["method"] for p in body["positions"]}
    assert {"footpoint", "fused", "height_prior"} <= methods
    # Observed path segments break at the gap: no segment spans it.
    for seg in body["paths"]:
        ts = [pt[2] for pt in seg]
        assert not (min(ts) <= gap["t0"] and max(ts) >= gap["t1"])


def test_twin_has_cones_coverage_and_blind_region(api: TestClient) -> None:
    body = api.get("/api/twin").json()
    assert len(body["cameras"]) == 4
    assert all("position" in c and "look_at" in c for c in body["cameras"])
    assert body["blind_regions"][0]["id"] == "shed_back"
    assert len(body["coverage"]) == 4
    glb = api.get(body["glb_url"])
    assert glb.status_code == 200
    assert glb.content[:4] == b"glTF"


def test_calls_ledger_and_totals(api: TestClient) -> None:
    body = api.get("/api/calls").json()
    assert body["totals"]["count"] == len(body["calls"])
    assert {c["model"] for c in body["calls"]} <= {"sam-3.1", "muse-spark-1.3", "muse-wonder-1.0"}
    assert body["totals"]["cost_usd"] == pytest.approx(sum(c["cost_usd"] for c in body["calls"]))


def test_eval_is_served(api: TestClient) -> None:
    body = api.get("/api/eval").json()
    assert "targets" in body or "metrics" in body


def test_web_shell_is_served(api: TestClient) -> None:
    page = api.get("/")
    assert page.status_code == 200
    assert "Vigil" in page.text
    assert api.get("/app.js").status_code == 200
    assert api.get("/twin/vendor/three/build/three.module.min.js").status_code == 200


def test_calibrate_page_is_hidden_in_the_sandbox(api: TestClient) -> None:
    assert api.get("/calibrate/index.html").status_code == 404
    _, lan = build(make_settings(mode="edge"), ip="192.168.1.20")
    assert lan.get("/calibrate/index.html").status_code == 200


def test_create_app_factory_without_arguments() -> None:
    from vigil.api.app import create_app as factory

    app = factory()
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200


# --- live buttons: cached by default, live with guards, fallback with notice ---------------


def test_protect_cached_preset(api: TestClient) -> None:
    body = api.post("/api/protect", json=_preset_body(api)).json()
    assert body["live"] is False
    assert body["result"]["object"]["id"] == "po_bin"
    assert body["result"]["outline"]
    assert body["telemetry"]["cached"] is True
    assert body["telemetry"]["model"] == "sam-3.1"
    assert body["telemetry"]["call_id"]


def test_protect_cached_far_from_presets_suggests_points(api: TestClient) -> None:
    resp = api.post("/api/protect", json={"camera_id": "backyard", "point": {"x": 5, "y": 5}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] is None
    assert "Try another point" in data["notice"]
    assert len(data["presets"]) >= 2


def test_protect_rejects_unknown_camera_and_bad_point(api: TestClient) -> None:
    bad_cam = {"camera_id": "garage", "point": {"x": 5, "y": 5}}
    assert api.post("/api/protect", json=bad_cam).status_code == 422
    bad_pt = {"camera_id": "front", "point": {"x": -5, "y": 5}}
    assert api.post("/api/protect", json=bad_pt).status_code == 422


def test_protect_live_with_backend_records_call_and_spend() -> None:
    backend = FakeBackend(cost=0.0025)
    _, client = build(backend=backend)
    body = client.post(
        "/api/protect",
        json={"camera_id": "side_right", "point": {"x": 640, "y": 500}, "label": "bin",
              "live": True},
    ).json()  # fmt: skip
    assert backend.calls == ["protect"]
    assert body["live"] is True
    assert body["notice"] is None
    assert body["telemetry"]["cached"] is False
    assert body["telemetry"]["latency_ms"] == 1234
    assert client.get("/api/health").json()["spend_today_usd"] == pytest.approx(0.0025)
    calls = client.get("/api/calls").json()["calls"]
    assert any(c["id"] == "call_live_001" and c["cached"] is False for c in calls)
    twin = client.get("/api/twin").json()
    assert any(o["label"] == "bin" for o in twin["protected_objects"])


def test_real_protect_does_not_invent_a_footprint_from_public_diagram():
    backend = FakeBackend(cost=0.0025)
    app, client = build(backend=backend)
    app.state.bundle.manifest["synthetic"] = False
    for camera in app.state.bundle.twin["cameras"]:
        camera["placement_measured"] = False
    body = client.post(
        "/api/protect",
        json={
            "camera_id": "side_right",
            "point": {"x": 640, "y": 500},
            "label": "object",
            "live": True,
        },
    ).json()
    assert body["result"]["object"]["footprint"] is None


def test_live_failure_falls_back_to_cached_with_visible_notice() -> None:
    backend = FakeBackend(error=RuntimeError("upstream 503"))
    _, client = build(backend=backend)
    body = client.post("/api/protect", json=_preset_body(client, live=True)).json()
    assert body["live"] is False
    assert body["notice"] == "Live call failed; recorded result from Nov 2, 2026 shown"
    assert body["result"]["object"]["id"] == "po_bin"
    assert body["error"] == "RuntimeError: upstream 503"


def test_compile_cached_then_confirm(api: TestClient) -> None:
    body = api.post(
        "/api/rules/compile", json={"text": "Tell me if anyone touches the bin after 9 PM"}
    ).json()
    assert body["live"] is False
    rule = body["result"]["rule"]
    assert rule["id"] == "r8"
    assert rule["state"] == "draft"
    assert rule["applies_to"] == "anyone"
    assert body["result"]["applies_label"] == "Applies to everyone, including household members."
    assert "does not identify anyone" in body["result"]["basis_note"]
    confirmed = api.post("/api/rules/r8/confirm").json()
    assert confirmed["state"] == "active"
    assert api.post("/api/rules/nope/confirm").status_code == 404


def test_compile_unknown_text_shows_recorded_example_with_notice(api: TestClient) -> None:
    body = api.post("/api/rules/compile", json={"text": "ping me when the cat sits"}).json()
    assert body["live"] is False
    assert "recorded" in body["notice"]
    assert body["result"]["rule"]


def test_compile_live_with_backend() -> None:
    backend = FakeBackend()
    _, client = build(backend=backend)
    body = client.post(
        "/api/rules/compile", json={"text": "side gate after 11", "live": True}
    ).json()
    assert backend.calls == ["compile"]
    assert body["live"] is True
    assert body["result"]["rule"]["id"] == "r20"
    assert client.post("/api/rules/r20/confirm").json()["state"] == "active"


def test_compile_live_rejects_unknown_target() -> None:
    class Unknown(FakeBackend):
        def compile_rule(self, text, catalog):
            res = super().compile_rule(text, catalog)
            res.payload["rule"]["target"]["id"] = "po_trampoline"
            return res

    _, client = build(backend=Unknown())
    body = client.post("/api/rules/compile", json={"text": "trampoline", "live": True}).json()
    assert body["result"]["question"].startswith("Which object do you mean?")
    assert "side gate" in body["result"]["question"]


def test_rerun_job_cached(api: TestClient) -> None:
    job = api.post("/api/visits/v_c/rerun", json={"stage": "story"}).json()
    result = api.get(f"/api/jobs/{job['job_id']}").json()
    assert result["status"] == "done"
    out = result["result"]
    assert out["live"] is False
    assert out["result"]["verdict"] == "needs_attention"
    assert out["result"]["story"]
    assert api.get("/api/jobs/nope").status_code == 404
    assert api.post("/api/visits/nope/rerun", json={"stage": "story"}).status_code == 404
    assert api.post("/api/visits/v_c/rerun", json={"stage": "tracks"}).status_code == 422


def test_rerun_job_live_keeps_the_verdict() -> None:
    backend = FakeBackend()
    _, client = build(backend=backend)
    job = client.post("/api/visits/v_c/rerun", json={"stage": "story", "live": True}).json()
    out = client.get(f"/api/jobs/{job['job_id']}").json()["result"]
    assert backend.calls == ["rerun"]
    assert out["live"] is True
    assert out["result"]["verdict"] == "needs_attention"
    assert out["result"]["validation"]["passed"] is True


def test_invalid_key_every_cached_flow_still_works() -> None:
    """NFR-009: MODEL_API_KEY=invalid; cached flows never touch the live backend."""
    _, client = build(make_settings(MODEL_API_KEY="invalid"), backend=ExplodingBackend())
    for path in (
        "/api/health",
        "/api/scenarios",
        "/api/scenarios/C",
        "/api/visits/v_c",
        "/api/visits/v_c/positions",
        "/api/twin",
        "/api/calls",
        "/api/eval",
    ):
        assert client.get(path).status_code == 200, path  # fmt: skip
    assert client.post("/api/protect", json=_preset_body(client)).status_code == 200
    assert client.post("/api/rules/compile", json={"text": "bin after 9"}).status_code == 200
    job = client.post("/api/visits/v_b/rerun", json={"stage": "story"}).json()
    assert client.get(f"/api/jobs/{job['job_id']}").json()["status"] == "done"


def test_default_backend_degrades_to_cached() -> None:
    """The real adapter is wired in but cannot run live here: it degrades, never blanks."""
    app = create_app(make_settings(MODEL_API_KEY="invalid"), clock=FakeClock())
    client = client_for(app)
    body = client.post("/api/protect", json=_preset_body(client, live=True)).json()
    assert body["live"] is False
    assert body["notice"].startswith("Live call failed")
    assert body["result"]["object"]


# --- roles in the cards: A′ vs C contrast, B′ window, measured r95 (FR-044, FR-029, FR-039) ---


def test_card_c_trace_shows_role_basis_per_subject(api: TestClient) -> None:
    body = api.get("/api/visits/v_c").json()
    (subject,) = body["trace"]["subjects"]
    assert subject["actor_role"] == "external_visitor"
    assert subject["role_basis"] == "perimeter:side_alley"
    assert subject["role_label"]
    touch = next(e for e in body["events"] if e["type"] == "touch")
    assert touch["actor_role"] == "external_visitor"
    assert touch["subject_id"] == subject["id"]
    assert body["trace"]["rules_excluded"] == []
    r7 = next(r for r in body["rule_hits"] if r["rule_id"] == "r7")
    assert r7["applies_to"] == "non_household"


def test_card_a_prime_shows_r7_excluded_by_applies_to(api: TestClient) -> None:
    body = api.get("/api/visits/v_ap").json()
    assert body["verdict"] == "normal"
    assert body["escalated"] is False
    assert body["rule_hits"] == []
    (subject,) = body["trace"]["subjects"]
    assert subject["actor_role"] == "household_insider"
    assert subject["role_basis"] == "egress:front_door_egress"
    (excluded,) = body["trace"]["rules_excluded"]
    assert excluded["rule_id"] == "r7"
    assert excluded["applies_to"] == "non_household"
    assert excluded["actor_role"] == "household_insider"
    assert "r7" in excluded["reason"]
    assert "non-household" in excluded["reason"]
    # Same gate, after dark, inside r7's window: the opposite outcome is decided by origin.
    c = api.get("/api/visits/v_c").json()
    assert c["verdict"] == "needs_attention"


def test_card_b_prime_names_the_expected_window(api: TestClient) -> None:
    body = api.get("/api/visits/v_bp").json()
    (subject,) = body["trace"]["subjects"]
    assert subject["role_basis"] == "window:w3"
    assert subject["actor_role"] == "expected_visitor"
    (window,) = body["expected_windows"]
    assert window["id"] == "w3"
    assert window["label"] == "deliveries"


def test_position_labels_use_the_measured_r95(api: TestClient) -> None:
    for vid in ("v_c", "v_ap", "v_b"):
        for p in api.get(f"/api/visits/{vid}/positions").json()["positions"]:
            assert f"±{p['r95']:.1f} m" in p["label"], p
            if p["method"] == "footpoint":
                assert p["label"].startswith("Estimated ±")


# --- voice: fixtures and transcribe (FR-022, NFR-002, NFR-015) ----------------------------


def _wav16(seconds: float = 2.0) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x01\x00" * int(seconds * 16000))
    return buf.getvalue()


def _fixture_files(tmp_path, wav: bytes | None = None):
    import hashlib
    import json

    voice = tmp_path / "voice"
    voice.mkdir()
    fixtures = []
    if wav is not None:
        (voice / "vf_family_bin.wav").write_bytes(wav)
        fixtures.append({"id": "vf_family_bin", "file": "vf_family_bin.wav",
                         "sha256": hashlib.sha256(wav).hexdigest(),
                         "transcript": "Tell me if anyone except family touches the bin after "
                                       "9 PM"})  # fmt: skip
    cfg = tmp_path / "audio_fixtures.json"
    cfg.write_text(json.dumps({"note": "test", "fixtures": fixtures}), encoding="utf-8")
    return {"voice_dir": voice, "audio_fixtures_path": cfg}


def test_voice_fixtures_lists_three_with_cached_transcripts(api: TestClient) -> None:
    body = api.get("/api/voice/fixtures").json()
    ids = [f["id"] for f in body["fixtures"]]
    assert ids == ["vf_family_bin", "vf_strangers_gate", "vf_named_gate"]
    for f in body["fixtures"]:
        assert f["transcript"]
        assert f["wav_url"] is None  # no consented WAV committed until T-07a
        assert f["recorded"] is False
        assert f["label"]
    assert "T-07a" in body["note"]


def test_voice_fixture_wav_url_when_the_consented_file_is_listed(tmp_path) -> None:
    wav = _wav16()
    _, client = build(**_fixture_files(tmp_path, wav))
    body = client.get("/api/voice/fixtures").json()
    first = body["fixtures"][0]
    assert first["recorded"] is True
    audio = client.get(first["wav_url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.content == wav
    assert body["fixtures"][1]["wav_url"] is None
    assert client.get("/api/voice/fixtures/vf_named_gate/audio").status_code == 404


def test_voice_fixture_with_tampered_audio_is_not_served(tmp_path) -> None:
    files = _fixture_files(tmp_path, _wav16())
    (files["voice_dir"] / "vf_family_bin.wav").write_bytes(_wav16(1.0))
    _, client = build(**files)
    first = client.get("/api/voice/fixtures").json()["fixtures"][0]
    assert first["wav_url"] is None
    assert client.get("/api/voice/fixtures/vf_family_bin/audio").status_code == 404


def test_transcribe_fixture_cached(api: TestClient) -> None:
    body = api.post("/api/voice/transcribe", json={"fixture_id": "vf_family_bin"}).json()
    assert body["live"] is False
    assert body["notice"] is None
    result = body["result"]
    assert result["transcript"] == "Tell me if anyone except family touches the bin after 9 PM"
    assert result["fixture_id"] == "vf_family_bin"
    assert result["editable"] is True
    assert body["telemetry"]["model"] == "muse-voice-transcribe-1.0"
    assert body["telemetry"]["cached"] is True
    assert api.post("/api/voice/transcribe", json={"fixture_id": "nope"}).status_code == 404
    assert api.post("/api/voice/transcribe", json={}).status_code == 422


def test_transcribe_fixture_live_without_recorded_audio_uses_cached(api: TestClient) -> None:
    body = api.post("/api/voice/transcribe",
                    json={"fixture_id": "vf_named_gate", "live": True}).json()  # fmt: skip
    assert body["live"] is False
    assert "recorded result shown" in body["notice"]
    assert body["result"]["transcript"].startswith("Tell me if anyone except Sam")


def test_transcribe_fixture_live_sends_the_listed_wav(tmp_path) -> None:
    wav = _wav16()
    backend = FakeBackend()
    _, client = build(backend=backend, **_fixture_files(tmp_path, wav))
    body = client.post("/api/voice/transcribe",
                       json={"fixture_id": "vf_family_bin", "live": True}).json()  # fmt: skip
    assert backend.calls == ["transcribe"]
    assert backend.audio == wav
    assert body["live"] is True
    assert body["telemetry"]["cached"] is False
    assert body["result"]["transcript"].startswith("tell me")


def test_transcribe_recording_live_then_compile_the_edited_text() -> None:
    backend = FakeBackend()
    _, client = build(backend=backend)
    r = client.post("/api/voice/transcribe?live=true", content=_wav16(),
                    headers={"content-type": "audio/wav"})  # fmt: skip
    body = r.json()
    assert backend.calls == ["transcribe"]
    assert body["live"] is True
    assert body["result"]["editable"] is True
    assert body["telemetry"]["model"] == "muse-voice-transcribe-1.0"
    edited = body["result"]["transcript"].replace("9 PM", "11 PM")
    compiled = client.post("/api/rules/compile", json={"text": edited, "live": True}).json()
    assert backend.calls == ["transcribe", "compile"]
    assert compiled["live"] is True
    calls = client.get("/api/calls").json()["calls"]
    assert any(c["model"] == "muse-voice-transcribe-1.0" and not c["cached"] for c in calls)


def test_transcribe_recording_without_live_is_an_empty_editable_transcript(api) -> None:
    r = api.post("/api/voice/transcribe", content=_wav16(), headers={"content-type": "audio/wav"})
    body = r.json()
    assert body["live"] is False
    assert body["result"]["transcript"] == ""
    assert "type" in body["notice"].lower()


def test_transcribe_failure_falls_back_with_notice() -> None:
    _, client = build(backend=FakeBackend(error=ConnectionError("api down")))
    r = client.post("/api/voice/transcribe?live=true", content=_wav16(),
                    headers={"content-type": "audio/wav"})  # fmt: skip
    body = r.json()
    assert body["live"] is False
    assert body["notice"].startswith("Live call failed")
    assert body["result"]["transcript"] == ""
    fx = client.post("/api/voice/transcribe", json={"fixture_id": "vf_family_bin", "live": True})
    assert fx.json()["result"]["transcript"].startswith("Tell me if anyone except family")


def test_spoken_audio_is_never_written_to_disk(monkeypatch) -> None:
    """NFR-002: the real adapter hands the bytes to vigil.meta.asr; no temp file is made."""
    import tempfile

    import vigil.meta.asr as asr
    from vigil.api.backend import MetaLiveBackend

    seen: dict[str, Any] = {}

    def fake_transcribe_wav(c, wav, visit_id=None):
        seen["wav"] = wav
        return asr.Transcript(text="tell me if anyone touches the bin", audio_sha256="x",
                              source="live", cached=False, call_id="call_live_9")  # fmt: skip

    def no_temp(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("spoken audio must never touch the disk")

    monkeypatch.setattr(asr, "transcribe_wav", fake_transcribe_wav)
    for name in ("TemporaryDirectory", "NamedTemporaryFile", "mkstemp", "mkdtemp"):
        monkeypatch.setattr(tempfile, name, no_temp)
    backend = MetaLiveBackend(make_settings())
    backend._client = type("NoNetwork", (), {"ledger": []})()
    audio = _wav16()
    res = backend.transcribe(audio, "audio/wav")
    assert seen["wav"] == audio
    assert isinstance(seen["wav"], bytes)
    assert res.payload["transcript"] == "tell me if anyone touches the bin"


# --- compile: applies_to, basis note, named person (FR-021, UC-03) ------------------------


def test_compile_cached_role_phrasings() -> None:
    _, client = build(backend=ExplodingBackend())
    fixtures = client.get("/api/voice/fixtures").json()["fixtures"]
    want = {"vf_family_bin": "non_household", "vf_strangers_gate": "external_visitor_only",
            "vf_named_gate": "non_household"}  # fmt: skip
    for f in fixtures:
        body = client.post("/api/rules/compile", json={"text": f["transcript"]}).json()
        result = body["result"]
        assert body["notice"] is None, f["id"]
        assert result["rule"]["applies_to"] == want[f["id"]]
        assert (
            "does not identify anyone and creates no face, voice or body templates"
            in (result["basis_note"])
        )
    family = client.post("/api/rules/compile", json={"text": fixtures[0]["transcript"]}).json()
    assert family["result"]["applies_label"] == "Applies to everyone except household members."
    assert family["result"]["basis_note"].startswith("Vigil treats someone as household only")
    named = client.post("/api/rules/compile", json={"text": fixtures[2]["transcript"]}).json()
    assert any(n.startswith("Vigil can't recognise individuals") for n in
               named["result"]["limits_note"])  # fmt: skip
    assert "Sam" not in json.dumps(named["result"]["rule"])  # no rule ever names a person


def test_compile_live_keeps_the_compiled_applies_to() -> None:
    class Role(FakeBackend):
        def compile_rule(self, text, catalog):
            res = super().compile_rule(text, catalog)
            res.payload["rule"]["applies_to"] = "non_household"
            res.payload["limits"] = res.payload.pop("limits_note")
            return res

    _, client = build(backend=Role())
    text = "tell me if anyone except Sam opens the side gate after 11"
    body = client.post("/api/rules/compile", json={"text": text, "live": True}).json()
    result = body["result"]
    assert result["rule"]["applies_to"] == "non_household"
    assert result["applies_label"] == "Applies to everyone except household members."
    assert any("so Sam is exempt only in those cases" in n for n in result["limits_note"])


def test_compile_live_clarifying_question_is_shown() -> None:
    class Ask(FakeBackend):
        def compile_rule(self, text, catalog):
            self._start("compile")
            return LiveResult.model_construct(
                payload={"question": "Which of these do you mean: side gate?",
                         "options": ["po_side_gate"], "reason": "unknown target",
                         "source_text": text},
                calls=self._call("rule_compile", "muse-spark-1.3"),
            )  # fmt: skip

    _, client = build(backend=Ask())
    body = client.post("/api/rules/compile", json={"text": "the shed", "live": True}).json()
    assert body["live"] is True
    assert body["result"]["rule"] is None
    assert body["result"]["question"].startswith("Which of these do you mean")


# --- expected windows (FR-029) --------------------------------------------------------------


OWNER_TOKEN = "owner-api-test-token-5e1f"


def owner_settings(tmp_path, **kw: Any) -> Settings:
    """Edge settings with VIGIL_OWNER_TOKEN set: owner endpoints need it (F2)."""
    return make_settings(mode="edge", db_path=tmp_path / "edge.db", owner_token=OWNER_TOKEN, **kw)


def as_owner(client: TestClient) -> TestClient:
    client.headers["authorization"] = f"Bearer {OWNER_TOKEN}"
    return client


def _edge(tmp_path, ip: str = "192.168.1.20", clock: FakeClock | None = None):
    app, client = build(owner_settings(tmp_path), clock=clock or FakeClock(), ip=ip)
    return app, as_owner(client)


def _iso(clock: FakeClock, offset_s: float) -> str:
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    t = datetime.fromtimestamp(clock.t + offset_s, tz=UTC)
    return t.astimezone(ZoneInfo("America/Los_Angeles")).isoformat()


def test_windows_sandbox_serves_presets(api: TestClient) -> None:
    body = api.get("/api/windows").json()
    (w3,) = body["windows"]
    assert w3["id"] == "w3"
    assert w3["label"] == "deliveries"
    assert w3["cameras"] == ["front"]
    assert w3["recorded"] is True


def test_windows_create_list_cancel_and_persist(tmp_path) -> None:
    clock = FakeClock()
    _, lan = _edge(tmp_path, clock=clock)
    body = {"start": _iso(clock, 600), "end": _iso(clock, 600 + 4 * 3600),
            "cameras": ["front"], "label": "plumber"}  # fmt: skip
    r = lan.post("/api/windows", json=body)
    assert r.status_code == 200, r.text
    created = r.json()["window"]
    assert created["state"] == "scheduled"
    assert created["label"] == "plumber"
    ids = [w["id"] for w in lan.get("/api/windows").json()["windows"]]
    assert created["id"] in ids
    clock.t += 700
    listed = {w["id"]: w for w in lan.get("/api/windows").json()["windows"]}
    assert listed[created["id"]]["state"] == "active"
    # Persisted: a fresh app on the same database still has it.
    _, again = _edge(tmp_path, clock=clock)
    assert created["id"] in [w["id"] for w in again.get("/api/windows").json()["windows"]]
    cancelled = again.delete(f"/api/windows/{created['id']}")
    assert cancelled.status_code == 200
    assert cancelled.json()["window"]["state"] == "cancelled"
    assert again.delete("/api/windows/nope").status_code == 404
    clock.t += 5 * 3600
    _, later = _edge(tmp_path, clock=clock)
    states = {w["id"]: w["state"] for w in later.get("/api/windows").json()["windows"]}
    assert states[created["id"]] == "cancelled"


def test_windows_validation(tmp_path) -> None:
    clock = FakeClock()
    _, lan = _edge(tmp_path, clock=clock)
    too_long = {"start": _iso(clock, 60), "end": _iso(clock, 60 + 12 * 3600 + 1)}
    assert lan.post("/api/windows", json=too_long).status_code == 422
    past = {"start": _iso(clock, -3600), "end": _iso(clock, 3600)}
    assert lan.post("/api/windows", json=past).status_code == 422
    bad_cam = {"start": _iso(clock, 60), "end": _iso(clock, 3600), "cameras": ["garage"]}
    assert lan.post("/api/windows", json=bad_cam).status_code == 422
    backwards = {"start": _iso(clock, 3600), "end": _iso(clock, 60)}
    assert lan.post("/api/windows", json=backwards).status_code == 422
    expires = {"start": _iso(clock, 60), "end": _iso(clock, 120)}
    wid = lan.post("/api/windows", json=expires).json()["window"]["id"]
    clock.t += 200
    states = {w["id"]: w["state"] for w in lan.get("/api/windows").json()["windows"]}
    assert states[wid] == "expired"


# --- check-in (FR-044 step 2) ---------------------------------------------------------------


def test_checkin_is_single_use_with_120s_binding_and_30_min_expiry(tmp_path) -> None:
    from datetime import datetime

    clock = FakeClock()
    _, lan = _edge(tmp_path, clock=clock)
    r = lan.post("/api/checkin", headers={"x-vigil-session": "owner_phone"})
    assert r.status_code == 200
    body = r.json()
    c = body["checkin"]
    start, expires = datetime.fromisoformat(c["start"]), datetime.fromisoformat(c["expires"])
    assert (expires - start).total_seconds() == 1800
    assert c["bound_subject"] is None
    assert c["session_id"] == "owner_phone"
    assert body["binds_within_s"] == 120
    assert "never" in body["note"].lower()  # never retroactive
    from vigil.store import db

    conn = db.open_db(tmp_path / "edge.db")
    assert [x.id for x in db.checkins(conn)] == [c["id"]]


# --- feedback: "This was expected" never changes a verdict (FR-029) -------------------------


def test_feedback_is_stored_and_never_changes_the_verdict(api: TestClient) -> None:
    before = api.get("/api/visits/v_c").json()["verdict"]
    r = api.post("/api/visits/v_c/feedback", json={"kind": "expected"})
    assert r.status_code == 200
    body = r.json()
    assert body["stored"] is True
    assert body["verdict"] == before
    assert "never changes" in body["note"]
    assert api.get("/api/visits/v_c").json()["verdict"] == before
    assert api.post("/api/visits/v_c/feedback", json={"kind": "wrong"}).status_code == 422
    assert api.post("/api/visits/nope/feedback", json={"kind": "expected"}).status_code == 404


def test_feedback_is_rate_limited() -> None:
    _, client = build(backend=ExplodingBackend())
    for _ in range(10):
        assert client.post("/api/visits/v_b/feedback", json={"kind": "expected"}).status_code == 200
    assert client.post("/api/visits/v_b/feedback", json={"kind": "expected"}).status_code == 429


# --- SAM landmark proposals (FR-037, UC-10) -------------------------------------------------


def test_landmarks_blocked_until_the_spatial_workstream_lands(tmp_path) -> None:
    _, lan = _edge(tmp_path)
    r = lan.post("/api/spatial/landmarks", json={"camera_id": "side_left"})
    assert r.status_code == 200
    body = r.json()
    assert body["blocked"] is True
    assert body["proposals"] == []
    assert "landmark" in body["notice"].lower()
    assert lan.post("/api/spatial/landmarks", json={"camera_id": "garage"}).status_code == 422


def test_landmarks_live_with_backend(tmp_path) -> None:
    class Landmarks(FakeBackend):
        def propose_landmarks(self, camera_id):
            self._start("landmarks")
            return LiveResult.model_construct(
                payload={"proposals": [{"label": "gate post", "pixel": [812, 410]}]},
                calls=self._call("landmarks", "sam-3.1"),
            )

    backend = Landmarks()
    _, lan = build(owner_settings(tmp_path), backend=backend, ip="10.0.0.8")
    as_owner(lan)
    body = lan.post("/api/spatial/landmarks", json={"camera_id": "side_left"}).json()
    assert backend.calls == ["landmarks"]
    assert body["blocked"] is False
    assert body["proposals"][0]["label"] == "gate post"
    assert body["telemetry"]["model"] == "sam-3.1"


def test_landmarks_default_adapter_says_when_no_still_exists(tmp_path) -> None:
    """The real adapter reaches vigil.spatial.landmarks; the synthetic bundle has no stills."""
    app = create_app(owner_settings(tmp_path), clock=FakeClock())
    lan = as_owner(client_for(app, "192.168.1.30"))
    body = lan.post("/api/spatial/landmarks", json={"camera_id": "side_left"}).json()
    assert body["proposals"] == []
    assert body["blocked"] is False
    assert "still" in body["notice"]
