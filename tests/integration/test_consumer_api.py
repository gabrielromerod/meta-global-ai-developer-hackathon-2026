"""FR-017/018: normalized UI reads actual bundle evidence; chat is cached and cited."""

import json

from fastapi.testclient import TestClient

from vigil.api.app import create_app
from vigil.settings import Settings


def client():
    return TestClient(
        create_app(
            Settings(_env_file=None, mode="sandbox", MODEL_API_KEY="invalid", meta_cache_only=True)
        )
    )


def test_ui_state_seven_cameras_honest_counts_and_role_contrast():
    with client() as api:
        response = api.get("/api/ui/state")
        assert response.status_code == 200
        state = response.json()
        assert state["contract_version"] == "vigil-ui/1"
        assert state["evidence"]["kind"] == "fixture"
        assert len(state["cameras"]) == 7
        # Owner-reviewed stills (Nov 3): doorbell and porch pass; battery cameras stay blocked.
        # The front Duos are reviewed too, but a later zone edit voids their digest until the
        # owner re-reviews, so they may be either; reviewed always means "not_connected".
        reviewed = {c["id"] for c in state["cameras"] if c["privacy_reviewed"]}
        assert (
            {"doorbell", "porch"}
            <= reviewed
            <= {
                "front_left_duo",
                "front_right_duo",
                "doorbell",
                "porch",
            }
        )
        assert all(
            (c["status"] == "not_connected") == c["privacy_reviewed"] for c in state["cameras"]
        )
        assert all(
            c["power_profile"] == "battery_wifi" and c["source_label"] == "Imported clips"
            for c in state["cameras"]
            if c["id"] in {"side_left", "backyard_1", "backyard_2"}
        )
        assert state["summary"]["camera_events"] is None
        assert state["summary"]["street_events"] is None
        visits = {v["id"]: v for v in state["visits"]}
        assert visits["v_ap"]["verdict"] == "normal"
        assert visits["v_ap"]["role_label"] == "Household"
        assert "came out of the house" in visits["v_ap"]["role_basis"]
        assert "excludes" in visits["v_ap"]["reason"]
        assert visits["v_c"]["verdict"] == "needs_attention"
        assert "rule" in visits["v_c"]["reason"].lower()
        assert not state["owner"]["enabled"]
        assert state["owner"]["reason"] == "Owner-only on the home box"


def test_ui_search_intersects_filters_and_rejects_bad_times():
    with client() as api:
        result = api.get(
            "/api/ui/search",
            params={"q": "gate", "camera": "side_left", "verdict": "needs_attention"},
        ).json()
        assert [v["id"] for v in result["visits"]] == ["v_c"]
        assert all(c["camera_id"] == "side_left" for c in result["clips"])
        assert api.get("/api/ui/search", params={"start": "not-a-time"}).status_code == 422
        assert (
            api.get(
                "/api/ui/search",
                params={"start": "2026-11-03T12:00:00", "end": "2026-11-02T12:00:00"},
            ).status_code
            == 422
        )


def test_ui_attention_ids_do_not_truncate_the_full_attention_page():
    with client() as api:
        bundle = api.app.state.bundle
        template = next(v for v in bundle.visits if v.verdict == "needs_attention")
        bundle.visits.extend(template.model_copy(update={"id": f"added_{i}"}) for i in range(6))
        state = api.get("/api/ui/state").json()
        assert len(state["attention_ids"]) == 8


def test_chat_answers_from_cited_cached_ledger_and_has_no_people_backend():
    with client() as api:
        result = api.post(
            "/api/chat/ask",
            json={"thread_id": "ask-home", "text": "side gate", "session_id": "synthetic"},
        )
        assert result.status_code == 200
        message = result.json()["message"]
        assert message["citations"]
        for cite in message["citations"]:
            visit = api.get("/api/visits/" + cite["visit_id"]).json()
            assert cite["event_id"] in {e["event_id"] for e in visit["events"]}
        assert (
            api.post(
                "/api/chat/ask",
                json={"thread_id": "household", "text": "hi", "session_id": "synthetic"},
            ).status_code
            == 400
        )
        answer = api.post(
            "/api/chat/ask",
            json={"thread_id": "ask-home", "text": "unseen meteor", "session_id": "synthetic"},
        ).json()["message"]
        assert not answer["citations"]
        assert "no matching" in answer["text"].lower()


