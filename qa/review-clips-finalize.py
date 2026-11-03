"""Combine independent cases and retain only evidence from the completed run."""

import json
import shutil
from pathlib import Path

workspace = Path(__file__).resolve().parents[1]
root = (workspace / "qa/screens/7c2ea321").resolve()
assert root == workspace / "qa/screens/7c2ea321"
cases = {}
for part in range(5):
    report = json.loads((root / f"review-clips-results-part{part}.json").read_text())
    assert not report["failures"], report["failures"]
    for case in report["cases"]:
        if case["width"] == 390 and part != 4:
            continue
        cases[(case["width"], case["height"], case["theme"], case["route"])] = case
assert len(cases) == 44, len(cases)
complete = {**report, "cases": list(cases.values()), "failures": []}
complete["images"] = sum(len(case["screens"]) for case in cases.values())
(root / "review-clips-results.json").write_text(json.dumps(complete, indent=2) + "\n")
valid = set()
for case in cases.values():
    folder = f"{case['width']}x{case['height']}"
    valid.update(f"{folder}/{name}" for name in case["screens"])
    for name in [
        "true-empty",
        "normal-motion-initial",
        "keyboard-traversal",
        "keyboard-tab-selection",
        "route-and-theme-transition",
    ]:
        valid.add(f"{folder}/review-clips-{case['route']}-{case['theme']}-extra-{name}.png")
valid.update(
    f"1280x600/{name.name}"
    for name in (root / "1280x600").glob("review-clips-media-dark-date-*.png")
)
moved = []
for file in root.glob("*/*.png"):
    if file.parent.name == "inspection" or file.relative_to(root).as_posix() in valid:
        continue
    source = file.resolve()
    assert source.is_relative_to(root)
    destination = (workspace / "qa/drafts/7c2ea321" / file.relative_to(root)).resolve()
    assert destination.is_relative_to(workspace / "qa/drafts")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source, destination)
    moved.append(str(file.relative_to(root)))
print(
    json.dumps(
        {
            "cases": len(cases),
            "matrix_images": complete["images"],
            "retained_originals": len(valid),
            "draft_files_moved": len(moved),
        },
        indent=2,
    )
)
