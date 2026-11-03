"""The offline WebGL viewer must ship its local runtime in a clean clone."""

import subprocess
from pathlib import Path


def test_twin_webgl_runtime_is_not_ignored() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("three.module.min.js", "three.core.min.js"):
        path = f"web/twin/vendor/three/build/{name}"
        assert (root / path).is_file()
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", path], cwd=root, capture_output=True
        )
        assert result.returncode == 1, f"WebGL runtime excluded from git: {path}"
