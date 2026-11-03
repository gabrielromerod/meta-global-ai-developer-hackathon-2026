"""CI gate: every tracked QA media asset is covered by checked screenshot provenance."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ui_evidence import validate_manifest
from vigil.ingest.media import IMAGE_EXTS, VIDEO_EXTS

ROOT = Path(__file__).resolve().parents[1]


def audit_tree(root: Path, tracked: list[str]) -> list[str]:
    root = root.resolve()
    assets = {
        root / name
        for name in tracked
        if Path(name).suffix.lower()
        in IMAGE_EXTS | VIDEO_EXTS | {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus"}
    }
    manifests = [root / name for name in tracked if name.endswith("privacy.json")]
    covered = set()
    failures = []
    for manifest in manifests:
        _, errors = validate_manifest(manifest.parent, manifest)
        failures.extend(f"{manifest.relative_to(root)}: {error}" for error in errors)
        try:
            record = json.loads(manifest.read_text(encoding="utf-8"))
            covered.update((manifest.parent / name).resolve() for name in record["files"])
        except (OSError, ValueError, KeyError, TypeError):
            failures.append(f"{manifest.relative_to(root)}: invalid provenance manifest")
    for asset in sorted(assets - covered):
        failures.append(
            f"{asset.relative_to(root)}: tracked media has no reviewed provenance manifest"
        )
    return failures


def main() -> int:
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z", "qa"], cwd=ROOT).decode().split("\0")
    )
    failures = audit_tree(ROOT, [name for name in tracked if name])
    for failure in failures:
        print("FAIL " + failure)
    print(f"Tracked QA provenance: {len(failures)} failures")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
