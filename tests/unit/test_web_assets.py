"""A clean clone pins its local WebGL runtime and includes its React source."""

import json
import subprocess
from pathlib import Path


def test_twin_webgl_runtime_is_pinned_and_its_sources_are_not_ignored():
    root = Path(__file__).resolve().parents[2]
    lock = json.loads((root / "web-next/package-lock.json").read_text(encoding="utf-8"))
    for package in ("three", "@react-three/fiber", "@react-three/drei"):
        entry = lock["packages"]["node_modules/" + package]
        assert entry["integrity"].startswith("sha512-")
        assert entry["version"]
    for path in (
        "web-next/package-lock.json",
        "web-next/src/twin/index.tsx",
        "web-next/src/twin/geometry.ts",
    ):
        assert (root / path).is_file()
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", path], cwd=root, capture_output=True
        )
        assert result.returncode == 1, f"Required React runtime input excluded from Git: {path}"
