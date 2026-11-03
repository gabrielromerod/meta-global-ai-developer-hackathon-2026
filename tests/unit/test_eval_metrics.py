"""Unit: evaluation harness (FR-024, FR-025, FR-013 escalation rate, NFR-023, NFR-025/026).

Also covers the T-03 / H-01 / H-02 scripts' offline behaviour: plan-only smoke run, the
contributor-ID refusal (NFR-004), and the GPU probe without torch. Everything synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from vigil.eval import baseline, metrics, run, spatial_eval
from vigil.eval.metrics import ScenarioLabel, compute_metrics
from vigil.models import Window

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Synthetic labels and pipeline results for scenarios A, B, C
# ---------------------------------------------------------------------------


def _label_a() -> dict:
    return {
        "schema_version": 1,
        "scenario": "A",
        "title": "Routine departure",
        "expected_verdict": "normal",
        "expected_escalated": False,
        "subjects": [
            {"id": "S1", "class": "person", "appearances": [
                {"camera_id": "front", "t0": 0.0, "t1": 20.0}]},
            {"id": "V1", "class": "vehicle", "appearances": [
                {"camera_id": "front", "t0": 15.0, "t1": 40.0}]},
        ],
        "gaps": [],
        "events": [{"type": "exit", "camera_id": "front", "t": 38.0}],
    }  # fmt: skip


def _label_b() -> dict:
    return {
        "schema_version": 1,
        "scenario": "B",
        "title": "Delivery",
        "expected_verdict": "noteworthy",
        "expected_escalated": True,
        "subjects": [{"id": "S1", "class": "person", "appearances": [
            {"camera_id": "front", "t0": 0.0, "t1": 30.0}]}],
        "gaps": [],
        "events": [],
    }  # fmt: skip


def _label_c() -> dict:
    return {
        "schema_version": 1,
        "scenario": "C",
        "title": "Night gate and shed",
        "expected_verdict": "needs_attention",
        "expected_escalated": True,
        "subjects": [
            {"id": "S1", "class": "person", "appearances": [
                {"camera_id": "front", "t0": 0.0, "t1": 10.0},
                {"camera_id": "side_left", "t0": 14.0, "t1": 40.0},
                {"camera_id": "side_left", "t0": 81.0, "t1": 95.0}]},
            {"id": "S2", "class": "person", "appearances": [
                {"camera_id": "side_right", "t0": 0.0, "t1": 10.0}]},
        ],
        "gaps": [{"id": "g4", "kind": "blind_spot", "t0": 40.0, "t1": 81.0,
                  "region_id": "shed_back"}],
        "events": [{"type": "touch", "camera_id": "side_left", "t": 22.0,
                    "target": "po_side_gate"}],
        "rules_fired": ["r7"],
    }  # fmt: skip


def _visit(vid, verdict, escalated, story, events=(), gaps=(), links=(), positions=()):
    return {
        "id": vid, "t0": 0.0, "t1": 100.0, "verdict": verdict, "escalated": escalated,
        "forced": verdict == "needs_attention", "story": list(story), "events": list(events),
        "gaps": list(gaps), "links": list(links), "positions": list(positions),
    }  # fmt: skip


def _results() -> list[dict]:
    a = {
        "scenario": "A",
        "motion_triggers": 6,
        "visits": [
            _visit("vA", "normal", False,
                   [{"text": "A person left by car.", "event_ids": ["eA1"], "source": "template"}],
                   events=[{"id": "eA1", "camera_id": "front", "t0": 37.0, "t1": 38.0}]),
        ],
    }  # fmt: skip
    b = {
        "scenario": "B",
        "motion_triggers": 4,
        "visits": [
            _visit("vB", "noteworthy", True,
                   [{"text": "A person left a box.", "event_ids": ["eB1"]}],
                   events=[{"id": "eB1", "camera_id": "front", "t0": 10.0, "t1": 12.0}]),
        ],
    }  # fmt: skip
    c = {
        "scenario": "C",
        "motion_triggers": 10,
        "visits": [
            _visit(
                "vC",
                "needs_attention",
                True,
                [
                    {"text": "A person touched the side gate at 10:14 PM.", "event_ids": ["e17"]},
                    {"text": "Not observed for 41 s.", "event_ids": [], "source": "code",
                     "gap_id": "g4"},
                    {"text": "They checked the shed door.", "event_ids": ["e30"]},
                    {"text": "They left.", "event_ids": []},
                ],
                events=[
                    {"id": "e17", "camera_id": "side_left", "t0": 21.5, "t1": 22.5},
                    {"id": "e30", "camera_id": "side_left", "t0": 55.0, "t1": 56.0},
                ],
                gaps=[{"id": "g4", "kind": "blind_spot", "t0": 40.3, "t1": 81.2}],
                links=[
                    {"from": {"camera_id": "front", "t0": 1.0, "t1": 9.0},
                     "to": {"camera_id": "side_left", "t0": 15.0, "t1": 39.0}},
                    {"from": {"camera_id": "side_left", "t0": 15.0, "t1": 39.0},
                     "to": {"camera_id": "side_left", "t0": 82.0, "t1": 94.0}},
                    {"from": {"camera_id": "side_right", "t0": 1.0, "t1": 9.0},
                     "to": {"camera_id": "side_left", "t0": 82.0, "t1": 94.0}},
                ],
                positions=[{"t": 30.0}, {"t": 60.0}],
            ),
        ],
        "camera_ai_events": [
            {"camera_id": "side_left", "kind": "person", "t0": 14.0, "t1": 30.0},
            {"camera_id": "backyard", "kind": "person", "t0": 50.0, "t1": 52.0},
        ],
        "tracks": [{"camera_id": "side_left", "cls": "person", "t_first": 15.0, "t_last": 39.0}],
    }  # fmt: skip
    return [a, b, c]


def _labels() -> list[dict]:
    return [_label_a(), _label_b(), _label_c()]


# ---------------------------------------------------------------------------
# compute_metrics (NFR-023)
# ---------------------------------------------------------------------------


def test_labels_validate_against_schema() -> None:
    for raw in _labels():
        ScenarioLabel.model_validate(raw)


def test_label_schema_has_no_identity_fields() -> None:
    """Labels describe what happened, never who (NFR-003)."""
    banned = {"face", "age", "gender", "skin", "ethnicity", "race", "name"}
    fields = set(ScenarioLabel.model_fields) | set(metrics.LabelSubject.model_fields)
    assert not banned & fields


def test_alert_reduction() -> None:
    m = compute_metrics(_labels(), _results())
    assert m["totals"]["motion_triggers"] == 20
    assert m["totals"]["alerts"] == 1  # only needs_attention is an alert
    assert m["totals"]["alert_reduction"] == pytest.approx(1 - 1 / 20)
    assert m["met"]["alert_reduction"] is True


def test_correct_verdicts_x_of_n() -> None:
    m = compute_metrics(_labels(), _results())
    assert m["totals"]["correct_verdicts"] == 3
    assert m["totals"]["scenarios"] == 3
    res = _results()
    res[1]["visits"][0]["verdict"] = "normal"
    m2 = compute_metrics(_labels(), res)
    assert m2["totals"]["correct_verdicts"] == 2
    row_b = next(r for r in m2["scenarios"] if r["scenario"] == "B")
    assert row_b["verdict"] == "normal"
    assert row_b["correct"] is False


def test_link_precision_counts_cross_subject_links_as_wrong() -> None:
    m = compute_metrics(_labels(), _results())
    assert m["totals"]["links"] == 3
    assert m["totals"]["links_correct"] == 2
    assert m["totals"]["link_precision"] == pytest.approx(2 / 3)
    assert m["met"]["link_precision"] is False  # misses are reported, never hidden


def test_claims_inside_gaps_and_uncited_sentences() -> None:
    m = compute_metrics(_labels(), _results())
    assert m["totals"]["claims_inside_gaps"] == 1  # "checked the shed door" cites e30 at 55 s
    assert m["totals"]["uncited_sentences_shipped"] == 1  # "They left." cites nothing
    assert m["totals"]["positions_inside_gaps"] == 1  # t=60 is inside g4
    assert m["met"]["claims_inside_gaps"] is False
    assert m["met"]["uncited_sentences_shipped"] is False


def test_code_gap_sentence_is_not_uncited() -> None:
    res = _results()
    story = res[2]["visits"][0]["story"]
    res[2]["visits"][0]["story"] = [s for s in story if s.get("event_ids") or s.get("gap_id")]
    res[2]["visits"][0]["story"].pop()  # drop the in-gap claim
    m = compute_metrics(_labels(), res)
    assert m["totals"]["uncited_sentences_shipped"] == 0
    assert m["totals"]["claims_inside_gaps"] == 0


def test_escalation_rate() -> None:
    m = compute_metrics(_labels(), _results())
    assert m["totals"]["visits"] == 3
    assert m["totals"]["escalated"] == 2
    assert m["totals"]["escalation_rate"] == pytest.approx(2 / 3)


def test_gap_matches_label_within_1s() -> None:
    m = compute_metrics(_labels(), _results())
    row_c = next(r for r in m["scenarios"] if r["scenario"] == "C")
    assert row_c["gaps_labelled"] == 1
    assert row_c["gaps_matched"] == 1


def test_reolink_sam_agreement() -> None:
    m = compute_metrics(_labels(), _results())
    assert m["totals"]["reolink_person_events"] == 2
    assert m["totals"]["reolink_matched_by_sam"] == 1


def test_missing_result_counts_as_incorrect() -> None:
    m = compute_metrics(_labels(), _results()[:2])
    row_c = next(r for r in m["scenarios"] if r["scenario"] == "C")
    assert row_c["status"] == "missing"
    assert row_c["correct"] is False
    assert m["totals"]["correct_verdicts"] == 2


def test_no_motion_triggers_gives_none_not_crash() -> None:
    res = _results()
    for r in res:
        r["motion_triggers"] = 0
    m = compute_metrics(_labels(), res)
    assert m["totals"]["alert_reduction"] is None
    assert m["met"]["alert_reduction"] is None


def _window_rows(n_idle: int, n_processed: int, cam: str = "front") -> list[dict]:
    statuses = ["idle"] * n_idle + ["processed"] * n_processed
    return [
        {"id": f"{cam}-{i}", "camera_id": cam, "t0": 8.0 * i, "t1": 8.0 * i + 10.0,
         "trigger": "motion", "status": s}
        for i, s in enumerate(statuses)
    ]  # fmt: skip


def test_tier0_skipped_window_share() -> None:
    """Spec 11.9 Tier 0: share of windows the motion gate skipped before any model call."""
    res = _results()
    res[0]["windows"] = _window_rows(8, 2)
    res[1]["windows"] = _window_rows(3, 1) + _window_rows(4, 0, cam="backyard")
    # Scenario C reports no window list: it contributes nothing (not a fake 0%).
    m = compute_metrics(_labels(), res)
    row_a = next(r for r in m["scenarios"] if r["scenario"] == "A")
    assert (row_a["windows_total"], row_a["windows_skipped"]) == (10, 8)
    row_c = next(r for r in m["scenarios"] if r["scenario"] == "C")
    assert (row_c["windows_total"], row_c["windows_skipped"]) == (0, 0)
    t = m["totals"]
    assert (t["windows_total"], t["windows_skipped"]) == (18, 15)
    assert t["tier0_skipped_share"] == pytest.approx(15 / 18)
    md = run.render_markdown(m)
    assert "Tier 0 skipped-window share" in md
    assert "83.3% (15/18 windows)" in md


def test_tier0_skipped_share_is_none_without_windows() -> None:
    m = compute_metrics(_labels(), _results())
    assert m["totals"]["windows_total"] == 0
    assert m["totals"]["tier0_skipped_share"] is None
    assert "Tier 0 skipped-window share (11.9) | reported | n/a |" in run.render_markdown(m)
    # A missing result contributes no windows either.
    assert compute_metrics(_labels(), [])["totals"]["tier0_skipped_share"] is None


def test_correct_verdict_target_is_10_of_12() -> None:
    labels, results = [], []
    for i in range(12):
        lab = _label_a() | {"scenario": f"S{i:02d}"}
        res = _results()[0] | {"scenario": f"S{i:02d}"}
        if i < 3:
            res = json.loads(json.dumps(res))
            res["visits"][0]["verdict"] = "noteworthy"
        labels.append(lab)
        results.append(res)
    m = compute_metrics(labels, results)
    assert m["totals"]["correct_verdicts"] == 9
    assert m["met"]["correct_verdicts"] is False


# ---------------------------------------------------------------------------
# run_eval (FR-024): deterministic results.json
# ---------------------------------------------------------------------------


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    labels_dir = tmp_path / "labels"
    out_dir = tmp_path / "outputs"
    labels_dir.mkdir()
    out_dir.mkdir()
    for lab in _labels():
        (labels_dir / f"{lab['scenario']}.json").write_text(json.dumps(lab), encoding="utf-8")
    (labels_dir / "_template.json").write_text("{}", encoding="utf-8")  # ignored
    for res in reversed(_results()):
        (out_dir / f"{res['scenario']}.json").write_text(json.dumps(res), encoding="utf-8")
    return labels_dir, out_dir


def test_run_eval_writes_sorted_results_and_returns_dict(tmp_path: Path) -> None:
    labels_dir, out_dir = _write_inputs(tmp_path)
    out = tmp_path / "eval" / "results.json"
    result = run.run_eval(labels_dir, out, results=out_dir)
    text = out.read_text(encoding="utf-8")
    assert json.loads(text) == result
    assert text == json.dumps(result, sort_keys=True, indent=2) + "\n"
    assert [r["scenario"] for r in result["scenarios"]] == ["A", "B", "C"]
    assert set(result["labels_sha256"]) == {"A", "B", "C"}


def test_run_eval_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    labels_dir, out_dir = _write_inputs(tmp_path)
    out1, out2 = tmp_path / "r1.json", tmp_path / "r2.json"
    run.run_eval(labels_dir, out1, results=out_dir)
    run.run_eval(labels_dir, out2, results=out_dir)
    assert out1.read_bytes() == out2.read_bytes()


def test_run_eval_default_results_location(tmp_path: Path) -> None:
    labels_dir, _ = _write_inputs(tmp_path)
    result = run.run_eval(labels_dir, tmp_path / "results.json")
    assert result["totals"]["scenarios"] == 3


def test_run_eval_accepts_single_results_file(tmp_path: Path) -> None:
    labels_dir, _ = _write_inputs(tmp_path)
    combined = tmp_path / "all.json"
    combined.write_text(json.dumps({"scenarios": _results()}), encoding="utf-8")
    result = run.run_eval(labels_dir, tmp_path / "results.json", results=combined)
    assert result["totals"]["correct_verdicts"] == 3


def test_run_eval_without_labels_is_a_clear_error(tmp_path: Path) -> None:
    (tmp_path / "labels").mkdir()
    with pytest.raises(FileNotFoundError, match="pre-regist"):
        run.run_eval(tmp_path / "labels", tmp_path / "r.json", results=tmp_path)


def test_run_eval_missing_results_is_a_clear_error(tmp_path: Path) -> None:
    labels_dir, _ = _write_inputs(tmp_path)
    with pytest.raises(FileNotFoundError, match="results"):
        run.run_eval(labels_dir, tmp_path / "r.json", results=tmp_path / "nope")


def test_markdown_table_lists_targets_and_misses(tmp_path: Path) -> None:
    labels_dir, out_dir = _write_inputs(tmp_path)
    result = run.run_eval(labels_dir, tmp_path / "r.json", results=out_dir)
    md = run.render_markdown(result)
    assert "| Alert reduction |" in md
    assert "missed" in md
    assert "3 of 3" in md


def test_committed_template_is_valid_and_ignored() -> None:
    raw = json.loads((REPO / "eval" / "labels" / "_template.json").read_text(encoding="utf-8"))
    ScenarioLabel.model_validate({k: v for k, v in raw.items() if not k.startswith("$")})


# ---------------------------------------------------------------------------
# Naive baseline (FR-025)
# ---------------------------------------------------------------------------


def _windows() -> list[Window]:
    return [
        Window(id=f"w{i}", camera_id="side_left", t0=10.0 * i, t1=10.0 * i + 10, trigger="motion")
        for i in range(10)
    ]


def test_baseline_counts_alerts_and_unsupported_claims() -> None:
    answers = {
        "w0": {"anything_wrong": False, "claims": []},
        "w2": {"anything_wrong": True, "claims": [{"text": "Someone touched the gate."}]},
        "w5": {"anything_wrong": True, "claims": [{"text": "An intruder is in the shed."}]},
        "w9": {"anything_wrong": True, "claims": [{"text": "Prowler", "supported": False}]},
    }

    def fake_answer(w: Window) -> dict:
        return answers.get(w.id, {"anything_wrong": False, "claims": []})

    report = baseline.run_baseline(_windows(), fake_answer, labels=[_label_c()])
    assert report["windows"] == 10
    assert report["alerts"] == 3
    assert report["claims"] == 3
    # w2 (20-30 s) overlaps S1 on side_left; w5 (50-60 s) is inside the shed gap;
    # w9 is annotated unsupported by the reviewer.
    assert report["unsupported_claims"] == 2
    assert report["auto_judged_claims"] == 2


def test_baseline_malformed_answer_counts_as_error_not_alert() -> None:
    report = baseline.run_baseline(_windows()[:2], lambda w: {"oops": 1})
    assert report["alerts"] == 0
    assert report["errors"] == 2


def test_baseline_side_by_side_table() -> None:
    report = baseline.run_baseline(_windows(), lambda w: {"anything_wrong": True, "claims": []})
    vigil = compute_metrics([_label_c()], [_results()[2]])
    rows = baseline.side_by_side(report, vigil)
    assert rows["baseline"]["alerts"] == 10
    assert rows["vigil"]["alerts"] == 1


def test_baseline_live_path_is_blocked_without_credits(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(baseline.BaselineBlocked, match="blocked"):
        baseline.spark_answer_fn()


# ---------------------------------------------------------------------------
# Spatial accuracy (NFR-025, NFR-026)
# ---------------------------------------------------------------------------


def test_spatial_report_median_p90_and_r95_share() -> None:
    errs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    points = [
        {"marker_id": f"m{i}", "camera_id": "side_left", "true": [1.0, 0.0, 2.0],
         "est": [1.0 + e, 0.3, 2.0], "r95": 0.75, "range_m": 4.0 + i}
        for i, e in enumerate(errs)
    ]  # fmt: skip
    rep = spatial_eval.spatial_report(points)
    assert rep["n"] == 10
    assert rep["median_m"] == pytest.approx(0.55)
    assert rep["p90_m"] == pytest.approx(0.91)
    assert rep["inside_r95_share"] == pytest.approx(0.7)
    assert rep["within_10m"]["n"] == 7
    assert rep["within_10m"]["median_m"] == pytest.approx(0.4)
    assert rep["median_basis"] == "within_10m"  # NFR-025 is stated within 10 m
    assert rep["met"]["median_under_0_5m"] is True
    assert rep["met"]["inside_r95_at_least_90pct"] is False
    assert rep["per_camera"]["side_left"]["n"] == 10


def test_spatial_report_ignores_height_and_accepts_xz_pairs() -> None:
    rep = spatial_eval.spatial_report(
        [{"camera_id": "front", "true": [0.0, 0.0], "est": [0.3, 0.4], "r95": 0.6}]
    )
    assert rep["median_m"] == pytest.approx(0.5)
    assert rep["inside_r95_share"] == 1.0


def test_spatial_report_empty() -> None:
    rep = spatial_eval.spatial_report([])
    assert rep["n"] == 0
    assert rep["median_m"] is None
    assert rep["met"]["median_under_0_5m"] is None


# ---------------------------------------------------------------------------
# Scripts: smoke_meta (T-03), gpu_probe (H-01), bench_sam_local (H-02)
# ---------------------------------------------------------------------------


def _run_script(name: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    full_env = {**os.environ, **(env or {})}
    full_env["MODEL_API_KEY"] = ""  # explicit empty: never fall back to a key in .env
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / name), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=full_env,
        cwd=REPO,
    )


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), REPO / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_smoke_meta_without_live_prints_plan_and_exits_0() -> None:
    proc = _run_script("smoke_meta.py")
    assert proc.returncode == 0, proc.stderr
    for model in ("sam-3.1", "muse-spark-1.3", "muse-wonder-1.0", "muse-voice-transcribe-1.0"):
        assert model in proc.stdout
    assert "plan only" in proc.stdout.lower()


def test_smoke_meta_refuses_contributor_ids() -> None:
    proc = _run_script("smoke_meta.py", "--model", "muse-spark-1.3-contributor")
    assert proc.returncode != 0
    assert "contributor" in (proc.stdout + proc.stderr).lower()


def test_smoke_meta_live_without_key_is_blocked() -> None:
    proc = _run_script("smoke_meta.py", "--live")
    assert proc.returncode != 0
    assert "MODEL_API_KEY" in proc.stdout + proc.stderr


def test_smoke_meta_never_records_without_flag(tmp_path: Path) -> None:
    mod = _load_script("smoke_meta.py")
    assert mod.record_path("sam-3.1", record=False, root=tmp_path) is None
    path = mod.record_path("sam-3.1", record=True, root=tmp_path, digest="abcdef123")
    assert path == tmp_path / "sam-3.1__smoke__abcdef1.json"


def test_smoke_meta_scrubs_before_recording() -> None:
    mod = _load_script("smoke_meta.py")
    raw = {
        "id": "resp_1",
        "file_id": "file-REAL",
        "organization": "org-x",
        "headers": {"Authorization": "Bearer sk-live"},
        "output": [{"file_id": "file-REAL"}],
    }
    clean = mod.scrub(raw)
    text = json.dumps(clean)
    assert "org-x" not in text
    assert "sk-live" not in text
    assert "file-REAL" not in text
    assert clean["file_id"] == "file_test_001" == clean["output"][0]["file_id"]


def test_gpu_probe_report_without_torch_is_not_ready() -> None:
    mod = _load_script("gpu_probe.py")
    smi = "NVIDIA GeForce RTX 3090, 24576, 23800, 300, 581.29, 41, 210, 2100, 30.5, P8"
    report = mod.build_report(smi_rows=mod.parse_smi(smi), cuda_version="13.0", torch_info=None)
    assert report["gpus"][0]["name"] == "NVIDIA GeForce RTX 3090"
    assert report["gpus"][0]["memory_total_mib"] == 24576
    assert report["torch"] == "not installed"
    assert report["ready"] is False
    assert any("torch" in r for r in report["reasons"])
    assert mod.default_name(report) == "3090"


def test_gpu_probe_ready_with_cuda_torch() -> None:
    mod = _load_script("gpu_probe.py")
    smi = "NVIDIA GeForce RTX 3090, 24576, 23800, 300, 581.29, 41, 210, 2100, 30.5, P8"
    torch_info = {"version": "2.9.0", "cuda_available": True, "device_count": 1,
                  "device_name": "NVIDIA GeForce RTX 3090", "free_mib": 23000,
                  "total_mib": 24576, "cuda": "12.8"}  # fmt: skip
    report = mod.build_report(
        smi_rows=mod.parse_smi(smi), cuda_version="13.0", torch_info=torch_info
    )
    assert report["ready"] is True, report["reasons"]


def test_gpu_probe_without_nvidia_smi_writes_not_ready(tmp_path: Path) -> None:
    out = tmp_path / "gpu.json"
    proc = _run_script("gpu_probe.py", "--out", str(out), "--smi", "definitely-not-nvidia-smi")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["ready"] is False
    assert any("nvidia-smi" in r for r in report["reasons"])


def test_bench_sam_local_is_blocked_without_sam3() -> None:
    proc = _run_script("bench_sam_local.py")
    if proc.returncode == 0:  # pragma: no cover - only on a provisioned GPU box
        pytest.skip("sam3 and torch present")
    assert proc.returncode == 2
    assert "blocked" in (proc.stdout + proc.stderr).lower()


def test_bench_sam_local_plan_lists_the_grid() -> None:
    proc = _run_script("bench_sam_local.py", "--plan")
    assert proc.returncode == 0
    mod = _load_script("bench_sam_local.py")
    grid = mod.grid()
    assert len(grid) == 4 * 2 * 2
    assert {g["chunk_s"] for g in grid} == {2, 3, 5, 10}
    assert {g["width"] for g in grid} == {640, 960}
    assert {g["fps"] for g in grid} == {5, 10}


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("| NVIDIA-SMI 581.29   Driver Version: 581.29   CUDA Version: 13.0 |", "13.0"),
        ("| NVIDIA-SMI 617.42   KMD Version: 617.42   CUDA UMD Version: 13.4 |", "13.4"),
        ("no banner", None),
    ],
)
def test_gpu_probe_reads_cuda_version_from_both_banner_styles(header, expected) -> None:
    mod = _load_script("gpu_probe.py")
    assert mod.cuda_version_from(header) == expected
