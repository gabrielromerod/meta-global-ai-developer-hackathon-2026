"""Hash-bound manual review of static generated UI/public-reference screenshots.

This never accepts footage. It verifies screenshot provenance, pixels decode, audio
absence and metadata. It makes no camera-polygon claim about UI screenshots.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vigil.ingest.metadata import scan as metadata_scan
from vigil.ingest.privacy import scan_media


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def pin_fixture(path: Path, manifest: Path) -> dict:
    content = path.read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(content).hexdigest()
    snapshot = manifest.parent / "proof-fixtures" / f"{path.stem}-{digest[:16]}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.exists() and fixture_sha(snapshot) != digest:
        raise ValueError("existing capture fixture snapshot changed")
    if not snapshot.exists():
        snapshot.write_bytes(content)
    return {
        "path": snapshot.relative_to(manifest.parent).as_posix(),
        "sha256": digest,
        "original_path": Path(
            os.path.relpath(path.resolve(), manifest.parent.resolve())
        ).as_posix(),
    }


def validate_manifest(root: Path, manifest: Path) -> tuple[int, list[str]]:
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            record.get("reviewed") is not True
            or not record.get("reviewer")
            or record.get("contains_camera_pixels") is not False
        ):
            raise ValueError("UI screenshots require explicit manual review and no camera pixels")
        source = urlparse(record.get("source", ""))
        if record.get("kind") == "generated_ui":
            if source.hostname not in {"localhost", "127.0.0.1"} or not record.get("fixtures"):
                raise ValueError("generated UI needs local static preview and fixture provenance")
            for fixture in record["fixtures"]:
                path = (manifest.parent / fixture["path"].replace("\\", "/")).resolve()
                digest = (
                    fixture_sha(path)
                    if record.get("fixture_hash_mode") == "lf-normalized"
                    else sha(path)
                )
                if digest != fixture["sha256"]:
                    raise ValueError("fixture changed after screenshot review")
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("evidence", {}).get("kind") != "fixture":
                    raise ValueError("UI screenshot source is not an explicit fixture")

                def check(value):
                    if isinstance(value, dict):
                        for key, child in value.items():
                            if key.endswith("_url") and child is not None:
                                raise ValueError(
                                    "UI screenshot fixture has media or external avatar pixels"
                                )
                            check(child)
                    elif isinstance(value, list):
                        for child in value:
                            check(child)

                check(data)
        elif record.get("kind") == "public_reference":
            domains = ("meta.com", "instagram.com", "messenger.com", "facebook.com", "meta.ai")
            host = source.hostname or ""
            if (
                source.scheme != "https"
                or not any(host == d or host.endswith("." + d) for d in domains)
                or record.get("authenticated") is not False
            ):
                raise ValueError("reference needs a logged-out public Meta product URL")
        else:
            raise ValueError("unsupported screenshot provenance")
        files = record["files"]
        if not files:
            raise ValueError("empty screenshot manifest")
        failures = []
        verified_paths = []
        root = root.resolve()
        for relative, digest in files.items():
            path = (root / relative).resolve()
            if (
                not path.is_relative_to(root)
                or path.suffix.lower() != ".png"
                or sha(path) != digest
            ):
                failures.append(f"{relative}: screenshot hash/path/type mismatch")
                continue
            report = scan_media(path, [])
            if not report.ok or report.frames != 1:
                failures.append(f"{relative}: screenshot failed decode/audio check")
            verified_paths.append(path)
        failures.extend(metadata_scan(root, files=verified_paths))
        return len(files), failures
    except (OSError, ValueError, KeyError, TypeError) as error:
        return 0, [str(error)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--fixture", type=Path, action="append", default=[])
    parser.add_argument("--reviewed", action="store_true", required=True)
    parser.add_argument("--reference", action="store_true")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--manifest", default="ui-privacy.json")
    args = parser.parse_args()
    manifest = args.root / args.manifest
    files = [args.root / f for f in args.file] if args.file else sorted(args.root.rglob("*.png"))
    record = {
        "kind": "public_reference" if args.reference else "generated_ui",
        "source": args.source,
        "reviewer": args.reviewer,
        "reviewed": args.reviewed,
        "contains_camera_pixels": False,
        "authenticated": False,
        "fixture_hash_mode": "lf-normalized",
        "fixtures": [pin_fixture(p, manifest) for p in args.fixture],
        "files": {p.relative_to(args.root).as_posix(): sha(p) for p in files},
    }
    manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    count, failures = validate_manifest(args.root, manifest)
    print(f"UI screenshot provenance: {count} named PNGs; {len(failures)} failures")
    for failure in failures:
        print(failure)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
