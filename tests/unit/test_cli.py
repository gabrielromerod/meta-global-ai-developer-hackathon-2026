"""`vigil` CLI (spec 9.2): every command's offline path and its blocked paths.

Everything runs through typer's CliRunner against files in ``tmp_path``. No network, no
Meta API, no camera: hardware and credit paths are checked for a clean ``blocked: <reason>``
with exit code 2 (never a traceback), and fakes stand in for reolink-aio and the pipeline.
"""

from __future__ import annotations

import json
import math
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

from tests.fixtures.video.synth import blob_clip, flash_clip
from vigil import __version__
from vigil.cli import app
from vigil.meta.budget import BudgetExceeded, ConfirmRequired
from vigil.models import Calibration, ModelCall, Window
from vigil.spatial.calibrate import fov_intrinsics
from vigil.spatial.geometry import CameraGeom, look_at_extrinsics
from vigil.store import db

runner = CliRunner()

CONFIG_YAML = """\
# test config: this comment must survive `vigil ingest` (offsets are not written back)
timezone: America/Los_Angeles
cameras:
  - id: front
    name: Front entrance
    source: {host_env: VIGIL_TEST_FRONT_HOST, channel: null}
    offset_s: 0.0
    hfov_deg: 100.0
    privacy:
      - [[0, 0], [1280, 0], [1280, 80], [0, 80]]   # street
  - id: side_left
    name: Left side
    privacy: none_needed
    source: {host_env: VIGIL_TEST_SIDE_HOST, channel: null}
    offset_s: 0.0
"""


def run(*args: str | Path):
    return runner.invoke(app, [str(a) for a in args])


def assert_clean(result) -> None:
    """No traceback: the command exited through typer.Exit / SystemExit only."""
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )
    assert "Traceback" not in result.output


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    p = tmp_path / "config" / "cameras.yaml"
    p.parent.mkdir(parents=True)
    p.write_text(CONFIG_YAML, encoding="utf-8")
    return p


