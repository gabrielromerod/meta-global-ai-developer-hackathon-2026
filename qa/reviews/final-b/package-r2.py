"""Hash-pin independently inspected R2 UI and pixel-free diagnostic PNGs."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.ui_evidence import pin_fixture, sha, validate_manifest

ROOT = Path("qa/screens/c965bedf")
manifest = ROOT / "final-b-privacy.json"
files = sorted(ROOT.rglob("*.png"))
assert not any("untracked" in str(p) for p in files)
fixtures = [
    ROOT / "final-b-fixture-api-states.json",
    ROOT / "final-b-r2-visual-probes.json",
    ROOT / "1470x870/final-b-r2-repairs.json",
    ROOT / "1470x870/final-b-r2-native.json",
    ROOT / "1470x870/final-b-r2-point.json",
    ROOT / "1470x870/final-b-owner-rule-fixture.json",
    ROOT / "390x844/final-b-r2-menu-scroll.json",
]
record = {
    "kind": "generated_ui",
    "source": "http://127.0.0.1:8119/next/",
    "reviewer": "final_review_b_round_2",
    "reviewed": True,
    "contains_camera_pixels": False,
    "authenticated": False,
    "fixture_hash_mode": "lf-normalized",
    "fixtures": [pin_fixture(p, manifest) for p in fixtures],
    "files": {p.relative_to(ROOT).as_posix(): sha(p) for p in files},
}
manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
count, failures = validate_manifest(ROOT, manifest)
result = {"evidence": {"kind": "fixture"}, "count": count, "failures": failures}
(ROOT / "final-b-privacy-result.json").write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(result), flush=True)
raise SystemExit(bool(failures))
