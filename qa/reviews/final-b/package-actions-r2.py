"""Validate only the additional settled navigation captures with the unchanged gate."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.ui_evidence import pin_fixture, sha, validate_manifest

root = Path("qa/screens/c965bedf")
manifest = root / "final-b-actions-privacy.json"
files = sorted(
    p
    for p in root.rglob("*.png")
    if re.search(r"final-b-r2-(nav-|notification-|actions-index-)", p.name)
)
assert len(files) == 56
record = {
    "kind": "generated_ui",
    "source": "http://127.0.0.1:8119/next/",
    "reviewer": "final_review_b_round_2",
    "reviewed": True,
    "contains_camera_pixels": False,
    "authenticated": False,
    "fixture_hash_mode": "lf-normalized",
    "fixtures": [
        pin_fixture(root / name, manifest)
        for name in ["final-b-fixture-api-states.json", "final-b-r2-navigation.json"]
    ],
    "files": {p.relative_to(root).as_posix(): sha(p) for p in files},
}
manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
count, failures = validate_manifest(root, manifest)
result = {"evidence": {"kind": "fixture"}, "count": count, "failures": failures}
(root / "final-b-actions-privacy-result.json").write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(result), flush=True)
raise SystemExit(bool(failures))
