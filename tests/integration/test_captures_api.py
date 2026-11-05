"""LAN-only list of recorded event clips before analysis (FR-031/032, spec 9.6).

The capture folders are written by the real `EventRecorder.finish`, so the reader is tested
against the writer's actual file shapes. Generated clips only; no footage.
"""

import hashlib
import os
import shutil
from datetime import UTC, datetime

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.fixtures.video.synth import texture_clip
from vigil import settings as vigil_settings
from vigil.api.app import create_app
from vigil.ingest.review import privacy_digest
from vigil.models import CameraAiEvent, CameraCfg, Config
from vigil.reolink.capture import segment_name
from vigil.settings import Settings

T_FIRST = 1_793_000_000.0
T_SECOND = 1_793_000_600.0


@pytest.fixture(autouse=True)
def _settings_without_dotenv(monkeypatch):
    # ffmpeg/ffprobe resolution must not read a developer's local .env.
    monkeypatch.setattr(vigil_settings, "get_settings", lambda: Settings(_env_file=None))


def _reviewed(camera_id: str, name: str) -> CameraCfg:
    camera = CameraCfg(
        id=camera_id,
        name=name,
        privacy=[[(0, 0), (1280, 0), (1280, 60), (0, 60)]],
        privacy_regions={"timestamp_watermark": [(10, 10), (300, 10), (300, 50), (10, 50)]},
        privacy_reviewed=True,
        privacy_still_sha256=hashlib.sha256(b"generated-still").hexdigest(),
    )
    camera.privacy_polygons_sha256 = privacy_digest(camera, camera.privacy)
    return camera


def _key(event_id: str) -> str:
    return hashlib.sha256(event_id.encode()).hexdigest()[:20]


def _raw(home, event_id: str, attempt: int = 0):
    return home["root"] / "capture" / "ring" / f"event-{_key(event_id)}-{attempt:03d}.mp4"


