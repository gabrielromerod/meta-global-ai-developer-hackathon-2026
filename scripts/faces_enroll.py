"""Enrol faces from processed captures into data/faces.db (spec change 2026-11-04).

Local only: YuNet + SFace on this machine, frames from data/windows/<capture>. Needs
VIGIL_FACE_TEMPLATES=1 and the two ONNX files in data/models/. Purges faces older than
VIGIL_FACE_RETENTION_DAYS (default 30) first.

    VIGIL_FACE_TEMPLATES=1 uv run python scripts/faces_enroll.py <capture id> [...]
    VIGIL_FACE_TEMPLATES=1 uv run python scripts/faces_enroll.py --all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from vigil.api.faces import faces_enabled
from vigil.faces import FaceEngine, FaceStore, FacesUnavailable
from vigil.faces.enroll import enroll_capture
from vigil.ingest.config import load_config
from vigil.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("captures", nargs="*")
    parser.add_argument("--all", action="store_true", help="every processed capture")
    args = parser.parse_args(argv)
    if not faces_enabled():
        print("Face templates are off. Set VIGIL_FACE_TEMPLATES=1 to opt in.", file=sys.stderr)
        return 2
    settings = get_settings()
    data = Path(settings.data_dir)
    results = data / "results"
    ids = sorted(p.name for p in results.iterdir() if (p / "visits.json").is_file()) if args.all \
        else args.captures  # fmt: skip
    if not ids:
        parser.error("name a capture id or pass --all")
    engine = FaceEngine(data / "models")
    store = FaceStore(data / "faces.db")
    days = int(os.environ.get("VIGIL_FACE_RETENTION_DAYS", "30"))
    print(json.dumps({"purged": store.purge_older_than(days)}))
    cameras = load_config(Path("config/cameras.yaml")).cameras
    for capture_id in ids:
        try:
            report = enroll_capture(capture_id, results / capture_id, data / "windows" / capture_id,
                                    cameras, store, detect=engine.detect, embed=engine.embed,
                                    crop=engine.crop)  # fmt: skip
        except FacesUnavailable as exc:
            print(f"Face models missing: {exc}", file=sys.stderr)
            return 3
        print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
