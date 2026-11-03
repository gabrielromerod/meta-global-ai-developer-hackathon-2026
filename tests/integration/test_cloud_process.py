"""Full production cloud adapters over authored HTTP fixtures and generated video.

FIXTURE, not recorded Meta acceptance. respx rejects every unmocked HTTP request.
"""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from vigil.ingest.privacy import mask_clip, verify_clean
from vigil.meta.budget import ConfirmRequired
from vigil.meta.client import CallLedger, MetaClient
from vigil.models import Window
from vigil.pipeline import process_session
from vigil.settings import Settings, ffmpeg_bin
from vigil.store import db

FIXTURES = Path(__file__).parents[1] / "fixtures" / "meta"


def generated_session(tmp_path):
    raw = tmp_path / "generated.mp4"
    subprocess.run(
        [
            ffmpeg_bin(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=10:duration=4",
            "-f",
            "lavfi",
            "-i",
            "color=white:size=40x100:rate=10:duration=4",
            "-filter_complex",
            "[0:v][1:v]overlay=x='80+38*t':y=500:shortest=1",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(raw),
        ],
        check=True,
        capture_output=True,
    )
    polys = [[(0, 0), (1280, 0), (1280, 60), (0, 60)]]
    config = tmp_path / "cameras.yaml"
    config.write_text(
        json.dumps(
            {
                "evidence_kind": "fixture",
                "cameras": [
                    {
                        "id": "side_left",
                        "name": "Left side",
                        "privacy": polys,
                        "zones": {"yard": [[0, 0], [1280, 0], [1280, 720], [0, 720]]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    wdir = tmp_path / "data" / "windows" / "generated"
    wdir.mkdir(parents=True)
    clip = mask_clip(raw, wdir / "w.mp4", polys, ref_size=(1280, 720))
    w = Window(id="w0", camera_id="side_left", t0=0, t1=4, path=str(clip), trigger="manual")
    (wdir / "windows.json").write_text(json.dumps([w.model_dump()]), encoding="utf-8")
    (wdir / "session.json").write_text(
        json.dumps({"session_start": "2026-11-03T10:00:00-08:00"}), encoding="utf-8"
    )
    settings = Settings(
        _env_file=None,
        MODEL_API_KEY="invalid-fixture-key",
        data_dir=tmp_path / "data",
        config_path=config,
        cache_dir=tmp_path / "cache",
        db_path=tmp_path / "result.db",
        ledger_path=tmp_path / "ledger.db",
        credit_window_end="2026-11-05T00:00:00Z",
    )
    return settings, polys


def mock_models(router, *, saturated=False, propose_watch=False):
    calls = []
    uploads = []

    def upload(request):
        uploads.append(request)
        return httpx.Response(200, json={"id": f"file_synthetic_{len(uploads)}"})

    router.post("https://api.meta.ai/v1/files").mock(side_effect=upload)

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["model"] == "sam-3.1":
            phrase = body["input"][0]["content"][0]["text"]
            text = "\n".join((FIXTURES / "sam_person_w0.txt").read_text().splitlines()[:10])
            if saturated and len(calls) == 1:
                text = (FIXTURES / "sam_16ids.txt").read_text()
            response = {"status": "completed", "output_text": text if phrase == "person" else ""}
            return httpx.Response(
                200,
                text="data: "
                + json.dumps({"type": "response.completed", "response": response})
                + "\n\n",
            )
        name = body["text"]["format"]["name"]
        if name == "appearance_notes":
            tags = body["text"]["format"]["schema"]["properties"]["tracks"]["items"]["properties"][
                "tag"
            ]["enum"]
            answer = {
                "tracks": [
                    {
                        "tag": t,
                        "class": "person",
                        "upper_color": "navy",
                        "lower_color": "grey",
                        "carrying": [],
                        "vehicle_color": None,
                        "vehicle_body": None,
                    }
                    for t in tags
                ]
            }
        elif name == "triage":
            answer = {"escalate": True, "reason": "Synthetic fixture requests review"}
        else:
            ledger = json.loads(body["input"][0]["content"][0]["text"].split("\n", 1)[1])
            answer = {
                "verdict_proposal": "noteworthy",
                "sentences": [
                    {"text": "Movement was observed.", "event_ids": [ledger["events"][0]["id"]]}
                ],
                "gap_after_sentence": [],
                "watch_proposals": [],
            }
            if propose_watch:
                answer["watch_proposals"] = [
                    {
                        "camera_id": "side_left",
                        "phrase": "package",
                        "reason_event_id": ledger["events"][0]["id"],
                    }
                ]
        return httpx.Response(200, json={"status": "completed", "output_text": json.dumps(answer)})

    router.post("https://api.meta.ai/v1/responses").mock(side_effect=respond)
    return calls


def test_process_cloud_end_to_end_generated_mp4(tmp_path):
    settings, polygons = generated_session(tmp_path)
    ledger = CallLedger(settings.ledger_path)
    with (
        respx.mock as router,
        MetaClient(
            settings,
            ledger=ledger,
            clock=lambda: datetime(2026, 11, 3, tzinfo=UTC),
            sleep=lambda _: None,
        ) as client,
    ):
        calls = mock_models(router)
        result = process_session("generated", settings=settings, client=client, confirm=True)
    assert {c["model"] for c in calls} == {"sam-3.1", "muse-spark-1.3", "muse-wonder-1.0"}
    assert result["sam_missing"] == []
    visit = result["visits"][0]
    assert visit["story_source"] == "wonder"
    assert visit["verdict"] == "noteworthy"
    assert all(v["passed"] for v in visit["validations"])
    assert result["cost_estimate"]["usd"] > 0
    assert len(ledger.rows()) >= 5
    tagged = list((settings.data_dir / "results" / "generated" / "tagged").glob("*.mp4"))
    assert tagged
    assert all(verify_clean(p, polygons, ref_size=(1280, 720)) for p in tagged)
    conn = db.connect(Path(result["db_path"]))
    try:
        assert db.rows(conn, "visits")[0]["verdict"] == "noteworthy"
        assert db.rows(conn, "model_calls")
        assert db.rows(conn, "appearance")
    finally:
        conn.close()


def test_sam_window_split_cloud_generated_mp4(tmp_path):
    settings, polygons = generated_session(tmp_path)
    with (
        respx.mock as router,
        MetaClient(
            settings,
            clock=lambda: datetime(2026, 11, 3, tzinfo=UTC),
            sleep=lambda _: None,
        ) as client,
    ):
        calls = mock_models(router, saturated=True)
        result = process_session("generated", settings=settings, client=client, confirm=True)
    assert len([c for c in calls if c["model"] == "sam-3.1"]) == 4
    splits = list((settings.data_dir / "results" / "generated" / "splits").glob("*.mp4"))
    assert len(splits) == 2
    assert all(verify_clean(p, polygons, ref_size=(1280, 720)) for p in splits)
    assert len(result["tracks"]) < 16


def test_cloud_confirm_before_upload(tmp_path):
    settings, _ = generated_session(tmp_path)
    reports = []
    with respx.mock as router, MetaClient(settings) as client:
        with pytest.raises(ConfirmRequired):
            process_session("generated", settings=settings, client=client, report=reports.append)
        assert len(router.calls) == 0
    assert "estimated cost:" in reports[0]


def test_watches_apply_to_later_windows_in_same_run(tmp_path):
    settings, _ = generated_session(tmp_path)
    wfile = settings.data_dir / "windows" / "generated" / "windows.json"
    windows = json.loads(wfile.read_text())
    windows.append({**windows[0], "id": "w1", "t0": 4, "t1": 8})
    wfile.write_text(json.dumps(windows), encoding="utf-8")
    with (
        respx.mock as router,
        MetaClient(
            settings,
            clock=lambda: datetime(2026, 11, 3, tzinfo=UTC),
            sleep=lambda _: None,
        ) as client,
    ):
        calls = mock_models(router, propose_watch=True)
        result = process_session("generated", settings=settings, client=client, confirm=True)
    package = [
        i
        for i, c in enumerate(calls)
        if c["model"] == "sam-3.1" and c["input"][0]["content"][0]["text"] == "package"
    ]
    assert len(package) == 1, "the accepted watch must reach the next window in this run"
    story = next(i for i, c in enumerate(calls) if c["model"] == "muse-wonder-1.0")
    assert package[0] > story
    assert len(result["watches"]["accepted"]) == 1
