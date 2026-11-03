"""FR-017/018: normalized UI reads actual bundle evidence; chat is cached and cited."""

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
        assert all(c["status"] == "privacy_blocked" for c in state["cameras"])
        assert all(not c["privacy_reviewed"] for c in state["cameras"])
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
