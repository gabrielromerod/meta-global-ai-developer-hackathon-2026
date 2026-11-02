"""Store and export (FR-023 ledger rows, FR-027 demo bundle, NFR-011 determinism)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from vigil.models import (
    Event,
    Gap,
    ModelCall,
    Position,
    StorySentence,
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
    assert sorted(s["id"] for s in bundle.scenarios) == ["A", "B", "C"]
    verdicts = {v.scenario: v.verdict for v in bundle.visits}
    assert verdicts == {"A": "normal", "B": "noteworthy", "C": "needs_attention"}
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


def test_synthetic_ground_glb_is_small_and_valid() -> None:
    glb = (SYNTHETIC / "media" / "ground.glb").read_bytes()
    assert glb[:4] == b"glTF"
    assert len(glb) < 300_000
    length = int.from_bytes(glb[12:16], "little")
    doc = json.loads(glb[20 : 20 + length])
    assert doc["asset"]["version"] == "2.0"
    assert doc["meshes"]
