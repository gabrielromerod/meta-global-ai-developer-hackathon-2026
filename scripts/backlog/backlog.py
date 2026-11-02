"""Build the GitHub backlog from the spec and sync it idempotently (bootstrap Phase 4).

    uv run python scripts/backlog/backlog.py build            # spec -> scripts/backlog/backlog.json
    uv run python scripts/backlog/backlog.py sync             # dry run: print what would change
    uv run python scripts/backlog/backlog.py sync --apply     # create labels, milestones, issues

Idempotent: issues are matched by their ID prefix ("FR-001:", "T-07:", "H-02:", "D-1:"), labels
and milestones by name. Existing issues get their labels reconciled; titles and bodies are never
overwritten, so manual edits on GitHub survive. Requires an authenticated `gh` CLI.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "spec" / "vigil-spec.md"
OUT = Path(__file__).with_name("backlog.json")
STATUS = Path(__file__).with_name("status.json")
REPO = "gabrielromerod/meta-global-ai-developer-hackathon-2026"
SPEC_URL = f"https://github.com/{REPO}/blob/main/docs/spec/vigil-spec.md"

# PST (UTC-8) after DST ended on Nov 1 2026.
MILESTONES = {
    "G1": ("2026-11-03T07:00:00Z", "Mon Nov 2 23:00 PT: footage and labels committed; SAM tracks for A, B, C; GLB built"),
    "G2": ("2026-11-03T21:00:00Z", "Tue Nov 3 13:00 PT: scenario C end to end, including 3D positions and the gap"),
    "G3 MVP freeze": ("2026-11-04T02:00:00Z", "Tue Nov 3 18:00 PT: all P0 pass in CI"),
    "G4": ("2026-11-04T07:00:00Z", "Tue Nov 3 23:00 PT: evidence complete; sandbox opened on a phone"),
    "Submission": ("2026-11-04T22:00:00Z", "Wed Nov 4 14:00 PT: spec 13.5 checklist ticked; form submitted"),
}  # fmt: skip

LABELS = {
    "track:A": ("1f77b4", "Pipeline (ingest, capture, perception)"),
    "track:B": ("9467bd", "Models and reasoning"),
    "track:C": ("2ca02c", "App and 3D"),
    "track:D": ("8c564b", "Field work and evidence"),
    "P0": ("b60205", "Required for a working demo"),
    "P1": ("d93f0b", "Required for a top score"),
    "P2": ("fbca04", "Optional"),
    "type:task": ("c5def5", "Build-plan task (spec 9.7)"),
    "type:fr": ("bfdadc", "Functional requirement (spec 1)"),
    "type:hw": ("d4c5f9", "Hardware verification (spec 10.2)"),
    "blocked:credits": ("e99695", "Needs Meta API credits / MODEL_API_KEY"),
    "blocked:hardware": ("e99695", "Needs field hardware: Reolink cameras, iPhone LiDAR, filming, GPU weights"),
    "blocked:dgx": ("e99695", "Needs the DGX Spark (conditional phase D-1)"),
    "blocked:owner": ("e99695", "Needs an owner decision, account or approval"),
    "offline-done": ("0e8a16", "Offline part implemented and green in CI on synthetic data; real-data acceptance pending"),
}  # fmt: skip

# Blockers for the *acceptance criteria* (what still stands between the item and Done).
FR_BLOCKERS = {
    "FR-002": ["hardware"], "FR-004": ["credits"], "FR-005": ["hardware"],
    "FR-006": ["credits"], "FR-009": ["credits"], "FR-010": ["hardware"],
    "FR-011": ["hardware"], "FR-013": ["credits"], "FR-014": ["credits"],
    "FR-015": [], "FR-019": ["credits"], "FR-020": ["credits"], "FR-021": ["credits"],
    "FR-022": ["credits"], "FR-024": ["hardware"], "FR-025": ["credits"],
    "FR-027": ["hardware"], "FR-028": ["hardware", "owner"],
    "FR-030": ["hardware"], "FR-031": ["hardware"], "FR-032": ["hardware"],
    "FR-033": ["hardware", "credits"], "FR-034": ["hardware"], "FR-035": ["hardware"],
    "FR-036": ["hardware"], "FR-037": ["hardware"], "FR-038": ["hardware"],
    "FR-039": ["hardware"], "FR-040": ["hardware"], "FR-041": ["hardware"],
    "FR-042": ["hardware", "owner"], "FR-043": ["credits"],
}  # fmt: skip
FR_TRACK = {
    **dict.fromkeys(["FR-001", "FR-002", "FR-003", "FR-004", "FR-005", "FR-006", "FR-007",
                     "FR-008", "FR-030", "FR-031", "FR-032", "FR-033"], "A"),
    **dict.fromkeys(["FR-009", "FR-010", "FR-011", "FR-012", "FR-013", "FR-014", "FR-015",
                     "FR-016", "FR-019", "FR-020", "FR-021", "FR-022", "FR-023", "FR-028",
                     "FR-042", "FR-043"], "B"),
    **dict.fromkeys(["FR-017", "FR-018", "FR-026", "FR-027", "FR-029", "FR-034", "FR-035",
                     "FR-036", "FR-037", "FR-038", "FR-039", "FR-040"], "C"),
    **dict.fromkeys(["FR-024", "FR-025", "FR-041"], "D"),
}  # fmt: skip
TASK_BLOCKERS = {
    "T-01": ["owner"], "T-03": ["credits"], "T-04": ["hardware"], "T-05": ["hardware"],
    "T-06": ["hardware"], "T-07": ["hardware", "owner"], "T-10": ["hardware"],
    "T-12": ["hardware"], "T-14": ["hardware"], "T-15": ["hardware"], "T-16": ["credits"],
    "T-17": ["hardware"], "T-19": ["hardware"], "T-20": ["credits"], "T-22": ["credits"],
    "T-23": ["hardware"], "T-26": ["hardware"], "T-27": ["credits", "hardware"],
    "T-28": ["owner"], "T-29": ["hardware", "owner"], "T-30": ["owner"],
    "H-02": ["owner", "hardware"], "H-03": ["owner", "hardware"], "H-04": ["credits"],
    "D-1": ["dgx"],
}  # fmt: skip


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _clean(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("\\|", "|").replace("\\_", "_")


def _milestone_for_time(when: str) -> str:
    day = when.split()[0]
    m = re.search(r"(\d{2}):(\d{2})", when)
    minutes = int(m.group(1)) * 60 + int(m.group(2)) if m else 0
    if day == "Mon":
        return "G1"
    if day == "Tue":
        if minutes <= 13 * 60:
            return "G2"
        if minutes <= 18 * 60:
            return "G3 MVP freeze"
        return "G4"
    return "Submission"


def build() -> list[dict]:
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    items: list[dict] = []
    top = section = ""
    for line in lines:
        if line.startswith("#"):
            section = line.lstrip("#").strip().split(" ", 1)[0]
            if line.startswith("## "):
                top = section
            continue
        if line.startswith("| FR-") and top == "1.":
            c = _cells(line)
            fr_id, pri, req, deps, acc = c[0], c[1], _clean(c[2]), c[3], _clean(c[4])
            title_req = re.match(r"(.+?)\.\s", req)
            short = title_req.group(1) if title_req else req[:70]
            blockers = FR_BLOCKERS.get(fr_id, [])
            items.append({
                "id": fr_id,
                "title": f"{fr_id}: {short}",
                "labels": ["type:fr", pri, f"track:{FR_TRACK.get(fr_id, 'B')}"]
                + [f"blocked:{b}" for b in blockers],
                "milestone": {"P0": "G3 MVP freeze", "P1": "G4"}.get(pri),
                "body": (
                    f"**Requirement ({pri}).** {req}\n\n**Depends on:** {deps}\n\n"
                    f"**Acceptance criteria:** {acc}\n\n"
                    f"**Blocked by:** {', '.join(blockers) or 'nothing (offline-buildable)'}\n\n"
                    f"Spec: [{fr_id}]({SPEC_URL}#1-functional-requirements) · "
                    f"Status: [docs/requirements/functional.md](https://github.com/{REPO}/blob/main/docs/requirements/functional.md)"
                ),
            })  # fmt: skip
        elif re.match(r"\| T-\d\d ", line) and section == "9.7":
            c = _cells(line)
            tid, rest = c[0].split(" ", 1)
            track, when, deps, files, done = c[1], _clean(c[2]), c[3], c[4], c[5]
            blockers = TASK_BLOCKERS.get(tid, [])
            items.append({
                "id": tid,
                "title": f"{tid}: {rest}",
                "labels": ["type:task", f"track:{track}"] + [f"blocked:{b}" for b in blockers],
                "milestone": _milestone_for_time(when),
                "body": (
                    f"**Due:** {when} PT · **Track:** {track} · **Depends on:** {deps}\n\n"
                    f"**Files:** {files}\n\n**Done when:** {done}\n\n"
                    f"**Blocked by:** {', '.join(blockers) or 'nothing'}\n\n"
                    f"Spec: [9.7 Tasks in order]({SPEC_URL}#97-tasks-in-order-times-pt-tracks-a-pipeline-b-models-and-reasoning-c-app-and-3d-d-field-work-and-evidence)"
                ),
            })  # fmt: skip
        elif re.match(r"\| H-0\d ", line) and section == "10.2":
            c = _cells(line)
            hid, rest = c[0].split(" ", 1)
            when, what, done = _clean(c[1]), _clean(c[2]), _clean(c[3])
            blockers = TASK_BLOCKERS.get(hid, [])
            items.append({
                "id": hid,
                "title": f"{hid}: {rest}",
                "labels": ["type:hw", "track:B"] + [f"blocked:{b}" for b in blockers],
                "milestone": _milestone_for_time(when),
                "body": (
                    f"**Due:** {when} PT\n\n**Runs:** {what}\n\n**Done when:** {done}\n\n"
                    f"**Blocked by:** {', '.join(blockers) or 'nothing'}\n\n"
                    f"Spec: [10.2 Hardware verification]({SPEC_URL}#102-hardware-verification-tasks-added-to-section-9) · "
                    "Runbook: docs/runbooks/gpu-h01-h04.md"
                ),
            })  # fmt: skip
    items.append({
        "id": "D-1",
        "title": "D-1: DGX Spark full-window SAM 3.1 (conditional: only if gate H-02 fails)",
        "labels": ["type:hw", "track:B", "blocked:dgx"],
        "milestone": "G2",
        "body": (
            "**Conditional.** Triggered only if gate H-02 fails at Mon 22:00 PT; connect the Spark "
            "by Tue 08:00 PT. Runs SAM 3.1 on full 10 s windows via a `sam-worker` "
            "(`VIGIL_SAM_BACKEND=remote`).\n\n**Done when:** no OOM on 10 s windows; ID switches "
            "at most the API's; mean IoU with the API >= 0.8; seconds per window recorded.\n\n"
            f"Spec: [10.4]({SPEC_URL}#104-advance-notice-dgx-spark-phase-d-1-conditional-not-yet-triggered) · "
            "Runbook: docs/runbooks/dgx-spark-d1.md"
        ),
    })  # fmt: skip
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)), "duplicate ids"
    OUT.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return items


def _gh(*args: str, input_: str | None = None) -> str:
    res = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8", input=input_
    )
    if res.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}... failed: {res.stderr.strip()}")
    return res.stdout


def sync(apply: bool) -> None:
    items = json.loads(OUT.read_text(encoding="utf-8"))
    status = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    offline_done = set(status.get("offline_done", []))
    close = status.get("close", {})
    for item in items:
        if item["id"] in offline_done and "offline-done" not in item["labels"]:
            item["labels"].append("offline-done")

    existing_labels = {
        lb["name"]
        for lb in json.loads(_gh("label", "list", "-R", REPO, "--limit", "200", "--json", "name"))
    }
    for name, (color, desc) in LABELS.items():
        if name not in existing_labels:
            print(f"label  + {name}")
            if apply:
                _gh("label", "create", name, "-R", REPO, "--color", color, "--description", desc)

    ms = {
        m["title"]: m["number"]
        for m in json.loads(_gh("api", f"repos/{REPO}/milestones?state=all&per_page=100"))
    }
    for title, (due, desc) in MILESTONES.items():
        if title not in ms:
            print(f"milestone + {title} ({due})")
            if apply:
                created = json.loads(
                    _gh(
                        "api",
                        f"repos/{REPO}/milestones",
                        "-f",
                        f"title={title}",
                        "-f",
                        f"due_on={due}",
                        "-f",
                        f"description={desc}",
                    )
                )
                ms[title] = created["number"]

    issues = json.loads(
        _gh(
            "issue",
            "list",
            "-R",
            REPO,
            "--state",
            "all",
            "--limit",
            "500",
            "--json",
            "number,title,labels,state",
        )
    )
    by_id = {i["title"].split(":", 1)[0]: i for i in issues}
    for item in items:
        found = by_id.get(item["id"])
        if not found:
            print(f"issue  + {item['title'][:90]}")
            if apply:
                args = ["issue", "create", "-R", REPO, "--title", item["title"], "--body-file", "-"]
                for lb in item["labels"]:
                    args += ["--label", lb]
                if item.get("milestone"):
                    args += ["--milestone", item["milestone"]]
                url = _gh(*args, input_=item["body"]).strip()
                found = {"number": int(url.rsplit("/", 1)[-1]), "labels": [], "state": "OPEN"}
        else:
            have = {lb["name"] for lb in found["labels"]}
            missing = [lb for lb in item["labels"] if lb not in have]
            if missing:
                print(f"issue  ~ #{found['number']} {item['id']} +labels {missing}")
                if apply:
                    _gh(
                        "issue",
                        "edit",
                        str(found["number"]),
                        "-R",
                        REPO,
                        *[a for lb in missing for a in ("--add-label", lb)],
                    )
        if found and item["id"] in close and found.get("state") == "OPEN":
            print(f"issue  x #{found['number']} {item['id']} close: {close[item['id']]}")
            if apply:
                _gh(
                    "issue",
                    "close",
                    str(found["number"]),
                    "-R",
                    REPO,
                    "--comment",
                    close[item["id"]],
                )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    s = sub.add_parser("sync")
    s.add_argument("--apply", action="store_true", help="make changes (default: dry run)")
    args = ap.parse_args()
    if args.cmd == "build":
        items = build()
        print(f"{len(items)} items -> {OUT.relative_to(ROOT)}")
    else:
        sync(args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