def test_today_events_do_not_relabel_the_recorded_evening():
    with client() as api:
        today = api.get("/api/ui/events", params={"date": "2026-11-03"}).json()
        assert today["events"] == []
        assert today["date"] == "2026-11-03"
        recorded = api.get("/api/ui/events", params={"date": "2026-11-02"}).json()
        assert recorded["events"]


def test_public_twin_and_positions_share_canonical_camera_ids():
    with client() as api:
        twin = api.get("/api/ui/twin")
        assert twin.status_code == 200
        assert twin.json()["generic_massing"]
        assert twin.json()["glb_url"] is None
        assert len(twin.json()["cameras"]) == 7
        state = api.get("/api/ui/state").json()
        ids = {c["id"] for c in state["cameras"]}
        positions = api.get("/api/ui/visits/v_c/positions").json()
        assert positions["positions"]
        assert all(set(p["cameras"]) <= ids for p in positions["positions"])
        assert positions["events"]
        assert all(e["camera_id"] in ids for e in positions["events"])


def test_ui_visit_detail_keeps_citations_and_player_metadata_in_one_camera_namespace():
    with client() as api:
        response = api.get("/api/ui/visits/v_c")
        assert response.status_code == 200
        result = response.json()
        ids = {c["id"] for c in api.get("/api/ui/state").json()["cameras"]}
        assert result["evidence"]["kind"] == "fixture"
        assert result["verdict"] == "needs_attention"
        original = api.get("/api/visits/v_c").json()["sentences"]
        assert [s["text"] for s in result["sentences"]] == [s["text"] for s in original]
        assert [[c["event_id"] for c in s["citations"]] for s in result["sentences"]] == [
            [c["event_id"] for c in s["citations"]] for s in original
        ]
        assert len(result["sentences"]) == 5
        assert result["trace"]["drafts"][0]["passed"] is False
        for sentence in result["sentences"]:
            assert all(c["camera_id"] in ids for c in sentence["citations"])
        assert set(result["overlays"]) <= ids
        assert result["playback_cameras"]
        assert all(c["id"] in ids for c in result["playback_cameras"])
        assert all(c["clip_url"] is None for c in result["playback_cameras"])
        assert all(c["width"] > 0 and c["height"] > 0 for c in result["playback_cameras"])
        assert api.get("/api/ui/visits/missing-visit").status_code == 404


def test_doorbell_press_and_measured_street_count_stay_separate_from_visits():
    with client() as api:
        bundle = api.app.state.bundle
        bundle.tables["camera_ai_events"] = [
            {
                "id": "press",
                "camera_id": "doorbell",
                "kind": "doorbell_press",
                "t0": 10,
                "t1": 10.1,
            },
            {"id": "street", "camera_id": "front_left_duo", "kind": "person", "t0": 20, "t1": 21},
        ]
        bundle.manifest["prefilter_counts"] = {
            "camera_events": 2,
            "on_property": 1,
            "street_events": 1,
            "street_event_ids": ["street"],
            "property_event_ids": ["press"],
            "unclassified_event_ids": [],
        }
        response = api.get("/api/ui/events", params={"date": "2026-11-02"}).json()
        assert response["street_events"] == 1
        assert response["camera_events"][0]["kind"] == "doorbell_press"
        assert response["camera_events"][0]["layer"] == "camera_ai"
        assert "actor_role" not in response["camera_events"][0]
        assert api.get("/api/ui/state").json()["summary"]["camera_events"] == 2


def test_duo_protect_coordinates_are_validated_against_full_frame():
    with client() as api:
        bundle = api.app.state.bundle
        bundle.tables["cameras"][0].update(id="front_left_duo", width=1920, height=720)
        allowed = {"camera_id": "front_left_duo", "point": {"x": 1600, "y": 600}}
        assert api.post("/api/protect", json=allowed).status_code == 200
        assert (
            api.post("/api/protect", json={**allowed, "point": {"x": 1921, "y": 600}}).status_code
            == 422
        )
        scaled = {
            **allowed,
            "point": {"x": 3200, "y": 1200},
            "frame_width": 3840,
            "frame_height": 1440,
        }
        assert api.post("/api/protect", json=scaled).status_code == 200
        assert (
            api.post("/api/protect", json={**scaled, "point": {"x": 3841, "y": 1200}}).status_code
            == 422
        )


