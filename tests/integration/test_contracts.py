"""Cross-module contracts the workstreams flagged (integration; offline, no network).

(a) mask encoding: SAM masks from vigil.meta.sam / perception decode in vigil.spatial.locate;
(b) event target conventions used by rules and visits;
(c) event ids are opaque (no ``e\\d+`` assumption) in validator, templates, loop and API;
(d) the API's live backend reads MetaClient's CallLedger (len / since), not only lists;
(e) the API serves a bundle exported from a pipeline result (scenario C);
plus the pipeline's own edges: the pre-upload privacy check and the blocked CLI entry.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import respx
from fastapi.testclient import TestClient

from tests.fixtures.scenarios.builders import (
    PDT,
    SCENARIOS,
    Subject,
    _c_retry,
    make_window,
    run_golden,
    sam_text,
)
from tests.fixtures.video.synth import blob_clip
from vigil.ingest.privacy import PrivacyViolation, mask_clip
from vigil.meta.sam import PointMask, parse_video_output
from vigil.models import (
    Box,
    CameraCfg,
    Config,
    Event,
    Gap,
    ModelCall,
    ProtectedObject,
    Rule,
    Track,
    TrackFrame,
    Visit,
    VisitLedger,
    Watch,
    WatchProposal,
    Window,
)
from vigil.perception.events import build_events
from vigil.perception.rle import decode_rle, encode_rle
from vigil.perception.tracks import stitch
from vigil.pipeline import bundle_trace, process_session, store_result, upload_window
from vigil.reasoning.loop import accept_watches, load_allowlist
from vigil.reasoning.rules import evaluate_rules, load_rules
from vigil.reasoning.templates import template_story
from vigil.reasoning.topology import exit_leads_to_blind
from vigil.reasoning.validator import validate
from vigil.settings import Settings
from vigil.spatial.geometry import rle_decode, rle_encode
from vigil.spatial.locate import foot_point

SENTINEL_KEY = "sk-vigil-contract-sentinel"


def _rules(rule_r7: Rule) -> list[Rule]:
    return [*load_rules(), rule_r7]


# ---------------------------------------------------------------------------
# (a) mask encoding
# ---------------------------------------------------------------------------


def _parsed_person() -> tuple[Window, list]:
    w = make_window("side_left", 8.0, 18.0)
    subj = Subject("side_left", "person", ((8.0, 400, 640), (17.8, 500, 640)), 60, 200)
    return w, parse_video_output(sam_text(w, [subj], "person"), w, "person")


def test_contract_sam_object_carries_frame_size() -> None:
    w, objs = _parsed_person()
    (obj,) = objs
    assert (obj.width, obj.height) == (w.width, w.height) == (1280, 720)


def test_contract_mask_rle_agrees_between_perception_and_spatial() -> None:
    _, (obj,) = _parsed_person()
    f = obj.frames[0]
    assert f.mask_rle
    a = decode_rle(f.mask_rle, 720, 1280)
    b = rle_decode(f.mask_rle, 720, 1280)
    assert a.shape == b.shape == (720, 1280)
    assert np.array_equal(a, b)
    assert a.any()
    # the same COCO counts string comes back from either encoder
    assert encode_rle(a) == rle_encode(a) == f.mask_rle
    # the JSON {size, counts} form decodes to the same mask
    as_json = json.dumps({"size": [720, 1280], "counts": f.mask_rle})
    assert np.array_equal(rle_decode(as_json, 0, 0), a)
    # the mask sits inside its box (full-frame placement, not box-local)
    ys, xs = np.nonzero(a)
    assert f.box.x1 <= xs.min()
    assert xs.max() < f.box.x2
    assert f.box.y1 <= ys.min()
    assert ys.max() < f.box.y2


def test_contract_stitched_mask_feeds_locate_foot_point() -> None:
    _, objs = _parsed_person()
    (track,) = stitch(objs)
    assert track.phrase == "person"
    frame = track.frames[0]
    fp = foot_point(frame, 1280, 720)
    assert fp.from_mask
    assert not fp.clipped
    cx = (frame.box.x1 + frame.box.x2) / 2
    assert abs(fp.foot[0] - cx) <= 2.0
    assert frame.box.y2 - 2.0 <= fp.foot[1] < frame.box.y2


# ---------------------------------------------------------------------------
# (b) event target conventions
# ---------------------------------------------------------------------------


def test_contract_event_targets(sample_config: Config, po_side_gate, rule_r7) -> None:
    sc = SCENARIOS["C"]()
    result = run_golden(sc, sample_config, _rules(rule_r7), [po_side_gate], spatial=False)
    cam = sample_config.camera("side_left")
    for e in result["events"]:
        if e["type"] in ("enter", "exit", "dwell"):
            assert e["target"] in cam.zones or e["target"] in cam.exits, e
        elif e["type"] == "touch":
            assert e["target"] == po_side_gate.id
        elif e["type"] == "cross":
            assert e["target"] in cam.lines
    first = min((t for t in result["tracks"]), key=lambda t: t["t_first"])
    exits = [e for e in result["events"] if e["track_id"] == first["id"] and e["type"] == "exit"]
    last_exit = max(exits, key=lambda e: e["t0"])
    assert last_exit["target"] == "to_shed_back"  # an exit polygon key ...
    assert exit_leads_to_blind(sample_config, "side_left", last_exit["target"]) == "shed_back"


def _box_frames(t0: float, t1: float, box: Box, step: float = 0.2) -> list[TrackFrame]:
    n = round((t1 - t0) / step)
    return [TrackFrame(t=round(t0 + i * step, 6), box=box) for i in range(n + 1)]


def test_contract_removed_event_targets_watch_id_and_rule_matches_phrase(
    sample_config: Config,
) -> None:
    pkg_box = Box(x1=600, y1=600, x2=660, y2=650)
    package = Track(
        id="front-package-1",
        camera_id="front",
        cls="package",
        t_first=0.0,
        t_last=10.0,
        frames=_box_frames(0.0, 10.0, pkg_box),
        phrase="package",
    )
    person = Track(
        id="front-person-1",
        camera_id="front",
        cls="person",
        t_first=8.0,
        t_last=15.0,
        frames=_box_frames(8.0, 15.0, Box(x1=590, y1=480, x2=650, y2=660)),
        phrase="person",
    )
    watch = Watch(
        id="w_pkg_opaque", camera_id="front", phrase="package", origin="wonder", status="watching"
    )
    events = build_events([package, person], sample_config, [], [watch], exits_as_zones=True)
    removed = [e for e in events if e.type == "removed"]
    assert len(removed) == 1
    assert removed[0].target == watch.id  # removed -> watch id
    assert removed[0].track_id == person.id
    visit = Visit(id="v9", t0=0.0, t1=15.0, event_ids=[e.id for e in events])
    rr = evaluate_rules(
        visit,
        events,
        load_rules(),
        "America/Los_Angeles",
        datetime(2026, 10, 30, 18, 0, tzinfo=PDT),
        watches=[watch],
    )
    assert [h.rule_id for h in rr.hits] == ["r_package_removed"]
    assert rr.floor == "needs_attention"


# ---------------------------------------------------------------------------
# (c) event ids are opaque
# ---------------------------------------------------------------------------


def test_contract_event_ids_are_opaque(sample_config: Config, po_side_gate, rule_r7) -> None:
    sc = SCENARIOS["C"]()
    result = run_golden(sc, sample_config, _rules(rule_r7), [po_side_gate], spatial=False)
    (v,) = result["visits"]
    rename = {eid: f"evt:{i:03d}/{eid[::-1]}#Δ" for i, eid in enumerate(v["event_ids"])}
    events = [
        Event.model_validate({**e, "id": rename[e["id"]]}) for e in v["events"] if e["id"] in rename
    ]
    visit = Visit.model_validate({k: v[k] for k in Visit.model_fields}).model_copy(
        update={"event_ids": [rename[e] for e in v["event_ids"]], "story": []}
    )
    ledger = VisitLedger(
        visit=visit,
        events=events,
        gaps=[Gap.model_validate(g) for g in v["gaps"]],
        protected_objects=[po_side_gate],
        camera_names={c.id: c.name for c in sample_config.cameras},
        session_start=sc.session_start,
    )
    draft = _c_retry(ledger)
    cited = {eid for s in draft["sentences"] for eid in s["event_ids"]}
    assert cited
    assert all(eid.startswith("evt:") for eid in cited)
    res = validate(draft, ledger)
    assert res.passed, res.failures
    sentences = template_story(ledger)
    assert sentences
    assert all(set(s.event_ids) <= set(visit.event_ids) for s in sentences)
    loop = accept_watches(
        [WatchProposal(camera_id="side_left", phrase="ladder", reason_event_id=events[0].id)],
        [c.id for c in sample_config.cameras],
        load_allowlist(),
        [],
        datetime(2026, 10, 30, 22, 20, tzinfo=PDT),
        visit.id,
        validated=True,
        visit_event_ids=set(visit.event_ids),
    )
    assert len(loop.accepted) == 1


# ---------------------------------------------------------------------------
# (d) MetaClient ledger and the API live backend
# ---------------------------------------------------------------------------


def test_contract_api_backend_reads_call_ledger(tmp_path: Path, monkeypatch) -> None:
    from vigil.api.backend import MetaLiveBackend, _calls_since
    from vigil.meta import sam as sam_mod
    from vigil.meta.client import CallLedger, MetaClient

    settings = Settings(cache_dir=tmp_path / "cache", MODEL_API_KEY=SENTINEL_KEY)
    client = MetaClient(settings=settings, ledger=CallLedger())
    try:
        old = ModelCall(id="call_old", model="sam-3.1", purpose="sam_track", req_hash="h0")
        client.ledger.add(old)
        assert len(client.ledger) == 1
        assert not isinstance(client.ledger, list)

        stills = tmp_path / "stills"
        stills.mkdir()
        (stills / "side_left.jpg").write_bytes(b"not decoded by the fake")

        def fake_segment_point(c: Any, still: Path, x: int, y: int) -> PointMask:
            assert c is client
            c.ledger.add(
                ModelCall(id="call_new", model="sam-3.1", purpose="segment_point", req_hash="h1")
            )
            return PointMask(
                obj_id=1, box=Box(x1=800, y1=400, x2=880, y2=660), mask_rle="0", width=1, height=1
            )

        monkeypatch.setattr(sam_mod, "segment_point", fake_segment_point)
        backend = MetaLiveBackend(settings, stills)
        backend._client = client
        assert backend._ledger_len(client) == 1
        res = backend.protect("side_left", None, 840.0, 500.0, "side gate")
        assert [c.id for c in res.calls] == ["call_new"]
        assert [c.id for c in _calls_since(client, 0)] == ["call_old", "call_new"]
    finally:
        client.close()


def test_contract_api_backend_still_accepts_a_plain_list() -> None:
    from vigil.api.backend import _calls_since

    class ListClient:
        def __init__(self) -> None:
            self.ledger = [
                ModelCall(id="a", model="sam-3.1", purpose="sam_track", req_hash="x"),
                {"id": "b", "model": "sam-3.1", "purpose": "sam_track", "req_hash": "y"},
            ]

    assert [c.id for c in _calls_since(ListClient(), 1)] == ["b"]


# ---------------------------------------------------------------------------
# (e) the API serves a bundle exported from the pipeline (scenario C)
# ---------------------------------------------------------------------------


def test_contract_api_serves_pipeline_bundle_for_c(
    tmp_path: Path, sample_config: Config, po_side_gate: ProtectedObject, rule_r7: Rule
) -> None:
    from vigil.api.app import create_app
    from vigil.store.export import export_bundle

    sc = SCENARIOS["C"]()
    rules = _rules(rule_r7)
    result = run_golden(sc, sample_config, rules, [po_side_gate])
    db_path = store_result(
        tmp_path / "vigil.db", result, cfg=sample_config, rules=rules, protected=[po_side_gate]
    )
    bundle_dir = export_bundle(
        tmp_path / "bundle",
        db_path,
        config=sample_config,
        trace=bundle_trace(result),
        eval_results={"status": "not measured", "metrics": []},
        meta={
            "synthetic": True,
            "label": "Golden scenario C (synthetic)",
            "session_start": sc.session_start.isoformat(),
            "timezone": sample_config.timezone,
            "scenario_titles": {"C": sc.title},
        },
    )
    (v,) = result["visits"]
    settings = Settings(mode="sandbox", MODEL_API_KEY=SENTINEL_KEY)
    with (
        respx.mock(assert_all_called=False),
        TestClient(create_app(settings, bundle_dir=bundle_dir)) as client,
    ):
        r = client.get(f"/api/visits/{v['id']}")
        assert r.status_code == 200
        body = r.json()
        sc_r = client.get("/api/scenarios/C")
        assert sc_r.status_code == 200
        pos = client.get(f"/api/visits/{v['id']}/positions")
        assert pos.status_code == 200
    assert body["verdict"] == "needs_attention"
    assert body["escalated"] is True
    (gap,) = body["gaps"]
    assert gap["region_name"] == "behind the shed"
    assert round(gap["duration_s"]) == 41
    assert gap["label"] == "Not observed · 41 s"
    assert {h["rule_id"] for h in body["rule_hits"]} == {"r7"}
    assert body["rule_hits"][0]["rule_name"] == rule_r7.name

    story = {i: s for i, s in enumerate(v["story"])}
    assert len(body["sentences"]) == len(story)
    for item in body["sentences"]:
        s = story[item["index"]]
        if s["source"] == "code":
            assert item["gap"]["id"] == gap["id"]
            assert item["citations"] == []
            assert item["badge"]["kind"] == "code"
        else:
            # every citation chip resolves to an event of this visit (opaque hash ids)
            assert [c["event_id"] for c in item["citations"]] == s["event_ids"]
            assert item["citations"]
    touch = next(c for c in body["events"] if c["type"] == "touch")
    assert touch["clock"].startswith("10:14:")
    drafts = body["trace"]["drafts"]
    assert [d["passed"] for d in drafts] == [False, True]
    assert "uncited" in {f["check"] for f in drafts[0]["failures"]}
    assert body["trace"]["triage"]["forced"] is True
    positions = pos.json()
    assert json.dumps(positions)  # serialisable; positions endpoint answers for C


# ---------------------------------------------------------------------------
# Pipeline edges: pre-upload privacy check (spec 5.8) and the blocked CLI entry
# ---------------------------------------------------------------------------


class FakeUploadClient:
    def __init__(self) -> None:
        self.uploads: list[Path] = []

    def upload(self, path: Path) -> str:
        self.uploads.append(Path(path))
        return f"file_{len(self.uploads)}"


def test_upload_window_checks_privacy_before_upload(tmp_path: Path) -> None:
    cam = CameraCfg(
        id="side_left",
        name="Left side",
        width=320,
        height=180,
        privacy=[[(0, 0), (80, 0), (80, 180), (0, 180)]],
    )
    raw = blob_clip(tmp_path / "raw.mp4", 1.0, size=(320, 180))
    masked = mask_clip(raw, tmp_path / "masked.mp4", cam.privacy, ref_size=(320, 180))
    client = FakeUploadClient()

    unmasked = Window(id="side_left_000000000", camera_id="side_left", t0=0, t1=1, path=str(raw))
    with pytest.raises(PrivacyViolation):
        upload_window(client, unmasked, cam)
    assert client.uploads == []
    assert unmasked.file_id is None

    clean = Window(id="side_left_000000000", camera_id="side_left", t0=0, t1=1, path=str(masked))
    assert upload_window(client, clean, cam) == "file_1"
    assert clean.file_id == "file_1"
    assert client.uploads == [masked]
    # already uploaded: no second upload
    assert upload_window(client, clean, cam) == "file_1"
    assert len(client.uploads) == 1


def test_upload_window_without_a_file_is_refused(tmp_path: Path) -> None:
    cam = CameraCfg(id="front", name="Front entrance")
    with pytest.raises(ValueError, match="no file"):
        upload_window(FakeUploadClient(), Window(id="w", camera_id="front", t0=0, t1=1), cam)


def test_process_session_blocked_without_windows(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    with pytest.raises(RuntimeError, match=r"^blocked: ") as ei:
        process_session("evening-1", settings=settings)
    assert "T-07" in str(ei.value)


def _write_session(data: Path, session: str, sc, *, sam: bool, extra: dict | None = None) -> None:
    wdir = data / "windows" / session
    wdir.mkdir(parents=True)
    (wdir / "windows.json").write_text(
        json.dumps([w.model_dump(mode="json") for w in sc.windows]), encoding="utf-8"
    )
    meta = {"session_start": sc.session_start.isoformat(), **(extra or {})}
    (wdir / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    if sam:
        for wid, by_phrase in sc.sam_outputs().items():
            for phrase, text in by_phrase.items():
                p = data / "sam" / session / wid / f"{phrase}.txt"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8", newline="\n")


def test_process_session_blocked_without_recorded_sam(tmp_path: Path) -> None:
    data = tmp_path / "data"
    _write_session(data, "evening-1", SCENARIOS["C"](), sam=False)
    with pytest.raises(RuntimeError, match=r"^blocked: ") as ei:
        process_session("evening-1", settings=Settings(data_dir=data))
    msg = str(ei.value)
    assert "H-02" in msg
    assert "credits" in msg


def test_process_session_runs_offline_on_recorded_sam(
    tmp_path: Path, po_side_gate: ProtectedObject, rule_r7: Rule
) -> None:
    data = tmp_path / "data"
    extra = {
        "protected_objects": [po_side_gate.model_dump(mode="json")],
        "rules": [rule_r7.model_dump(mode="json")],
    }
    _write_session(data, "evening-1", SCENARIOS["C"](), sam=True, extra=extra)
    with respx.mock(assert_all_called=False):  # nothing may touch the network
        result = process_session("evening-1", settings=Settings(data_dir=data))
    (v,) = result["visits"]
    assert v["verdict"] == "needs_attention"
    assert {h["rule_id"] for h in v["rule_hits"]} == {"r7"}
    assert v["story_source"] == "template"  # no Wonder offline: template plus gap sentence
    assert any(s["source"] == "code" for s in v["story"])
    out = data / "results" / "evening-1" / "visits.json"
    assert json.loads(out.read_text(encoding="utf-8"))["visits"][0]["id"] == v["id"]


# ---------------------------------------------------------------------------
# Pipeline result -> EVAL metrics: instantaneous events on a gap boundary
# ---------------------------------------------------------------------------


def test_contract_metrics_boundary_event_is_not_a_claim_inside_gap() -> None:
    """build_events emits instants (t0 == t1); the exit that opens a gap sits on its start."""
    from vigil.eval.metrics import compute_metrics

    label = {
        "scenario": "C",
        "expected_verdict": "needs_attention",
        "gaps": [{"id": "g1", "kind": "blind_spot", "t0": 40.0, "t1": 81.0}],
    }

    def result(t: float) -> dict[str, Any]:
        return {
            "scenario": "C",
            "visits": [
                {
                    "id": "v1",
                    "verdict": "needs_attention",
                    "story": [{"text": "They walked out of view.", "event_ids": ["ex"]}],
                    "events": [{"id": "ex", "camera_id": "side_left", "t0": t, "t1": t}],
                    "gaps": [{"id": "g1", "t0": 40.0, "t1": 81.0}],
                }
            ],
        }

    for t in (40.0, 81.0):  # the moment they left / came back: on the boundary, not inside
        assert compute_metrics([label], [result(t)])["totals"]["claims_inside_gaps"] == 0
    assert compute_metrics([label], [result(55.0)])["totals"]["claims_inside_gaps"] == 1