@pytest.fixture
def no_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("VIGIL_TEST_FRONT_HOST", "VIGIL_TEST_SIDE_HOST"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def hosts(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("VIGIL_TEST_FRONT_HOST", "192.0.2.10")
    monkeypatch.setenv("VIGIL_TEST_SIDE_HOST", "192.0.2.11")
    monkeypatch.setenv("REOLINK_USER", "viewer")
    secret = "hunter2-not-real"
    monkeypatch.setenv("REOLINK_PASSWORD", secret)
    return secret


# ---------------------------------------------------------------------------
# version and help
# ---------------------------------------------------------------------------


def test_cli_version() -> None:
    r = run("version")
    assert r.exit_code == 0
    assert r.output.strip() == __version__


def test_cli_help_lists_every_command() -> None:
    r = run("--help")
    assert r.exit_code == 0
    for name in ("version", "ingest", "process", "eval", "export", "serve", "spatial",
                 "reolink", "cost", "demo"):  # fmt: skip
        assert name in r.output


def test_cli_ingest_help_says_offsets_are_not_written_back() -> None:
    r = run("ingest", "--help")
    assert r.exit_code == 0
    assert "cameras.yaml" in r.output
    assert "not" in r.output.lower()


# ---------------------------------------------------------------------------
# ingest (FR-001 to FR-005)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def flash_clips(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two cameras; the clap/flash lands at 1.0 s on front and 2.0 s on side_left."""
    d = tmp_path_factory.mktemp("clips")
    flash_clip(d / "front.mp4", 11.0, [1.0], fps=15.0, seed=1)
    flash_clip(d / "side_left_20261102T180000Z.mp4", 11.0, [2.0], fps=15.0, seed=2)
    (d / "notes.txt").write_text("not a clip", encoding="utf-8")
    return d


def test_cli_ingest_end_to_end(flash_clips: Path, cfg_path: Path, tmp_path: Path) -> None:
    before = cfg_path.read_bytes()
    out = tmp_path / "windows"
    r = run("ingest", flash_clips, "--session", "s1", "--config", cfg_path, "--out", out)
    assert_clean(r)
    assert r.exit_code == 0, r.output
    session_dir = out / "s1"
    meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert meta["session"] == "s1"
    assert meta["synced"] is True
    assert meta["reference"] == "front"
    assert meta["offsets"]["front"] == 0.0
    assert meta["offsets"]["side_left"] == pytest.approx(-1.0, abs=0.1)
    # session start from the side_left clip name (capture naming, UTC), minus its offset,
    # in the config timezone: 18:00:00Z + 1 s = 10:00:01 PST
    start = datetime.fromisoformat(meta["session_start"])
    assert start.utcoffset() is not None
    assert start.astimezone(UTC) == datetime(2026, 11, 2, 18, 0, 1, tzinfo=UTC)
    # windows.json is what vigil.pipeline.process_session reads: 11 s -> [0, 10], [8, 11]
    wins = [Window.model_validate(w) for w in
            json.loads((session_dir / "windows.json").read_text(encoding="utf-8"))]  # fmt: skip
    assert {w.camera_id for w in wins} == {"front", "side_left"}
    assert len(wins) == 4
    for w in wins:
        assert w.path is not None
        assert Path(w.path).exists()
        assert w.status in ("pending", "idle")
    side = sorted((w for w in wins if w.camera_id == "side_left"), key=lambda w: w.t0)
    assert side[0].t0 == pytest.approx(-1.0, abs=0.1)  # session clock = camera + offset
    assert set(meta["active"]) <= {w.id for w in wins}
    # offsets printed, config untouched (comments kept)
    assert "side_left" in r.output
    assert "offset" in r.output.lower()
    assert cfg_path.read_bytes() == before


def test_cli_ingest_keeps_owner_keys_and_explicit_start(
    flash_clips: Path, cfg_path: Path, tmp_path: Path
) -> None:
    session_dir = tmp_path / "windows" / "s2"
    session_dir.mkdir(parents=True)
    rules = [{"id": "r9", "name": "x"}]
    (session_dir / "session.json").write_text(json.dumps({"rules": rules}), encoding="utf-8")
    r = run("ingest", flash_clips, "--session", "s2", "--config", cfg_path,
            "--out", tmp_path / "windows", "--start", "2026-10-30T18:00:00")  # fmt: skip
    assert r.exit_code == 0, r.output
    meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert meta["rules"] == rules  # owner-added keys survive a re-ingest
    assert meta["session_start"] == "2026-10-30T18:00:00-07:00"  # naive -> config timezone


def test_cli_ingest_then_process_with_real_pipeline_is_blocked_cleanly(
    flash_clips: Path, cfg_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: ingest writes the layout vigil.pipeline reads; with no recorded SAM
    answers the pipeline raises RuntimeError("blocked: ...") -> exit 2, no traceback."""
    from vigil.settings import get_settings

    data = tmp_path / "data"
    r = run("ingest", flash_clips, "--session", "s3", "--config", cfg_path,
            "--out", data / "windows")  # fmt: skip
    assert r.exit_code == 0, r.output
    monkeypatch.setenv("VIGIL_DATA_DIR", str(data))
    monkeypatch.setenv("VIGIL_CONFIG_PATH", str(cfg_path))
    get_settings.cache_clear()
    try:
        r = run("process", "--session", "s3")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert_clean(r)
    assert r.exit_code == 2, r.output
    assert "blocked:" in r.output
    assert "SAM" in r.output


def test_cli_ingest_no_clips(cfg_path: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    r = run("ingest", empty, "--config", cfg_path, "--out", tmp_path / "w")
    assert_clean(r)
    assert r.exit_code == 1
    assert "no clips" in r.output.lower()


def test_cli_ingest_bad_config(flash_clips: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("cameras: [{id: front}]\n", encoding="utf-8")
    r = run("ingest", flash_clips, "--config", bad, "--out", tmp_path / "w")
    assert_clean(r)
    assert r.exit_code == 1
    assert "config" in r.output.lower() or "schema" in r.output.lower()


def test_cli_ingest_without_sync_event(cfg_path: Path, tmp_path: Path) -> None:
    clips = tmp_path / "quiet"
    clips.mkdir()
    blob_clip(clips / "front.mp4", 3.0, size=(320, 180), blob=None)
    r = run("ingest", clips, "--config", cfg_path, "--out", tmp_path / "w")
    assert_clean(r)
    assert r.exit_code == 1
    assert "--no-sync" in r.output

    r = run("ingest", clips, "--config", cfg_path, "--out", tmp_path / "w", "--no-sync")
    assert_clean(r)
    assert r.exit_code == 0, r.output
    meta = json.loads((tmp_path / "w" / "default" / "session.json").read_text("utf-8"))
    wins = json.loads((tmp_path / "w" / "default" / "windows.json").read_text("utf-8"))
    assert meta["synced"] is False
    assert meta["offsets"] == {"front": 0.0}
    assert len(wins) == 1
    assert wins[0]["status"] == "idle"  # static scene: no model calls (FR-005)
    assert meta["active"] == []
    assert "session start" in r.output.lower()  # no --start, no timestamp in name: warned


def test_cli_ingest_blocked_without_ffmpeg(
    flash_clips: Path, cfg_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vigil.settings

    def missing() -> str:
        raise FileNotFoundError("ffmpeg not found; install ffmpeg or set VIGIL_FFMPEG")

    monkeypatch.setattr(vigil.settings, "ffmpeg_bin", missing)
    r = run("ingest", flash_clips, "--config", cfg_path, "--out", tmp_path / "w")
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


def test_cli_ingest_rejects_path_like_session(
    flash_clips: Path, cfg_path: Path, tmp_path: Path
) -> None:
    r = run("ingest", flash_clips, "--session", "../x", "--config", cfg_path, "--out", tmp_path)
    assert_clean(r)
    assert r.exit_code == 1


# ---------------------------------------------------------------------------
# process (pipeline, lazily imported)
# ---------------------------------------------------------------------------


def _fake_pipeline(monkeypatch: pytest.MonkeyPatch, fn) -> None:
    mod = types.ModuleType("vigil.pipeline")
    mod.process_session = fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "vigil.pipeline", mod)


def test_cli_process_blocked_without_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "vigil.pipeline", None)
    r = run("process", "--session", "s1")
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


def test_cli_process_calls_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool]] = []

    def process_session(session: str, *, confirm: bool = False, settings=None) -> dict:
        calls.append((session, confirm))
        return {"session": session, "visits": 3, "cost_usd": 0.0}

    _fake_pipeline(monkeypatch, process_session)
    r = run("process", "--session", "s1", "--confirm")
    assert_clean(r)
    assert r.exit_code == 0, r.output
    assert calls == [("s1", True)]
    assert '"visits": 3' in r.output


def test_cli_process_needs_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    def process_session(session: str, *, confirm: bool = False, settings=None) -> dict:
        raise ConfirmRequired(7.5, 5.0)

    _fake_pipeline(monkeypatch, process_session)
    r = run("process")
    assert_clean(r)
    assert r.exit_code == 1
    assert "--confirm" in r.output


def test_cli_process_pipeline_blocked_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def process_session(session: str, *, confirm: bool = False, settings=None) -> dict:
        raise RuntimeError("blocked: no recorded SAM 3.1 answers")

    _fake_pipeline(monkeypatch, process_session)
    r = run("process")
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked: no recorded SAM 3.1 answers" in r.output


def test_cli_process_budget_refusal_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def process_session(session: str, *, confirm: bool = False, settings=None) -> dict:
        raise BudgetExceeded("total", 140.0, 139.0, 2.0)

    _fake_pipeline(monkeypatch, process_session)
    r = run("process", "--confirm")
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


# ---------------------------------------------------------------------------
# eval (FR-024, NFR-025/026, latency)
# ---------------------------------------------------------------------------

LABEL_A = {
    "schema_version": 1, "scenario": "A", "title": "Routine departure",
    "expected_verdict": "normal", "expected_escalated": False,
    "subjects": [{"id": "S1", "class": "person",
                  "appearances": [{"camera_id": "front", "t0": 0.0, "t1": 20.0}]}],
    "gaps": [], "events": [],
}  # fmt: skip
RESULT_A = {
    "scenario": "A", "motion_triggers": 4,
    "visits": [{"id": "vA", "t0": 0.0, "t1": 20.0, "verdict": "normal", "escalated": False,
                "forced": False, "events": [], "gaps": [], "links": [], "positions": [],
                "story": [{"text": "A person left.", "event_ids": ["e1"]}]}],
}  # fmt: skip


def test_cli_eval_missing_labels(tmp_path: Path) -> None:
    r = run("eval", "--labels", tmp_path / "nolabels", "--out", tmp_path / "r.json")
    assert_clean(r)
    assert r.exit_code == 1
    assert "labels" in r.output.lower()


def test_cli_eval_runs_and_prints_table(tmp_path: Path) -> None:
    labels = tmp_path / "labels"
    outputs = tmp_path / "outputs"
    labels.mkdir()
    outputs.mkdir()
    (labels / "A.json").write_text(json.dumps(LABEL_A), encoding="utf-8")
    (outputs / "A.json").write_text(json.dumps(RESULT_A), encoding="utf-8")
    out = tmp_path / "results.json"
    r = run("eval", "--labels", labels, "--results", outputs, "--out", out, "--table")
    assert_clean(r)
    assert r.exit_code == 0, r.output
    res = json.loads(out.read_text(encoding="utf-8"))
    assert res["totals"]["scenarios"] == 1
    assert "| Metric | Target | Measured | Result |" in r.output


def test_cli_eval_missing_results(tmp_path: Path) -> None:
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / "A.json").write_text(json.dumps(LABEL_A), encoding="utf-8")
    r = run("eval", "--labels", labels, "--results", tmp_path / "none", "--out", tmp_path / "o")
    assert_clean(r)
    assert r.exit_code == 1
    assert "vigil process" in r.output


def test_cli_eval_spatial_blocked_without_recordings(tmp_path: Path) -> None:
    r = run("eval", "--spatial", "--spatial-dir", tmp_path / "spatial")
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


def test_cli_eval_spatial_report(tmp_path: Path) -> None:
    sp = tmp_path / "spatial"
    sp.mkdir()
    pts = [
        {"marker_id": "m1", "camera_id": "front", "true": [0, 0, 5], "est": [0.3, 0, 5],
         "r95": 0.5, "range_m": 5.0},
        {"marker_id": "m2", "camera_id": "front", "true": [1, 5], "est": [1, 5.2], "r95": 0.4},
    ]  # fmt: skip
    (sp / "front.json").write_text(json.dumps({"points": pts}), encoding="utf-8")
    out = tmp_path / "spatial_results.json"
    r = run("eval", "--spatial", "--spatial-dir", sp, "--spatial-out", out)
    assert_clean(r)
    assert r.exit_code == 0, r.output
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["n"] == 2
    assert rep["inside_r95_share"] == 1.0
    assert "median_m" in r.output


def _db_with_calls(path: Path, latencies: list[int | None]) -> Path:
    conn = db.open_db(path)
    for i, ms in enumerate(latencies):
        db.insert_model_call(
            conn,
            ModelCall(id=f"c{i}", model="sam-3.1", purpose="protect", req_hash=f"h{i}",
                      latency_ms=ms, cached=ms is None),
        )  # fmt: skip
    conn.commit()
    conn.close()
    return path


def test_cli_eval_latency(tmp_path: Path) -> None:
    dbp = _db_with_calls(tmp_path / "v.db", [1000, 2000, 3000, 4000, None])
    out = tmp_path / "latency.json"
    r = run("eval", "--latency", "--db", dbp, "--latency-out", out)
    assert_clean(r)
    assert r.exit_code == 0, r.output
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["protect"]["n"] == 4
    assert rep["protect"]["p50_ms"] == pytest.approx(2500.0)


def test_cli_eval_latency_blocked_without_live_calls(tmp_path: Path) -> None:
    r = run("eval", "--latency", "--db", tmp_path / "missing.db")
    assert_clean(r)
    assert r.exit_code == 2
    dbp = _db_with_calls(tmp_path / "cached.db", [None])
    r = run("eval", "--latency", "--db", dbp)
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


# ---------------------------------------------------------------------------
# export and demo
# ---------------------------------------------------------------------------


def test_cli_export_without_db(tmp_path: Path, cfg_path: Path) -> None:
    r = run("export", "--out", tmp_path / "bundle", "--db", tmp_path / "none.db",
            "--config", cfg_path)  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 1
    assert "vigil process" in r.output


def test_cli_export_writes_bundle(tmp_path: Path, cfg_path: Path) -> None:
    dbp = _db_with_calls(tmp_path / "v.db", [1200])
    out = tmp_path / "bundle"
    r = run("export", "--out", out, "--db", dbp, "--config", cfg_path)
    assert_clean(r)
    assert r.exit_code == 0, r.output
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "vigil-bundle/1"
    assert (out / "bundle.db").exists()
    assert "privacy" in r.output.lower()


def test_cli_demo_synthetic(tmp_path: Path) -> None:
    out = tmp_path / "synthetic"
    r = run("demo", "synthetic", "--out", out)
    assert_clean(r)
    assert r.exit_code == 0, r.output
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


def test_cli_serve_uses_app_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    seen: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda target, **kw: seen.update(target=target, **kw))
    r = run("serve", "--port", "8123")
    assert_clean(r)
    assert r.exit_code == 0
    assert seen["target"] == "vigil.api.app:create_app"
    assert seen["factory"] is True
    assert seen["port"] == 8123


# ---------------------------------------------------------------------------
# reolink (FR-030, FR-031): field hardware
# ---------------------------------------------------------------------------


def test_cli_reolink_probe_blocked_without_hosts(cfg_path: Path, no_hosts, tmp_path) -> None:
    r = run("reolink", "probe", "--config", cfg_path, "--env-file", tmp_path / "none.env")
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


def test_cli_reolink_probe_blocked_without_reolink_aio(
    cfg_path: Path, hosts: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vigil.reolink import probe as rp

    def unavailable():
        raise rp.ReolinkUnavailable("reolink-aio is not installed (optional group 'reolink')")

    monkeypatch.setattr(rp, "import_reolink_host", unavailable)
    r = run("reolink", "probe", "--config", cfg_path, "--env-file", tmp_path / "none.env")
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output
    assert "reolink-aio" in r.output


def test_cli_reolink_probe_prints_redacted_reports(
    cfg_path: Path, hosts: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vigil.reolink import probe as rp

    class FakeAdapter:
        async def host_info(self, host: str, username: str, password: str) -> rp.HostInfo:
            return rp.HostInfo(model="RLC-TEST", firmware="v1", channels=[0],
                               ai_types={0: ["people", "vehicle"]})  # fmt: skip

        async def check_stream(self, url) -> bool:
            return True

    monkeypatch.setattr(rp, "ReolinkAioAdapter", FakeAdapter)
    r = run("reolink", "probe", "--config", cfg_path, "--env-file", tmp_path / "none.env")
    assert_clean(r)
    assert r.exit_code == 0, r.output
    assert hosts not in r.output
    reports = [json.loads(line) for line in r.stdout.splitlines() if line.startswith("{")]
    assert [rep["camera_id"] for rep in reports] == ["front", "side_left"]
    assert all(rep["ok"] and rep["ai_person"] for rep in reports)


def test_cli_reolink_capture_blocked_without_hosts(cfg_path: Path, no_hosts, tmp_path) -> None:
    r = run("reolink", "capture", "--config", cfg_path, "--out-dir", tmp_path / "seg",
            "--env-file", tmp_path / "none.env")  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


def test_cli_reolink_capture_runs_supervisors(
    cfg_path: Path, hosts: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vigil.reolink import capture as rc

    seen: dict = {}

    async def fake_run_capture(cams, out_dir, segment_s=10, **kw):
        seen.update(cams=[c.id for c in cams], out_dir=out_dir, **kw)
        return []

    monkeypatch.setattr(rc, "run_capture", fake_run_capture)
    r = run("reolink", "capture", "--config", cfg_path, "--out-dir", tmp_path / "seg",
            "--env-file", tmp_path / "none.env", "--max-restarts", "0")  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 0, r.output
    assert seen["cams"] == ["front", "side_left"]
    assert Path(seen["out_dir"]) == tmp_path / "seg"
    assert seen["via_restreamer"] is True
    assert seen["max_restarts"] == 0


def test_cli_reolink_capture_blocked_without_ffmpeg(
    cfg_path: Path, hosts: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vigil.settings

    def missing() -> str:
        raise FileNotFoundError("ffmpeg not found")

    monkeypatch.setattr(vigil.settings, "ffmpeg_bin", missing)
    r = run("reolink", "capture", "--config", cfg_path, "--out-dir", tmp_path / "seg",
            "--env-file", tmp_path / "none.env")  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


# ---------------------------------------------------------------------------
# spatial (FR-035 to FR-038)
# ---------------------------------------------------------------------------


def test_cli_spatial_build_blocked(tmp_path: Path) -> None:
    r = run("spatial", "build")
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output
    seg = tmp_path / "loop1.ply"
    seg.write_bytes(b"ply\n")
    r = run("spatial", "build", seg)
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


def _true_front(hfov: float = 90.0) -> Calibration:
    k = fov_intrinsics(1280, 720, hfov)
    ext = look_at_extrinsics((0.0, 2.6, 0.0), (0.0, 0.0, 6.0))
    return Calibration(camera_id="front", intrinsics=k, extrinsics=ext)


def _marker_pairs(hfov: float = 90.0) -> list[dict]:
    cal = _true_front(hfov)
    pts = np.array([[-1.5, 0, 3.0], [1.5, 0, 3.5], [0, 0, 5.5], [2.0, 0, 6.5], [-2.0, 0, 7.0],
                    [1.0, 0, 8.5], [-1.0, 0, 9.5], [0.5, 0, 10.0]], float)  # fmt: skip
    uv, front = CameraGeom.from_calibration(cal).project(pts)
    assert front.all()
    return [
        {"u": float(u), "v": float(v), "x": float(p[0]), "y": float(p[1]), "z": float(p[2]),
         "id": f"m{i}"}
        for i, ((u, v), p) in enumerate(zip(uv, pts, strict=True))
    ]  # fmt: skip


def test_cli_spatial_calibrate_blocked_without_pairs(cfg_path: Path, tmp_path: Path) -> None:
    r = run("spatial", "calibrate", "front", "--config", cfg_path,
            "--out", tmp_path / "calibration.json")  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


def test_cli_spatial_calibrate_unknown_camera(cfg_path: Path, tmp_path: Path) -> None:
    pairs = tmp_path / "pairs.json"
    pairs.write_text(json.dumps(_marker_pairs()), encoding="utf-8")
    r = run("spatial", "calibrate", "nope", "--pairs", pairs, "--config", cfg_path,
            "--out", tmp_path / "calibration.json")  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 1


def test_cli_spatial_calibrate_fov_fallback_and_pnp(cfg_path: Path, tmp_path: Path) -> None:
    """FR-036/FR-037 (Nov 2): nominal-FOV intrinsics, the 6 landmarks all used in the solve
    (none held out), accuracy measured only by the separate audit markers (NFR-024)."""
    marks = _marker_pairs()
    pairs = tmp_path / "pairs.json"
    pairs.write_text(json.dumps({"pairs": marks[:6]}), encoding="utf-8")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"markers": marks[6:]}), encoding="utf-8")
    frames = tmp_path / "frames"
    frames.mkdir()  # no checkerboard views -> FOV fallback (FR-036), flagged
    out = tmp_path / "calibration.json"
    r = run("spatial", "calibrate", "front", "--frames", frames, "--pairs", pairs,
            "--audit", audit, "--hfov", "90", "--config", cfg_path, "--out", out)  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 0, r.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [c["camera_id"] for c in data] == ["front"]
    assert data[0]["intrinsics"]["fov_fallback"] is True
    report = json.loads((tmp_path / "calibration_report.json").read_text(encoding="utf-8"))
    rep = report["cameras"][0]
    assert rep["camera_id"] == "front"
    assert rep["reproj_ok"] is True
    assert rep["audit_measured"] is True
    assert rep["heldout_ok"] is True
    assert "fov_fallback" in r.output
    # re-running for another camera keeps the first one
    r = run("spatial", "calibrate", "side_left", "--pairs", pairs, "--hfov", "90",
            "--config", cfg_path, "--out", out)  # fmt: skip
    assert r.exit_code == 0, r.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert sorted(c["camera_id"] for c in data) == ["front", "side_left"]


def test_cli_spatial_calibrate_uses_all_landmarks_and_camera_hfov(
    cfg_path: Path, tmp_path: Path
) -> None:
    """Without --hfov the camera's hfov_deg from cameras.yaml sets the nominal intrinsics;
    every landmark pair goes into the solve (no hold-out), so no audit means not measured."""
    pairs = tmp_path / "pairs.json"
    pairs.write_text(json.dumps(_marker_pairs(100.0)), encoding="utf-8")  # 8, all landmarks
    out = tmp_path / "calibration.json"
    r = run("spatial", "calibrate", "front", "--pairs", pairs, "--config", cfg_path,
            "--out", out)  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 0, r.output
    (cal,) = json.loads(out.read_text(encoding="utf-8"))
    assert cal["intrinsics"]["source"] == "fov_nominal"
    f = 640.0 / math.tan(math.radians(100.0 / 2))  # front's hfov_deg 100 at 1280 px
    assert cal["intrinsics"]["k"][0][0] == pytest.approx(f)
    rep = json.loads((tmp_path / "calibration_report.json").read_text(encoding="utf-8"))
    (rep,) = rep["cameras"]
    assert rep["audit_measured"] is False
    assert rep["heldout_ground_m"] is None
    assert rep["reproj_ok"] is True


def test_cli_spatial_calibrate_refuses_audit_marker_reused_as_landmark(
    cfg_path: Path, tmp_path: Path
) -> None:
    marks = _marker_pairs()
    pairs = tmp_path / "pairs.json"
    pairs.write_text(json.dumps(marks[:6]), encoding="utf-8")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps(marks[5:]), encoding="utf-8")  # m5 is also a landmark
    r = run("spatial", "calibrate", "front", "--pairs", pairs, "--audit", audit,
            "--config", cfg_path, "--out", tmp_path / "calibration.json")  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 1
    assert "audit" in r.output


SITE_PLAN = {
    "ground": {"min": [-6.0, -1.0], "max": [6.0, 12.0]},
    "site_plan": {"boxes": [{"id": "shed", "name": "Shed", "kind": "building",
                             "min": [-1.5, 5.0], "max": [1.5, 6.0], "h": 2.2}]},
}  # fmt: skip


@pytest.fixture
def calib_file(tmp_path: Path) -> Path:
    p = tmp_path / "calibration.json"
    p.write_text(json.dumps([_true_front().model_dump(mode="json")]), encoding="utf-8")
    return p


def test_cli_spatial_coverage_blocked_without_inputs(
    cfg_path: Path, calib_file: Path, tmp_path: Path
) -> None:
    r = run("spatial", "coverage", "--config", cfg_path,
            "--calibration", tmp_path / "missing.json")  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output
    r = run("spatial", "coverage", "--config", cfg_path, "--calibration", calib_file)
    assert_clean(r)
    assert r.exit_code == 2
    assert "blocked:" in r.output


def test_cli_spatial_coverage_dry_run_then_write(
    cfg_path: Path, calib_file: Path, tmp_path: Path
) -> None:
    plan = tmp_path / "site_plan.json"
    plan.write_text(json.dumps(SITE_PLAN), encoding="utf-8")
    before = cfg_path.read_bytes()
    grid = tmp_path / "coverage.json"
    r = run("spatial", "coverage", "--config", cfg_path, "--calibration", calib_file,
            "--site-plan", plan, "--grid-out", grid)  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 0, r.output
    assert "behind the shed" in r.output
    assert "dry run" in r.output.lower()
    assert cfg_path.read_bytes() == before
    assert json.loads(grid.read_text(encoding="utf-8"))["cell_m"] == 0.25

    r = run("spatial", "coverage", "--config", cfg_path, "--calibration", calib_file,
            "--site-plan", plan, "--write")  # fmt: skip
    assert_clean(r)
    assert r.exit_code == 0, r.output
    assert "comments" in r.output.lower()
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert any(b["name"] == "behind the shed" for b in raw["blind_regions"])


# ---------------------------------------------------------------------------
# cost (FR-043, spec 11.4)
# ---------------------------------------------------------------------------


def _total(output: str) -> float:
    line = next(ln for ln in output.splitlines() if ln.lower().startswith("total"))
    return float(line.split("$")[1].split()[0])


def test_cli_cost_estimate_plan() -> None:
    r = run("cost", "estimate")
    assert_clean(r)
    assert r.exit_code == 0, r.output
    for feature in ("perception_demo", "appearance", "story", "baseline", "sandbox"):
        assert feature in r.output
    assert "perception_all" not in r.output
    assert "$140.00" in r.output
    local = _total(r.output)
    assert 40.0 < local < 70.0  # spec 11.5: about $55 with local SAM

    r = run("cost", "estimate", "--api-sam")
    assert r.exit_code == 0
    assert "perception_all" in r.output
    assert _total(r.output) > local + 30.0


def _feature_line(output: str, feature: str) -> str:
    return next(ln for ln in output.splitlines() if ln.strip().startswith(feature))


def test_cli_cost_estimate_with_measured_tokens() -> None:
    base = run("cost", "estimate")
    assert "OVER" not in _feature_line(base.output, "appearance")
    r = run("cost", "estimate", "--spark-clip-tokens", "60000")
    assert r.exit_code == 0
    assert _total(r.output) > _total(base.output) + 10.0
    # appearance now exceeds its $16 feature budget
    assert "OVER" in _feature_line(r.output, "appearance")


def test_cli_cost_estimate_over_total_cap_exits_1() -> None:
    r = run("cost", "estimate", "--api-sam", "--spark-clip-tokens", "200000")
    assert_clean(r)
    assert r.exit_code == 1
    assert _total(r.output) > 140.0


def test_cli_cost_estimate_ad_hoc() -> None:
    r = run("cost", "estimate", "--model", "sam-3.1", "--frames", "600")
    assert_clean(r)
    assert r.exit_code == 0, r.output
    assert "$0.12" in r.output
    r = run("cost", "estimate", "--model", "muse-spark-1.3", "--in-tokens", "30000",
            "--out-tokens", "500", "--calls", "10")  # fmt: skip
    assert r.exit_code == 0
    assert "$0.40" in r.output


def test_cli_cost_estimate_refuses_contributor_model() -> None:
    r = run("cost", "estimate", "--model", "muse-spark-1.3-contributor", "--in-tokens", "10")
    assert_clean(r)
    assert r.exit_code == 1
    assert "contributor" in r.output.lower()
