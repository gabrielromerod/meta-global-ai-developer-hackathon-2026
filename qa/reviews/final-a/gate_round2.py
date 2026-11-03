"""Pin only accepted reviewer-A FIXTURE screenshots with the unchanged lead gate."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "qa/screens/0a7f99a1"
HELPER = Path(
    "C:/Users/lords/.codex/worktrees/ad9e/"
    "meta-global-ai-developer-hackathon-2026/scripts/ui_evidence.py"
)
full = json.loads((OUT / "accepted-full-round2.json").read_text())
supplement = json.loads((OUT / "supplement-round2.json").read_text())
media = json.loads((OUT / "media-controls-round2.json").read_text())
assert len(full["cases"]) == 22
assert not full["failures"]
assert len(media["rows"]) == 22
files = {row["screenshot"].replace("\\", "/") for row in full["rows"]}
files.update(row["file"].replace("\\", "/") for row in supplement["rows"])
for row in media["rows"]:
    width, height = row["viewport"]
    for label in ("transport", "point-coordinates", "cost-approval"):
        files.add(f"{width}x{height}/final-a-media-{row['theme']}-{label}.png")
files.update(p.relative_to(OUT).as_posix() for p in (OUT / "inspection").glob("*.png"))
fixtures = sorted((OUT / "proofs").glob("*.json"))
assert len(files) == 7980, len(files)
spec = importlib.util.spec_from_file_location("lead_ui_evidence", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.argv = [
    str(HELPER),
    str(OUT),
    "--source",
    "http://127.0.0.1:8118/next/",
    "--reviewer",
    "final_review_a",
    "--reviewed",
]
for fixture in fixtures:
    sys.argv.extend(["--fixture", str(fixture)])
for relative in sorted(files):
    sys.argv.extend(["--file", relative])
raise SystemExit(module.main())