def _private_massing(data_dir):
    from vigil.spatial.massing import build_massing

    doc = build_massing(
        {
            "buildings": [{"id": "main", "min": [-5, 0], "max": [5, 12], "h": 2.9}],
            "cameras": {"doorbell": {"position": [0.6, 1.3, -0.05], "look_at": [0, 0.8, -6]}},
        }
    )
    (data_dir / "spatial").mkdir(parents=True)
    (data_dir / "spatial" / "massing.json").write_text(json.dumps(doc), encoding="utf-8")


def _client_at(data_dir, ip):
    app = create_app(
        Settings(
            _env_file=None,
            mode="sandbox",
            MODEL_API_KEY="invalid",
            meta_cache_only=True,
            data_dir=data_dir,
        )
    )
    return TestClient(app, client=(ip, 50000))


def test_private_house_massing_is_served_to_loopback_only(tmp_path):
    _private_massing(tmp_path)
    with _client_at(tmp_path, "127.0.0.1") as api:
        default = api.get("/api/ui/twin").json()
        assert default["generic_massing"]
        assert default["private_available"]
        house = api.get("/api/ui/twin", params={"model": "house"}).json()
        assert house["private_massing"]
        assert not house["generic_massing"]
        assert house["glb_url"] is None
        assert house["blind_regions"] == []
        assert [c["id"] for c in house["cameras"]] == ["doorbell"]
        assert house["site_plan"]["boxes"][0]["id"] == "main"
    with _client_at(tmp_path, "203.0.113.7") as api:
        public = api.get("/api/ui/twin", params={"model": "house"}).json()
        assert public["generic_massing"]
        assert not public.get("private_available")
        assert "detail" not in public


def test_private_house_massing_absent_falls_back_to_generic(tmp_path):
    with _client_at(tmp_path, "127.0.0.1") as api:
        twin = api.get("/api/ui/twin", params={"model": "house"}).json()
        assert twin["generic_massing"]
        assert not twin["private_available"]


def test_benchmark_lists_five_models_from_the_ledger_and_labels_economics(tmp_path):
    """Benchmark tab: model rows come from the call ledger; 11.9 economics stay hypotheses."""
    import sqlite3

    ledger = tmp_path / "ledger.db"
    conn = sqlite3.connect(ledger)
    conn.execute(
        "create table model_calls(id text primary key, model text, purpose text, visit_id text,"
        " req_hash text, latency_ms int, in_tokens int, out_tokens int, units real,"
        " cost_usd real, cached int, ok int, error text, backend text, gpu_s real,"
        " feature text, funding text, created_at text)"
    )
    rows = [("a", "sam-3.1", 6000, 0.02, 0), ("b", "sam-3.1", 0, 0.0, 1),
            ("c", "muse-wonder-1.0", 9000, 0.05, 0)]  # fmt: skip
    rows = [(i, m, lat, c, k) for i, m, lat, c, k in rows]
    conn.executemany(
        "insert into model_calls(id, model, purpose, req_hash, latency_ms, cost_usd, cached, ok,"
        " backend, feature, funding, created_at)"
        " values (?, ?, 'test', 'h', ?, ?, ?, 1, 'api', 'perception_demo', 'credit',"
        " '2026-11-04T12:00:00+00:00')",
        rows,
    )
    conn.commit()
    conn.close()
    app = create_app(Settings(_env_file=None, mode="dev", ledger_path=ledger))
    bench = TestClient(app).get("/api/ui/state").json()["benchmark"]
    models = {m["model"]: m for m in bench["models"]}
    assert list(models) == [
        "sam-3.1", "muse-spark-1.3", "muse-wonder-1.0", "muse-voice-transcribe-1.0",
        "muse-glimmer-30b-q4",
    ]  # fmt: skip
    assert models["sam-3.1"]["live_calls"] == 1
    assert models["sam-3.1"]["cached_calls"] == 1
    assert models["sam-3.1"]["cost_usd"] == 0.02
    assert models["sam-3.1"]["median_latency_ms"] == 6000
    assert models["muse-spark-1.3"]["live_calls"] == 0
    econ = bench["economics"]
    assert econ["status"] == "hypothesis"
    assert any("1.80" in row["monthly"] for row in econ["rows"])
    assert bench["measured"] is False  # a ledger is usage, not a field benchmark
