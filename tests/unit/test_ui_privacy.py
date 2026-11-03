"""UI evidence needs hash-bound review provenance; camera media keeps its strict gate."""

import hashlib
import json

import cv2
import numpy as np

from scripts.privacy_scan import main


def test_generated_ui_provenance_is_scoped_and_tamper_evident(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    image = root / "home.png"
    assert cv2.imwrite(str(image), np.full((24, 24, 3), 120, dtype=np.uint8))
    fixture = root / "state.json"
    fixture.write_text(
        json.dumps({"evidence": {"kind": "fixture"}, "clip_url": None, "thumbnail_url": None})
    )
    manifest = root / "ui-privacy.json"
    record = {
        "kind": "generated_ui",
        "source": "http://127.0.0.1:8103/next/preview.html",
        "reviewer": "offline reviewer",
        "reviewed": True,
        "contains_camera_pixels": False,
        "fixtures": [
            {"path": str(fixture), "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()}
        ],
        "files": {"home.png": hashlib.sha256(image.read_bytes()).hexdigest()},
    }
    manifest.write_text(json.dumps(record))
    assert main([str(root), "--ui-manifest", str(manifest)]) == 0
    image.write_bytes(b"changed")
    assert main([str(root), "--ui-manifest", str(manifest)]) == 1


def test_ui_manifest_cannot_cover_real_camera_pixels(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    manifest = root / "ui-privacy.json"
    manifest.write_text(
        json.dumps({"kind": "generated_ui", "contains_camera_pixels": True, "files": {}})
    )
    assert main([str(root), "--ui-manifest", str(manifest)]) == 1


def test_ui_manifest_fixture_paths_are_portable(tmp_path, monkeypatch):
    import sys

    from scripts import ui_evidence

    root = tmp_path / "qa" / "screens"
    root.mkdir(parents=True)
    image = root / "home.png"
    assert cv2.imwrite(str(image), np.full((8, 8, 3), 120, dtype=np.uint8))
    fixture = tmp_path / "state.json"
    fixture.write_text(json.dumps({"evidence": {"kind": "fixture"}, "clip_url": None}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ui_evidence",
            str(root),
            "--source",
            "http://localhost:8103/preview",
            "--reviewer",
            "fixture-review",
            "--fixture",
            str(fixture),
            "--reviewed",
        ],
    )
    assert ui_evidence.main() == 0
    record = json.loads((root / "ui-privacy.json").read_text())
    assert "\\" not in record["fixtures"][0]["path"]


def test_ui_fixture_hash_normalizes_only_line_endings(tmp_path):
    from scripts.ui_evidence import fixture_sha

    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_bytes(b'{\r\n"evidence":{"kind":"fixture"}\r\n}')
    b.write_bytes(b'{\n"evidence":{"kind":"fixture"}\n}')
    assert fixture_sha(a) == fixture_sha(b)
    b.write_bytes(b'{\n"evidence":{"kind":"real"}\n}')
    assert fixture_sha(a) != fixture_sha(b)