def _record(tmp_path, camera: CameraCfg, event_id: str, t0: float, t1: float | None) -> str:
    from vigil.reolink.event_capture import EventRecorder

    ring = tmp_path / "capture" / "ring"
    sub = ring / camera.id / segment_name(camera.id, t0 - 5)
    sub.parent.mkdir(parents=True, exist_ok=True)
    texture_clip(sub, 0.3, size=(320, 180), audio=False)
    # Named as run_event_capture names the raw main-stream clip it keeps in the ring.
    main = ring / f"event-{_key(event_id)}-000.mp4"
    texture_clip(main, 0.5, size=(640, 360), audio=False)
    recorder = EventRecorder(ring, tmp_path / "windows", camera.model_copy())
    event = CameraAiEvent(id=event_id, camera_id=camera.id, kind="person", t0=t0, t1=t1)
    return recorder.finish(event, main, main_start=t0)["session_id"]


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """Record the clips once per module; each test gets its own copy of the tree."""
    root = tmp_path_factory.mktemp("recorded")
    porch = _reviewed("porch", "Porch")
    doorbell = CameraCfg(id="doorbell", name="Front door")  # real, never reviewed
    (root / "cameras.yaml").write_text(
        yaml.safe_dump(Config(cameras=[porch, doorbell]).model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(vigil_settings, "get_settings", lambda: Settings(_env_file=None))
        first = _record(root, porch, "e-first", T_FIRST, T_FIRST + 0.2)
        second = _record(root, porch, "e-second", T_SECOND, None)
        recorded_doorbell = doorbell.model_copy(update={"evidence_kind": "fixture"})
        door = _record(root, recorded_doorbell, "e-door", T_FIRST + 60, T_FIRST + 60.1)
    (root / "results" / first).mkdir(parents=True)
    return {"root": root, "first": first, "second": second, "door": door}


@pytest.fixture
def home(recorded, tmp_path):
    root = tmp_path / "data"
    shutil.copytree(recorded["root"], root, symlinks=True)
    return {**recorded, "root": root, "config": root / "cameras.yaml"}


def _client(home, ip="127.0.0.1", mode="edge"):
    app = create_app(
        Settings(
            _env_file=None,
            mode=mode,
            MODEL_API_KEY="invalid",
            meta_cache_only=True,
            data_dir=home["root"],
            config_path=home["config"],
        )
    )
    return TestClient(app, client=(ip, 50000))


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat()


def test_captures_list_newest_first_with_unanalysed_camera_ai_rows(home):
    with _client(home) as api:
        response = api.get("/api/ui/captures")
    assert response.status_code == 200
    rows = response.json()["captures"]
    assert [r["id"] for r in rows] == [home["second"], home["door"], home["first"]]
    second, door, first = rows
    assert set(first) == {
        "id",
        "camera_id",
        "camera_name",
        "kind",
        "started_at",
        "ended_at",
        "partial",
        "clip_url",
        "masked",
        "analysis",
        "verdict",
        "headline",
        "layer",
        "frame_aspect",
        "crop",
        "crop_top",
        "subject",
    }
    assert first["verdict"] is first["headline"] is None  # not analysed yet
    assert first["camera_id"] == "porch"
    assert first["camera_name"] == "Porch"
    assert first["kind"] == "person"
    assert first["layer"] == "camera_ai"
    assert first["started_at"] == _iso(T_FIRST)
    assert first["ended_at"] == _iso(T_FIRST + 0.2)
    assert first["analysis"] == "analysed"
    assert first["clip_url"] == f"/api/ui/captures/{home['first']}/clip"
    assert first["masked"] is False  # the raw clip is kept, so LAN view is unmasked
    assert second["analysis"] == "not_analysed"
    assert second["ended_at"] is None
    assert second["partial"] is True
    assert door["camera_name"] == "Front door"
    assert door["clip_url"] == f"/api/ui/captures/{home['door']}/clip"
    assert door["masked"] is False
    text = response.text
    assert str(home["root"]) not in text
    assert "path" not in text
    assert "rtsp" not in text


def test_captures_refuse_non_lan_client(home):
    with _client(home, ip="203.0.113.7") as api:
        assert api.get("/api/ui/captures").status_code == 403
        assert api.get(f"/api/ui/captures/{home['first']}/clip").status_code == 403


def test_captures_refused_in_sandbox(home):
    with _client(home, mode="sandbox") as api:
        assert api.get("/api/ui/captures").status_code == 403
        assert api.get(f"/api/ui/captures/{home['first']}/clip").status_code == 403


def test_capture_clip_rejects_traversal_ids(home):
    outside = home["root"] / "porch-0123456789abcdef0123-0123456789ab"
    outside.mkdir()
    (outside / "capture.json").write_text("{}", encoding="utf-8")
    link = home["root"] / "windows" / "porch-aaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbb"
    os.symlink(outside, link)
    with _client(home) as api:
        for bad in (
            "..",
            "..%2Fcameras.yaml",
            "%2e%2e",
            "porch-0123",
            "porch-0123456789abcdef0123-0123456789ab.mp4",
            "porch-aaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbb",
            "porch-cccccccccccccccccccc-dddddddddddd",
        ):
            response = api.get(f"/api/ui/captures/{bad}/clip")
            assert response.status_code in {400, 404}, bad
            assert not response.headers.get("content-type", "").startswith("video/"), bad
        ids = [r["id"] for r in api.get("/api/ui/captures").json()["captures"]]
    assert "porch-aaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbb" not in ids


def test_capture_clip_serves_raw_unmasked_clip_on_lan(home):
    with _client(home) as api:
        clip = api.get(f"/api/ui/captures/{home['door']}/clip")  # camera never reviewed
    assert clip.status_code == 200
    assert clip.headers["content-type"] == "video/mp4"
    assert clip.content == _raw(home, "e-door").read_bytes()


def test_capture_clip_falls_back_to_masked_part_without_linked_raw(home):
    _raw(home, "e-first").unlink()
    # Same event key but another attempt: not this capture's clip, never served for it.
    texture_clip(_raw(home, "e-first", attempt=1), 0.2, size=(320, 180), audio=False)
    masked = home["root"] / "windows" / home["first"] / "part-001.mp4"
    with _client(home) as api:
        row = next(
            r for r in api.get("/api/ui/captures").json()["captures"] if r["id"] == home["first"]
        )
        clip = api.get(f"/api/ui/captures/{home['first']}/clip")
    assert row["masked"] is True
    assert row["clip_url"] == f"/api/ui/captures/{home['first']}/clip"
    assert clip.status_code == 200
    assert clip.content == masked.read_bytes()


def test_capture_clip_streams_with_range(home):
    main = _raw(home, "e-first")
    with _client(home) as api:
        full = api.get(f"/api/ui/captures/{home['first']}/clip")
        partial = api.get(f"/api/ui/captures/{home['first']}/clip", headers={"Range": "bytes=0-99"})
    assert full.status_code == 200
    assert full.headers["content-type"] == "video/mp4"
    assert full.content == main.read_bytes()
    assert partial.status_code == 206
    assert partial.headers["content-range"].startswith("bytes 0-99/")
    assert partial.content == main.read_bytes()[:100]
    assert str(home["root"]) not in full.headers.get("content-disposition", "")


# --- analysis of a captured clip (FR-012/FR-015 output shown on the LAN) ----------------


def _clip_start(home) -> float:
    """Session-relative second at which the served camera clip starts (its main part)."""
    import json

    folder = home["root"] / "windows" / home["first"]
    capture = json.loads((folder / "capture.json").read_text(encoding="utf-8"))
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    main = next(p for p in capture["parts"] if p["source_quality"] == "main")
    return main["t0"] - datetime.fromisoformat(session["session_start"]).timestamp()


def _analysis(home) -> None:
    import json

    start = _clip_start(home)
    results = home["root"] / "results" / home["first"]
    (results / "tagged").mkdir(parents=True, exist_ok=True)
    texture_clip(results / "tagged" / "porch_1793000000000.mp4", 0.3, size=(320, 180), audio=False)
    visits = {
        "appearance": {
            "porch-person-1": {"tag": "T1", "class": "person", "upper_color": "white",
                               "lower_color": "black", "carrying": [], "vehicle_color": None,
                               "vehicle_body": None, "illumination": "unknown"},
        },
        "tracks": [{"id": "porch-person-1", "phrase": "person", "tag": "T1", "camera_id": "porch",
                    "t_first": start + 1.0, "t_last": start + 4.0, "origin_zone": "porch_path"}],
        "windows": [{"id": "porch_1793000000000", "t0": start + 1.0, "t1": start + 3.0}],
        "events": [{"id": "e1", "t0": start + 2.5, "track_id": "porch-person-1", "type": "enter"}],
        "visits": [{
            "id": "v1", "verdict": "cant_confirm", "story_source": "wonder",
            "story": [
                {"text": "At 5:07 PM, a person entered the view of Porch.", "source": "wonder",
                 "event_ids": ["e1"], "gap_id": None},
                {"text": "The recording ended before the camera event closed.", "source": "code",
                 "event_ids": [], "gap_id": "g1"},
            ],
            "subjects": [{"id": "s1", "actor_role": "unknown", "role_basis": "origin_null:x",
                          "track_ids": ["porch-person-1"]}],
            "gaps": [{"id": "g1", "kind": "clip_truncated", "resolved": False}],
        }],
    }  # fmt: skip
    (results / "visits.json").write_text(json.dumps(visits), encoding="utf-8")


def test_capture_analysis_returns_story_verdict_and_tagged_clip(home):
    _analysis(home)
    with _client(home) as api:
        response = api.get(f"/api/ui/captures/{home['first']}/analysis")
        assert response.status_code == 200
        body = response.json()
        tagged = api.get(body["tagged"][0]["url"])
    assert body["verdict"] == "cant_confirm"
    assert body["story_source"] == "wonder"
    assert [s["source"] for s in body["story"]] == ["wonder", "code"]
    assert body["story"][0]["event_ids"] == ["e1"]
    # Times are seconds into the camera clip, so the player can jump to each sentence.
    assert body["story"][0]["at"] == pytest.approx(2.5, abs=0.01)
    assert body["story"][0]["kind"] == "person"
    assert body["story"][1]["at"] is None
    assert body["tagged"][0]["offset"] == pytest.approx(1.0, abs=0.01)
    assert body["clip"]["duration"] > 0
    assert body["subjects"][0]["actor_role"] == "unknown"
    assert body["subjects"][0]["kind"] == "person"
    assert body["tracks"] == [
        {"tag": "T1", "phrase": "person", "class": "person", "upper_color": "white",
         "lower_color": "black", "vehicle_color": None, "vehicle_body": None, "carrying": [],
         "from": pytest.approx(1.0, abs=0.01), "to": pytest.approx(4.0, abs=0.01)}
    ]  # fmt: skip
    assert tagged.status_code == 200
    assert tagged.headers["content-type"] == "video/mp4"
    assert str(home["root"]) not in response.text


def test_capture_analysis_absent_and_traversal_refused(home):
    with _client(home) as api:
        assert api.get(f"/api/ui/captures/{home['second']}/analysis").status_code == 404
        for bad in ("..%2F..%2Fcameras", "porch_1.mp4", "a" * 80):
            response = api.get(f"/api/ui/captures/{home['first']}/tagged/{bad}")
            assert response.status_code in {400, 404}, bad
    with _client(home, ip="203.0.113.7") as api:
        assert api.get(f"/api/ui/captures/{home['first']}/analysis").status_code == 403


def test_masked_view_serves_only_masked_parts_for_recording(home, monkeypatch):
    """Recording a public video: VIGIL_MASKED_VIEW=1 never serves the unmasked ring clip."""
    monkeypatch.setenv("VIGIL_MASKED_VIEW", "1")
    masked = home["root"] / "windows" / home["first"] / "part-001.mp4"
    with _client(home) as api:
        rows = api.get("/api/ui/captures").json()["captures"]
        clip = api.get(f"/api/ui/captures/{home['first']}/clip")
    assert all(r["masked"] is not False for r in rows)
    assert clip.status_code == 200
    assert clip.content == masked.read_bytes()


def test_capture_analysis_links_the_merged_two_camera_moment(home):
    """A clip that was merged with another camera's clip shows the combined story (moments)."""
    import json

    _analysis(home)
    moment = "moment-0123456789abcdef"
    (home["root"] / "windows" / moment).mkdir(parents=True)
    (home["root"] / "windows" / moment / "session.json").write_text(
        json.dumps({"merged_from": [home["first"], home["second"]]}), encoding="utf-8"
    )
    (home["root"] / "results" / moment).mkdir(parents=True)
    (home["root"] / "results" / moment / "visits.json").write_text(json.dumps({
        "tracks": [{"id": "porch-person-1", "camera_id": "porch"},
                   {"id": "doorbell-person-1", "camera_id": "doorbell"}],
        "visits": [{"verdict": "cant_confirm", "story_source": "wonder", "story": [
            {"text": "A person crossed from Porch to Front door.", "source": "wonder"}]}],
    }), encoding="utf-8")  # fmt: skip
    with _client(home) as api:
        body = api.get(f"/api/ui/captures/{home['first']}/analysis").json()
    assert body["moment"] == {
        "id": moment,
        "clips": [home["first"], home["second"]],
        "cameras": ["doorbell", "porch"],
        "verdict": "cant_confirm",
        "story": ["A person crossed from Porch to Front door."],
    }


def test_capture_analysis_without_a_moment_says_none(home):
    _analysis(home)
    with _client(home) as api:
        assert api.get(f"/api/ui/captures/{home['first']}/analysis").json()["moment"] is None


# --- crop to the property, subject box and crop (UI redesign, Nov 4) ----------------------


def _zoned(home) -> None:
    """Give the porch a street strip (perimeter) and a yard, keeping its review valid."""
    data = yaml.safe_load(home["config"].read_text(encoding="utf-8"))
    for cam in data["cameras"]:
        if cam["id"] == "porch":
            cam["zones"] = {
                "street": [[0, 60], [1280, 60], [1280, 200], [0, 200]],
                "yard": [[0, 200], [1280, 200], [1280, 720], [0, 720]],
            }
            cam["zone_kinds"] = {"street": "perimeter", "yard": "interior_yard"}
            camera = CameraCfg(**cam)
            cam["privacy_polygons_sha256"] = privacy_digest(camera, camera.privacy)
    home["config"].write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _overlay(home, offset: float = 0.1) -> float:
    """Add SAM boxes to the analysed capture: one in the yard, one on the street strip."""
    import json

    _analysis(home)
    t = _clip_start(home) + offset  # seconds after the served clip starts
    results = home["root"] / "results" / home["first"] / "visits.json"
    visits = json.loads(results.read_text(encoding="utf-8"))
    yard = {"box": [100, 300, 200, 700], "cls": "person", "track_id": "porch-person-1"}
    street = {"box": [500, 20, 560, 150], "cls": "person", "track_id": "porch-person-2"}
    visits["overlays"] = {"cameras": {"porch": {"width": 1280, "height": 720, "frames": [
        {"t": t, "objects": [yard, street]},
    ]}}}  # fmt: skip
    visits["tracks"].append({"id": "porch-person-2", "phrase": "person", "tag": "T2",
                             "camera_id": "porch", "t_first": t, "t_last": t})  # fmt: skip
    visits["events"].append({"id": "e2", "t0": _clip_start(home) + 2.6, "type": "enter",
                             "track_id": "porch-person-1", "target": "yard"})  # fmt: skip
    results.write_text(json.dumps(visits), encoding="utf-8")
    return t


def test_capture_crop_follows_the_privacy_mask_only_when_masked(home, monkeypatch):
    with _client(home) as api:
        raw = next(r for r in api.get("/api/ui/captures").json()["captures"]
                   if r["id"] == home["first"])  # fmt: skip
    assert raw["crop"] is None
    assert raw["crop_top"] == 0
    assert raw["frame_aspect"] == pytest.approx(1280 / 720, abs=1e-3)
    monkeypatch.setenv("VIGIL_MASKED_VIEW", "1")
    with _client(home) as api:
        rows = {r["id"]: r for r in api.get("/api/ui/captures").json()["captures"]}
    masked = rows[home["first"]]
    # Rows 0..60 of 720 are masked (plus the mask's safety margin): measured from the pixels.
    assert 0.08 <= masked["crop"]["y0"] <= 0.15
    assert (masked["crop"]["x0"], masked["crop"]["x1"], masked["crop"]["y1"]) == (0.0, 1.0, 1.0)
    assert masked["crop_top"] == masked["crop"]["y0"]
    assert rows[home["door"]]["crop"]["y0"] == 0.0  # never reviewed, nothing masked
    assert (home["root"] / "ui" / "views" / f"{home['first']}.json").is_file()


def test_capture_crop_uses_the_measured_mask_over_todays_config(home, monkeypatch):
    """A part cut before a polygon change keeps its old, larger mask: the pixels decide."""
    import json

    monkeypatch.setenv("VIGIL_MASKED_VIEW", "1")
    views = home["root"] / "ui" / "views"
    views.mkdir(parents=True)
    old = {"x0": 0.0, "y0": 0.5, "x1": 1.0, "y1": 1.0}
    (views / f"{home['first']}.json").write_text(json.dumps(old), encoding="utf-8")
    with _client(home) as api:
        rows = {r["id"]: r for r in api.get("/api/ui/captures").json()["captures"]}
    assert rows[home["first"]]["crop"] == old


def test_capture_subject_never_points_outside_the_served_clip(home):
    """A box from before the served clip would sit on a frame where the person is not."""
    _zoned(home)
    _overlay(home, offset=-5.0)
    with _client(home) as api:
        row = next(r for r in api.get("/api/ui/captures").json()["captures"]
                   if r["id"] == home["first"])  # fmt: skip
    assert row["subject"] is None


def test_capture_subject_is_a_person_inside_the_property(home):
    _zoned(home)
    _overlay(home)
    with _client(home) as api:
        row = next(r for r in api.get("/api/ui/captures").json()["captures"]
                   if r["id"] == home["first"])  # fmt: skip
        subject = row["subject"]
        assert subject["track_id"] == "porch-person-1"  # the street-strip person is skipped
        assert subject["label"] == "T1 person"
        assert subject["t"] == pytest.approx(0.1, abs=0.01)
        assert subject["box"] == pytest.approx([100 / 1280, 300 / 720, 200 / 1280, 700 / 720],
                                               abs=1e-3)  # fmt: skip
        image = api.get(subject["image_url"])
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"
        assert image.content[:2] == b"\xff\xd8"
        analysis = api.get(f"/api/ui/captures/{home['first']}/analysis").json()
        assert analysis["zones"] == [
            {"tag": "T1", "path": [{"zone": "yard", "kind": "interior_yard",
                                    "at": pytest.approx(2.6, abs=0.01)}]}
        ]  # fmt: skip
    assert next(iter(home["root"].glob("appearance/crops/subject__*.jpg"))).is_file()


def test_capture_subject_absent_without_zones_and_ids_validated(home):
    _overlay(home)  # porch has no zones: nothing proves the person is inside the property
    with _client(home) as api:
        row = next(r for r in api.get("/api/ui/captures").json()["captures"]
                   if r["id"] == home["first"])  # fmt: skip
        assert row["subject"] is None
        assert api.get(f"/api/ui/captures/{home['first']}/subject.jpg").status_code == 404
        assert api.get("/api/ui/captures/..%2F..%2Fx/subject.jpg").status_code in {400, 404}
    with _client(home, ip="203.0.113.7") as api:
        assert api.get(f"/api/ui/captures/{home['first']}/subject.jpg").status_code == 403


def test_real_only_state_serves_nothing_from_the_demo_bundle(home, monkeypatch):
    """Owner decision Nov 4: the home box shows only this home's recordings."""
    monkeypatch.setenv("VIGIL_REAL_ONLY", "1")
    _analysis(home)
    with _client(home) as api:
        state = api.get("/api/ui/state").json()
        rows = {r["id"]: r for r in api.get("/api/ui/captures").json()["captures"]}
    assert state["real_only"] is True
    assert state["evidence"]["kind"] == "real"
    assert state["visits"] == state["clips"] == state["notifications"] == []
    assert state["events"] == state["camera_events"] == []
    assert state["summary"]["motion_triggers"] == len(rows)
    assert state["summary"]["visits"] == 1
    assert state["summary"]["needs_attention"] == 0
    assert rows[home["first"]]["verdict"] == "cant_confirm"
    assert rows[home["first"]]["headline"] == "At 5:07 PM, a person entered the view of Porch."


def test_real_only_chat_answers_from_the_home_clips(home, monkeypatch):
    monkeypatch.setenv("VIGIL_REAL_ONLY", "1")
    _analysis(home)
    with _client(home) as api:
        body = {"thread_id": "ask-home", "text": "Who entered the porch?", "session_id": "s"}
        message = api.post("/api/chat/ask", json=body).json()["message"]
    assert message["text"] == "At 5:07 PM, a person entered the view of Porch."
    assert message["citations"] == [
        {"capture_id": home["first"], "event_id": "e1", "label": "Porch"}
    ]


def test_demo_state_is_unchanged_without_real_only(home, monkeypatch):
    monkeypatch.delenv("VIGIL_REAL_ONLY", raising=False)
    with _client(home) as api:
        state = api.get("/api/ui/state").json()
    assert state["real_only"] is False
    assert state["visits"]  # the bundle still serves the tests and the judges' sandbox


def test_real_only_chat_threads_say_answers_come_from_the_home_clips(home, monkeypatch):
    monkeypatch.setenv("VIGIL_REAL_ONLY", "1")
    with _client(home) as api:
        chat = api.get("/api/ui/chat").json()
    assert chat["evidence"]["kind"] == "real"
    assert chat["threads"][0]["note"] == "Answers come from your analysed clips."


def test_real_only_bell_lists_clips_whose_rule_raised_an_alert(home, monkeypatch):
    """A carried-object rule hit on a real clip reaches the bell; the story is the code's."""
    import json

    monkeypatch.setenv("VIGIL_REAL_ONLY", "1")
    _analysis(home)
    path = home["root"] / "results" / home["first"] / "visits.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["visits"][0]["verdict"] = "needs_attention"
    path.write_text(json.dumps(data), encoding="utf-8")
    with _client(home) as api:
        state = api.get("/api/ui/state").json()
    (notice,) = state["notifications"]
    assert notice["capture_id"] == home["first"]
    assert notice["visit_id"] is None
    assert notice["verdict"] == "needs_attention"
    assert notice["story"] == "At 5:07 PM, a person entered the view of Porch."
    assert state["summary"]["needs_attention"] == 1


def test_capture_analysis_names_the_rule_and_the_carried_object(home):
    import json

    _analysis(home)
    path = home["root"] / "results" / home["first"] / "visits.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    carry = {**data["events"][0], "id": "e9", "type": "carry", "target": "knife"}
    data["events"].append(carry)
    data["visits"][0]["verdict"] = "needs_attention"
    data["visits"][0]["rule_hits"] = [
        {"rule_id": "r_carried_object", "visit_id": "v1", "event_id": "e9"}
    ]
    path.write_text(json.dumps(data), encoding="utf-8")
    with _client(home) as api:
        body = api.get(f"/api/ui/captures/{home['first']}/analysis").json()
    (alert,) = body["alerts"]
    assert alert["rule"] == "Possible knife or gun carried by a non-household person"
    assert alert["object"] == "knife"
    assert alert["type"] == "carry"
    assert alert["event_id"] == "e9"
