"""Package only manually reviewed null-media UI and pixel-free diagnostics."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.ui_evidence import pin_fixture, sha, validate_manifest

ROOT = Path("qa/screens/9a8ced22")
manifest = ROOT / "final-b-privacy.json"
rows = json.loads((ROOT / "final-b-matrix.json").read_text())["results"]
files = {ROOT / row["file"] for row in rows}
files.update((ROOT / "inspection-final-b").glob("*.png"))
# Supplemental images were opened individually; all media-bearing captures excluded.
names = [
    "1470x870/final-b-native-play-readout.png",
    "1470x870/final-b-native-pause-readout.png",
    "1280x600/final-b-front-garden-before-top.png",
    "1280x600/final-b-front-garden-top-ignored.png",
    "1470x870/final-b-chat-service-error-as-empty.png",
    "1470x870/final-b-microphone-start-failure.png",
    "1470x870/final-b-rule-draft-before-confirm.png",
    "1470x870/final-b-rule-still-draft-after-confirm.png",
    "1470x870/final-b-motion-timing-no-preference-readout.png",
    "1470x870/final-b-motion-timing-reduce-readout.png",
    "1470x870/final-b-chat-touch-citation.png",
    "1470x870/final-b-chat-citation-wrong-time.png",
    "1470x870/final-b-floating-popup-no-preference.png",
    "1470x870/final-b-floating-popup-reduce.png",
    "390x844/final-b-phone-toolbar-clipped.png",
]
files.update(ROOT / name for name in names)
files.update((ROOT / "390x844").glob("final-b-mobile-nav-*.png"))
assert all("untracked" not in str(p) for p in files)
assert all(p.is_file() for p in files), [str(p) for p in files if not p.is_file()]
fault_path = ROOT / "1470x870/final-b-faults.json"
fault = json.loads(fault_path.read_text())
fault["evidence"] = {
    "kind": "fixture",
    "source": (
        "Explicit 503 route injection and fake microphone stream counters; "
        "no actual microphone stream"
    ),
}
fault_path.write_text(json.dumps(fault, indent=2) + "\n")
fixtures = [
    ROOT / "final-b-fixture-api-states.json",
    ROOT / "1470x870/final-b-native-controls.json",
    ROOT / "1470x870/final-b-faults.json",
    ROOT / "1470x870/final-b-initial-reduced-motion.json",
    ROOT / "1470x870/final-b-owner-rule-fixture.json",
    ROOT / "1470x870/final-b-floating-popup.json",
    ROOT / "1470x870/final-b-chat-citation.json",
    ROOT / "390x844/final-b-mobile-nav.json",
    ROOT / "390x844/final-b-phone-toolbar.json",
]
record = {
    "kind": "generated_ui",
    "source": "http://127.0.0.1:8119/next/",
    "reviewer": "final_review_b",
    "reviewed": True,
    "contains_camera_pixels": False,
    "authenticated": False,
    "fixture_hash_mode": "lf-normalized",
    "fixtures": [pin_fixture(p, manifest) for p in fixtures],
    "files": {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)},
}
manifest.write_text(json.dumps(record, indent=2) + "\n")
count, failures = validate_manifest(ROOT, manifest)
result = {"evidence": {"kind": "fixture"}, "count": count, "failures": failures}
(ROOT / "final-b-privacy-result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result), flush=True)
raise SystemExit(bool(failures))
