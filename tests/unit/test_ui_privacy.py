"""UI evidence needs hash-bound review provenance; camera media keeps its strict gate."""

import hashlib
import json

import cv2
import numpy as np

from scripts.privacy_scan import main


def test_ui_audit_parallelism_keeps_every_hash_decode_and_metadata_failure(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    from scripts import ui_evidence

    root = tmp_path / "qa"
    root.mkdir()
    fixture = root / "state.json"
    fixture.write_text(json.dumps({"evidence": {"kind": "fixture"}, "clip_url": None}))
    names = ["a.png", "bad.png", "c.png", "d.png"]
    for name in names:
        assert cv2.imwrite(str(root / name), np.zeros((8, 8, 3), dtype=np.uint8))
    manifest = root / "ui-privacy.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "generated_ui",
                "source": "http://localhost/preview",
                "reviewer": "fixture",
                "reviewed": True,
                "contains_camera_pixels": False,
                "fixtures": [{"path": "state.json", "sha256": ui_evidence.sha(fixture)}],
                "files": {name: ui_evidence.sha(root / name) for name in names},
            }
        )
    )
    overlap = threading.Event()
    lock = threading.Lock()
    active = 0
    decoded = []
    metadata = []

    def decode(path, polygons):
        nonlocal active
        with lock:
            active += 1
            if active > 1:
                overlap.set()
        overlap.wait(1)
        with lock:
            decoded.append(path.name)
            active -= 1
        return SimpleNamespace(ok=path.name != "bad.png", frames=1)

    def scan_metadata(path, *, files):
        metadata.extend(p.name for p in files)
        return ["fixture metadata failure"]

    monkeypatch.setattr(ui_evidence, "scan_media", decode)
    monkeypatch.setattr(ui_evidence, "metadata_scan", scan_metadata)
    count, failures = ui_evidence.validate_manifest(root, manifest)
    assert overlap.is_set()
    assert count == 4
    assert sorted(decoded) == sorted(names)
    assert metadata == names
    assert failures == ["bad.png: screenshot failed decode/audio check", "fixture metadata failure"]


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


def test_capture_manifest_pins_immutable_fixture_snapshot(tmp_path, monkeypatch):
    import sys

    from scripts import ui_evidence

    root = tmp_path / "qa"
    root.mkdir()
    assert cv2.imwrite(str(root / "home.png"), np.zeros((8, 8, 3), dtype=np.uint8))
    fixture = tmp_path / "state.json"
    fixture.write_text(json.dumps({"evidence": {"kind": "fixture"}, "clip_url": None}))
    original = fixture.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ui_evidence",
            str(root),
            "--source",
            "http://localhost/preview",
            "--reviewer",
            "fixture",
            "--fixture",
            str(fixture),
            "--reviewed",
        ],
    )
    assert ui_evidence.main() == 0
    record = json.loads((root / "ui-privacy.json").read_text())
    snapshot = (root / record["fixtures"][0]["path"]).resolve()
    assert snapshot != fixture
    assert snapshot.read_bytes() == original
    fixture.write_text("changed live fixture")
    assert ui_evidence.validate_manifest(root, root / "ui-privacy.json")[1] == []
    snapshot.write_text("tampered snapshot")
    assert ui_evidence.validate_manifest(root, root / "ui-privacy.json")[1]


def _owner_reviewed_capture(root):
    from scripts.ui_evidence import sha

    root.mkdir()
    image = root / "home.png"
    assert cv2.imwrite(str(image), np.zeros((16, 16, 3), dtype=np.uint8))
    files = {"home.png": sha(image)}
    return {
        "kind": "owner_reviewed_ui",
        "source": "http://127.0.0.1:8000/#/home",
        "reviewer": "Fixture owner",
        "reviewed": True,
        "contains_camera_pixels": True,
        "privacy": {
            "masked_previews": True,
            "no_identifying_details": True,
            "no_raw_media": True,
        },
        "owner_approval": {
            "confirmed": True,
            "date": "2026-11-04",
            "scope": "private_repository_readme",
            "statement": "I reviewed and approve this exact screenshot for the private repo.",
            "files": dict(files),
        },
        "files": files,
    }


def test_owner_reviewed_ui_requires_approval_bound_to_the_exact_capture(tmp_path):
    from scripts.ui_evidence import validate_manifest

    root = tmp_path / "qa"
    record = _owner_reviewed_capture(root)
    manifest = root / "owner-privacy.json"
    manifest.write_text(json.dumps(record))
    assert validate_manifest(root, manifest) == (1, [])
    # Replacing an approved image cannot reuse its owner's previous approval.
    record["files"]["home.png"] = "0" * 64
    manifest.write_text(json.dumps(record))
    assert validate_manifest(root, manifest)[1]


def test_owner_reviewed_ui_fails_closed_without_scoped_review(tmp_path):
    from copy import deepcopy

    from scripts.ui_evidence import validate_manifest

    root = tmp_path / "qa"
    original = _owner_reviewed_capture(root)
    manifest = root / "owner-privacy.json"
    changes = [
        ("owner_approval", "confirmed", False),
        ("owner_approval", "date", "not-a-date"),
        ("owner_approval", "scope", "public_release"),
        ("owner_approval", "statement", ""),
        ("privacy", "masked_previews", False),
        ("privacy", "no_identifying_details", False),
        ("privacy", "no_raw_media", False),
    ]
    for section, key, value in changes:
        record = deepcopy(original)
        record[section][key] = value
        manifest.write_text(json.dumps(record))
        assert validate_manifest(root, manifest)[1], (section, key)
    for key, value in [("source", "https://example.com/"), ("contains_camera_pixels", False)]:
        record = deepcopy(original)
        record[key] = value
        manifest.write_text(json.dumps(record))
        assert validate_manifest(root, manifest)[1], key


def test_owner_review_does_not_bypass_image_decoding(tmp_path):
    from scripts.ui_evidence import sha, validate_manifest

    root = tmp_path / "qa"
    record = _owner_reviewed_capture(root)
    (root / "home.png").write_bytes(b"not an image")
    record["files"] = {"home.png": sha(root / "home.png")}
    record["owner_approval"]["files"] = dict(record["files"])
    manifest = root / "owner-privacy.json"
    manifest.write_text(json.dumps(record))
    assert validate_manifest(root, manifest)[1]
