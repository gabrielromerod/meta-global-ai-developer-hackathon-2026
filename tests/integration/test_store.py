"""Store and export (FR-023 ledger rows, FR-027 demo bundle, NFR-011 determinism)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from vigil.models import (
    ActiveWindow,
    CheckIn,
    Event,
    ExpectedWindow,
    Gap,
    ModelCall,
    Position,
    Rule,
    RuleTarget,
    StorySentence,
    Subject,
    Track,
    ValidationFailure,
    ValidationResult,
    Visit,
)
from vigil.store import db
from vigil.store.export import export_bundle, load_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = REPO_ROOT / "demo" / "synthetic"
CONTRIBUTOR = "-" + "contributor"


def _load_builder():
    spec = importlib.util.spec_from_file_location("vigil_synthetic_build", SYNTHETIC / "build.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tiny_db(path: Path) -> sqlite3.Connection:
    conn = db.open_db(path)
    db.insert_track(
        conn, Track(id="t1", camera_id="side_left", cls="person", t_first=1.0, t_last=9.0)
    )
    db.insert_event(
        conn,
        Event(
            id="e1",
            visit_id="v1",
            camera_id="side_left",
            track_id="t1",
            type="touch",
            t0=2.0,
            t1=3.0,
            target="po_side_gate",
            clip_t0=0.0,
            clip_t1=5.0,
        ),
    )
    db.insert_gap(
        conn,
        Gap(id="g1", visit_id="v1", kind="blind_spot", t0=4.0, t1=45.0, region_id="shed_back"),
    )
    db.insert_position(
        conn,
        Position(
            track_id="t1",
            t=2.0,
            x=6.1,
            y=0.0,
            z=2.8,
            r95=0.4,
            method="footpoint",
            cameras=["side_left"],
        ),
    )
    db.insert_visit(
        conn,
        Visit(
            id="v1",
            scenario="C",
            t0=1.0,
            t1=50.0,
            state="published",
            floor="needs_attention",
            verdict="needs_attention",
            escalated=True,
            story=[StorySentence(text="A person touched the side gate.", event_ids=["e1"])],
        ),
    )
    db.insert_model_call(
        conn,
        ModelCall(
            id="call_1",
            model="muse-wonder-1.0",
            purpose="story",
            visit_id="v1",
            req_hash="abc",
            latency_ms=1200,
            cost_usd=0.02,
            cached=True,
        ),
    )
    db.insert_validation(
        conn,
        "v1",
        ValidationResult(
            passed=False,
            attempt=1,
            failures=[ValidationFailure(check="uncited", sentence_index=0, detail="no id")],
        ),
    )
    conn.commit()
    return conn


def test_open_db_creates_every_schema_table(tmp_path: Path) -> None:
    conn = db.open_db(tmp_path / "x.db")
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"visits", "events", "gaps", "positions", "model_calls", "validations"} <= names
    # Re-opening an initialised DB must not fail (idempotent init).
    conn.close()
    db.open_db(tmp_path / "x.db").close()


def test_repository_round_trip(tmp_path: Path) -> None:
    conn = _tiny_db(tmp_path / "x.db")
    visit = db.get_visit(conn, "v1")
    assert visit is not None
    assert visit.verdict == "needs_attention"
    assert visit.escalated is True
    assert visit.event_ids == ["e1"]
    assert visit.gap_ids == ["g1"]
    assert visit.track_ids == ["t1"]
    assert visit.story[0].event_ids == ["e1"]
    assert db.events_for_visit(conn, "v1")[0].target == "po_side_gate"
    assert db.gaps_for_visit(conn, "v1")[0].duration_s == pytest.approx(41.0)
    pos = db.positions_for_tracks(conn, ["t1"])
    assert pos[0].cameras == ["side_left"]
    assert pos[0].method == "footpoint"
    calls = db.model_calls(conn, visit_id="v1")
    assert calls[0].cached is True
    assert calls[0].model == "muse-wonder-1.0"
    vals = db.validations_for_visit(conn, "v1")
    assert vals[0].failures[0].check == "uncited"
    assert db.get_visit(conn, "nope") is None


def test_insert_model_call_rejects_contributor_ids(tmp_path: Path) -> None:
    conn = db.open_db(tmp_path / "x.db")
    with pytest.raises(ValueError, match="NFR-004"):
        db.insert_raw(conn, "model_calls", {"id": "c", "model": "muse-spark-1.3" + CONTRIBUTOR})


def test_position_method_check_constraint(tmp_path: Path) -> None:
    conn = db.open_db(tmp_path / "x.db")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_raw(conn, "positions", {"track_id": "t", "method": "guess"})


# --- Nov 2 tables: subjects, expected windows, check-ins, funding (spec 9.3) ---------------


def test_subject_round_trip_and_role_check(tmp_path: Path) -> None:
    conn = db.open_db(tmp_path / "x.db")
    subj = Subject(id="s1", visit_id="v1", track_ids=["t1", "t2"],
                   actor_role="external_visitor", role_basis="perimeter:side_alley")  # fmt: skip
    db.insert_subject(conn, subj)
    assert db.subjects_for_visit(conn, "v1") == [subj]
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_raw(conn, "subjects", {"id": "s2", "actor_role": "neighbour"})


def test_track_origin_zone_and_event_role_persist(tmp_path: Path) -> None:
    conn = db.open_db(tmp_path / "x.db")
    track = Track(id="t1", camera_id="front", cls="person", t_first=1.0, t_last=4.0,
                  origin_zone="front_door_egress")  # fmt: skip
    db.insert_track(conn, track)
    row = db.rows(conn, "tracks")[0]
    assert row["origin_zone"] == "front_door_egress"
    ev = Event(id="e1", visit_id="v1", camera_id="front", track_id="t1", type="enter", t0=1.0,
               t1=2.0, clip_t0=0.0, clip_t1=5.0, subject_id="s1",
               actor_role="household_insider")  # fmt: skip
    db.insert_event(conn, ev)
    assert db.events_for_visit(conn, "v1") == [ev]


def test_expected_window_round_trip_and_cancel(tmp_path: Path) -> None:
    conn = db.open_db(tmp_path / "x.db")
    from datetime import datetime

    w = ExpectedWindow(id="w3", label="deliveries",
                       start=datetime.fromisoformat("2026-11-03T13:00:00-08:00"),
                       end=datetime.fromisoformat("2026-11-03T17:00:00-08:00"),
                       cameras=["front"], state="scheduled")  # fmt: skip
    db.insert_expected_window(conn, w, created_at="2026-11-03T09:00:00-08:00")
    assert db.expected_windows(conn) == [w]
    assert db.cancel_expected_window(conn, "w3") is True
    assert db.expected_windows(conn)[0].state == "cancelled"
    assert db.cancel_expected_window(conn, "nope") is False


def test_checkin_round_trip_and_binding(tmp_path: Path) -> None:
    conn = db.open_db(tmp_path / "x.db")
    from datetime import datetime, timedelta

    start = datetime.fromisoformat("2026-11-03T18:00:00-08:00")
    c = CheckIn(id="c1", session_id="owner_session", start=start,
                expires=start + timedelta(minutes=30))  # fmt: skip
    db.insert_checkin(conn, c)
    assert db.checkins(conn) == [c]
    db.insert_checkin(conn, c.model_copy(update={"bound_subject": "s4"}))
    assert db.checkins(conn)[0].bound_subject == "s4"


def test_rule_applies_to_column_and_model_call_funding(tmp_path: Path) -> None:
    conn = db.open_db(tmp_path / "x.db")
    rule = Rule(id="r7", name="Side gate after dark",
                target=RuleTarget(kind="protected_object", id="po_side_gate"), trigger="touch",
                active=ActiveWindow(start="17:30", end="06:00"), severity="needs_attention",
                applies_to="non_household")  # fmt: skip
    db.insert_rule(conn, rule, "owner")
    row = db.rows(conn, "rules")[0]
    assert row["applies_to"] == "non_household"
    assert db.rules(conn) == [rule]
    db.insert_model_call(
        conn, ModelCall(id="c1", model="sam-3.1", purpose="protect", req_hash="h", funding="paid")
    )
    assert db.model_calls(conn)[0].funding == "paid"


def test_export_writes_role_window_and_checkin_tables(tmp_path: Path) -> None:
    conn = _tiny_db(tmp_path / "x.db")
    db.insert_subject(conn, Subject(id="s1", visit_id="v1", track_ids=["t1"],
                                    actor_role="external_visitor",
                                    role_basis="perimeter:side_alley"))  # fmt: skip
    conn.commit()
    conn.close()
    out = export_bundle(tmp_path / "b", tmp_path / "x.db", meta={"synthetic": True})
    for name in ("subjects", "expected_windows", "checkins"):
        assert (out / "tables" / f"{name}.json").exists(), name
    bundle = load_bundle(out)
    assert [s.role_basis for s in bundle.subjects_for("v1")] == ["perimeter:side_alley"]
    assert bundle.subject_for_track("t1").actor_role == "external_visitor"
    assert bundle.expected_windows == []


def test_export_is_deterministic_and_loadable(tmp_path: Path) -> None:
    conn = _tiny_db(tmp_path / "x.db")
    conn.close()
    out1 = export_bundle(tmp_path / "b1", tmp_path / "x.db", meta={"synthetic": True})
    out2 = export_bundle(tmp_path / "b2", tmp_path / "x.db", meta={"synthetic": True})

    def digest(root: Path) -> dict[str, str]:
        return {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.json"))
        }

    assert digest(out1) == digest(out2)
    assert (out1 / "bundle.db").exists()
    bundle = load_bundle(out1)
    assert [v.id for v in bundle.visits] == ["v1"]
    assert bundle.events_for("v1")[0].id == "e1"
    assert bundle.model_calls[0].id == "call_1"
    assert bundle.scenarios[0]["id"] == "C"
    # The exported DB is a working copy of the source.
    copy = sqlite3.connect(out1 / "bundle.db")
    assert copy.execute("SELECT count(*) FROM visits").fetchone()[0] == 1


def test_export_without_db_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="vigil process"):
        export_bundle(tmp_path / "out", tmp_path / "missing.db")


def test_load_bundle_rejects_non_bundle(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="manifest"):
        load_bundle(tmp_path)


# --- the committed synthetic bundle (FR-027) -------------------------------------------


def test_synthetic_bundle_is_labelled_and_complete() -> None:
    bundle = load_bundle(SYNTHETIC)
    assert bundle.manifest["synthetic"] is True
    assert "SYNTHETIC" in bundle.manifest["label"]
    # Five scenarios A, A′, B, B′, C (spec section 4, FR-027).
    assert [s["id"] for s in bundle.scenarios] == ["A", "A-prime", "B", "B-prime", "C"]
    assert [s["title"][:2] for s in bundle.scenarios] == ["A ", "A′", "B ", "B′", "C "]
    verdicts = {v.scenario: v.verdict for v in bundle.visits}
    assert verdicts == {"A": "normal", "A-prime": "normal", "B": "noteworthy",
                        "B-prime": "normal", "C": "needs_attention"}  # fmt: skip
    visit_c = next(v for v in bundle.visits if v.scenario == "C")
    gaps = bundle.gaps_for(visit_c.id)
    g4 = next(g for g in gaps if g.id == "g4")
    assert g4.duration_s == pytest.approx(41.0)
    assert g4.region_id == "shed_back"
    hits = [h for h in bundle.rule_hits if h["visit_id"] == visit_c.id]
    assert {h["rule_id"] for h in hits} == {"r7"}
    touch = [e for e in bundle.events_for(visit_c.id) if e.type == "touch"]
    assert touch[0].target == "po_side_gate"
    # A rejected draft is visible in the validator log.
    vals = bundle.validations_for(visit_c.id)
    assert [v.passed for v in vals] == [False, True]
    # No position is ever inside a gap (FR-039).
    tracks = {e.track_id for e in bundle.events_for(visit_c.id)}
    for p in bundle.positions_for(tracks):
        assert not (g4.t0 < p.t < g4.t1)
    assert any(p.method == "fused" for p in bundle.positions_for(tracks))
    assert any(p.method == "height_prior" for p in bundle.positions_for(tracks))
    # Every story sentence cites at least one event of its visit or is a code gap sentence.
    for visit in bundle.visits:
        ids = {e.id for e in bundle.events_for(visit.id)}
        assert visit.story
        for s in visit.story:
            assert s.event_ids
            assert set(s.event_ids) <= ids
    # Watch activated by the loop in scenario B.
    assert any(w["phrase"] == "package" and w["status"] == "watching" for w in bundle.watches)


def _wall(bundle, t: float):
    from datetime import datetime, timedelta

    return datetime.fromisoformat(bundle.manifest["session_start"]) + timedelta(seconds=t)


def test_synthetic_bundle_roles_and_times_follow_section_4() -> None:
    """Roles with role_basis per subject, r7 17:30-06:00 non_household, A′ vs C contrast."""
    from datetime import time

    bundle = load_bundle(SYNTHETIC)
    by_scenario = {v.scenario: v for v in bundle.visits}
    expected = {
        "A": ("household_insider", "egress:front_door_egress"),
        "A-prime": ("household_insider", "egress:front_door_egress"),
        "B": ("external_visitor", "perimeter:driveway_entry"),
        "B-prime": ("expected_visitor", "window:w3"),
        "C": ("external_visitor", "perimeter:side_alley"),
    }
    for sid, (role, basis) in expected.items():
        subjects = bundle.subjects_for(by_scenario[sid].id)
        assert [(s.actor_role, s.role_basis) for s in subjects] == [(role, basis)], sid
        person_events = [e for e in bundle.events_for(by_scenario[sid].id)
                         if e.track_id in subjects[0].track_ids]  # fmt: skip
        assert person_events
        assert all(e.actor_role == role and e.subject_id == subjects[0].id
                   for e in person_events), sid  # fmt: skip
    r7 = next(r["json"] for r in bundle.rules if r["id"] == "r7")
    assert r7["active"] == {"start": "17:30", "end": "06:00"}
    assert r7["applies_to"] == "non_household"
    assert next(r for r in bundle.rules if r["id"] == "r7")["applies_to"] == "non_household"
    # A′ and C: the same touch of the same gate, after dark, inside r7's window.
    touches = {}
    for sid in ("A-prime", "C"):
        touch = next(e for e in bundle.events_for(by_scenario[sid].id) if e.type == "touch")
        assert touch.target == "po_side_gate"
        local = _wall(bundle, touch.t0).time()
        assert local >= time(17, 30), (sid, local)
        touches[sid] = local
    assert touches["A-prime"] < touches["C"]
    assert time(18, 0) <= touches["C"] <= time(18, 30)  # "about 18:14 PT"
    assert not [h for h in bundle.rule_hits if h["visit_id"] == by_scenario["A-prime"].id]
    assert by_scenario["A-prime"].escalated is False  # FR-013 case-2 household touch
    # A, B and B′ are daylight (T-07a, before sunset 16:55); B′ sits inside window w3.
    for sid in ("A", "B", "B-prime"):
        assert _wall(bundle, by_scenario[sid].t0).time() < time(16, 55), sid
    w3 = next(w for w in bundle.expected_windows if w.id == "w3")
    bp_start = _wall(bundle, by_scenario["B-prime"].t0)
    b_start = _wall(bundle, by_scenario["B"].t0)
    assert w3.start <= bp_start <= w3.end
    assert not (w3.start <= b_start <= w3.end)
    assert w3.cameras == ["front"]
    # Track origins (FR-008) on the first track of each subject.
    origins = {t["id"]: t["origin_zone"] for t in bundle.tables["tracks"]}
    for sid, (_, basis) in expected.items():
        first = bundle.subjects_for(by_scenario[sid].id)[0].track_ids[0]
        zone = basis.split(":", 1)[1] if not basis.startswith("window") else "driveway_entry"
        assert origins[first] == zone, sid
    # Every person-related table row is free of identity fields (NFR-003).
    for table in ("subjects", "tracks", "events", "positions", "appearance"):
        for row in bundle.tables.get(table, []):
            assert not {"name", "face", "age", "gender"} & set(row), table


def test_synthetic_bundle_presets_cover_voice_and_role_rules() -> None:
    bundle = load_bundle(SYNTHETIC)
    voice = bundle.presets["voice"]
    assert len(voice) == 3
    compile_texts = {c["text"] for c in bundle.presets["compile"]}
    for fixture in voice:
        assert fixture["transcript"] in compile_texts, fixture["id"]
        assert fixture["model"] == "muse-voice-transcribe-1.0"
    applies = {c["rule"]["applies_to"] for c in bundle.presets["compile"]}
    assert {"anyone", "non_household", "external_visitor_only"} <= applies
    assert set(bundle.presets["rerun"]) == {v.id for v in bundle.visits}


def test_synthetic_bundle_has_no_contributor_or_sensitive_words() -> None:
    banned = ("gender", "ethnicity", " age ", "skin", "male", "female", "suspicious", "intruder")
    for path in SYNTHETIC.rglob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        assert CONTRIBUTOR not in text, path
        if path.name in {"validations.json", "trace.json"}:
            continue  # the rejected draft is shown on purpose, with its reasons
        for word in banned:
            assert word not in text, (path, word)


def test_synthetic_bundle_regenerates_byte_identical(tmp_path: Path) -> None:
    builder = _load_builder()
    out = builder.build(tmp_path / "synthetic")
    committed = sorted(
        p.relative_to(SYNTHETIC).as_posix()
        for p in SYNTHETIC.rglob("*")
        if p.is_file() and p.suffix in {".json", ".glb"}
    )
    fresh = sorted(
        p.relative_to(out).as_posix()
        for p in out.rglob("*")
        if p.is_file() and p.suffix in {".json", ".glb"}
    )
    assert fresh == committed
    for rel in committed:
        fresh_bytes = (out / rel).read_bytes()
        committed_bytes = (SYNTHETIC / rel).read_bytes()
        if rel.endswith(".json"):  # tolerate a CRLF checkout of the committed text files
            committed_bytes = committed_bytes.replace(b"\r\n", b"\n")
        assert fresh_bytes == committed_bytes, rel


def test_synthetic_bundle_commits_no_audio() -> None:
    """NFR-002: no audio in the bundle; demo/voice holds a README until T-07a records WAVs."""
    audio = (".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac", ".aac", ".opus")
    demo = REPO_ROOT / "demo"
    found = [p for p in demo.rglob("*") if p.suffix.lower() in audio]
    allow = json.loads((REPO_ROOT / "config" / "audio_fixtures.json").read_text(encoding="utf-8"))
    listed = {f["sha256"] for f in allow["fixtures"]}
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() in listed for p in found), found
    assert allow["note"]
    assert (demo / "voice" / "README.md").exists()


def test_synthetic_ground_glb_is_small_and_valid() -> None:
    glb = (SYNTHETIC / "media" / "ground.glb").read_bytes()
    assert glb[:4] == b"glTF"
    assert len(glb) < 300_000
    length = int.from_bytes(glb[12:16], "little")
    doc = json.loads(glb[20 : 20 + length])
    assert doc["asset"]["version"] == "2.0"
    assert doc["meshes"]


def test_synthetic_stories_pass_the_validator_including_role_claims() -> None:
    """Every recorded story and re-run preset cites its role phrases correctly (check 7)."""
    from vigil.api import views
    from vigil.models import StoryDraft
    from vigil.reasoning.validator import validate

    bundle = load_bundle(SYNTHETIC)
    for visit in bundle.visits:
        ledger = views.visit_ledger(bundle, visit)
        stories = [visit.story, bundle.presets["rerun"][visit.id]["story"]]
        for story in stories:
            sentences = [StorySentence.model_validate(s) for s in story]
            draft = StoryDraft(sentences=[s for s in sentences if s.source != "code"])
            result = validate(draft, ledger)
            assert result.passed, (visit.id, [f.detail for f in result.failures])
