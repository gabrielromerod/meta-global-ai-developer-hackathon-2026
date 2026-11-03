"""`vigil eval`: benchmark against pre-registered labels (FR-024).

Loads every `eval/labels/<scenario>.json` (files starting with `_` are templates and are
skipped), loads the pipeline results, computes the NFR-023 metrics and writes
`eval/results.json` with sorted keys and no timestamps, so re-running from the cache
gives byte-identical output. The SHA-256 of each label file is included so the results
can be tied to the label commit (pre-registration).

Results location: a directory of `<scenario>.json` files, or one JSON file holding a list
or `{"scenarios": [...]}`. Default: `<labels_dir>/../outputs`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from vigil.eval.metrics import TARGETS, compute_metrics


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_labels(labels_dir: Path) -> tuple[list[dict], dict[str, str]]:
    labels_dir = Path(labels_dir)
    files = sorted(p for p in labels_dir.glob("*.json") if not p.name.startswith("_"))
    if not files:
        raise FileNotFoundError(
            f"no labels in {labels_dir}: labels must be written and committed before any "
            "run (pre-registration, FR-024); copy eval/labels/_template.json"
        )
    labels: list[dict] = []
    hashes: dict[str, str] = {}
    for p in files:
        raw = p.read_bytes()
        lab = json.loads(raw.decode("utf-8"))
        lab = {k: v for k, v in lab.items() if not k.startswith("$")}
        labels.append(lab)
        hashes[str(lab.get("scenario", p.stem))] = hashlib.sha256(raw).hexdigest()
    return labels, hashes


def load_results(results: Path) -> list[dict]:
    results = Path(results)
    if results.is_dir():
        files = sorted(p for p in results.glob("*.json") if not p.name.startswith("_"))
        if not files:
            raise FileNotFoundError(f"no pipeline results (*.json) in {results}")
        out = []
        for p in files:
            data = _read_json(p)
            data.setdefault("scenario", p.stem)
            out.append(data)
        return out
    if results.is_file():
        data = _read_json(results)
        if isinstance(data, dict):
            data = data.get("scenarios", [])
        if not isinstance(data, list):
            raise ValueError(f"{results}: expected a list of scenario results")
        return data
    raise FileNotFoundError(
        f"pipeline results not found at {results}; run `vigil process` first or pass --results"
    )


def run_eval(
    labels_dir: Path,
    out: Path,
    results: Path | None = None,
    table_out: Path | None = None,
) -> dict:
    """Compute EVAL metrics and write `out` deterministically. Returns the written dict."""
    labels_dir = Path(labels_dir)
    labels, hashes = load_labels(labels_dir)
    res = load_results(Path(results) if results is not None else labels_dir.parent / "outputs")
    metrics = compute_metrics(labels, res)
    metrics["labels_sha256"] = dict(sorted(hashes.items()))
    text = json.dumps(metrics, sort_keys=True, indent=2) + "\n"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    if table_out is not None:
        Path(table_out).write_text(render_markdown(metrics), encoding="utf-8", newline="\n")
    return json.loads(text)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _met(v: bool | None) -> str:
    return "n/a" if v is None else ("met" if v else "missed")


def render_markdown(metrics: dict) -> str:
    """EVAL.md table (NFR-023): target, measured value, met or missed. Misses included."""
    t, m = metrics["totals"], metrics["met"]
    alerts_txt = f"{t['alerts']} alerts / {t['motion_triggers']} motion triggers"
    reolink_txt = f"{t['reolink_matched_by_sam']}/{t['reolink_person_events']}"
    tier0_txt = _pct(t.get("tier0_skipped_share"))
    if t.get("windows_total"):
        tier0_txt += f" ({t['windows_skipped']}/{t['windows_total']} windows)"
    rows = [
        ("Alert reduction", TARGETS["alert_reduction"]["text"],
         f"{_pct(t['alert_reduction'])} ({alerts_txt})",
         m["alert_reduction"]),
        ("Correct verdicts", TARGETS["correct_verdicts"]["text"],
         f"{t['correct_verdicts']} of {t['scenarios']}", m["correct_verdicts"]),
        ("Link precision", TARGETS["link_precision"]["text"],
         f"{_pct(t['link_precision'])} ({t['links_correct']}/{t['links']})", m["link_precision"]),
        ("Claims inside gaps", TARGETS["claims_inside_gaps"]["text"],
         str(t["claims_inside_gaps"]), m["claims_inside_gaps"]),
        ("Uncited sentences shipped", TARGETS["uncited_sentences_shipped"]["text"],
         str(t["uncited_sentences_shipped"]), m["uncited_sentences_shipped"]),
        ("Escalation rate (FR-013)", "reported", _pct(t["escalation_rate"]), None),
        ("Positions inside gaps (FR-039)", "0", str(t["positions_inside_gaps"]), None),
        ("Gaps matched within 1 s (FR-011)", "reported",
         f"{t['gaps_matched']} of {t['gaps_labelled']}", None),
        ("Reolink person events matched by SAM", "reported",
         f"{_pct(t['reolink_sam_agreement'])} ({reolink_txt})",
         None),
        ("Tier 0 skipped-window share (11.9)", "reported", tier0_txt, None),
    ]  # fmt: skip
    lines = ["| Metric | Target | Measured | Result |", "| --- | --- | --- | --- |"]
    lines += [f"| {a} | {b} | {c} | {_met(d) if d is not None else '-'} |" for a, b, c, d in rows]
    lines += [
        "",
        "| Scenario | Lighting | Expected | Verdict | Correct |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in metrics["scenarios"]:
        lines.append(
            f"| {r['scenario']} | {r['lighting']} | {r['expected_verdict']} | "
            f"{r['verdict'] or r['status']} | {'yes' if r['correct'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"
