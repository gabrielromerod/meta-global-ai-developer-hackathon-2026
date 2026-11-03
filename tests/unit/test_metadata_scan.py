"""NFR-032: actual ExifTool metadata scan, fail closed on tool/read failures."""

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def scan(path, **env):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/metadata_scan.py"), str(path)],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_metadata_scan_clean_and_gps_device_tags(tmp_path):
    image = tmp_path / "generated.jpg"
    assert cv2.imwrite(str(image), np.full((24, 24, 3), 120, dtype=np.uint8))
    assert scan(tmp_path).returncode == 0
    subprocess.run(
        [
            "exiftool",
            "-overwrite_original",
            "-GPSLatitude=1",
            "-GPSLongitude=2",
            "-Make=Generated",
            "-Model=Test",
            str(image),
        ],
        capture_output=True,
        check=True,
    )
    result = scan(tmp_path)
    assert result.returncode == 1
    assert "GPS" in result.stdout
    assert "Make" in result.stdout
    assert "Generated" not in result.stdout  # tag values never printed


def test_metadata_scan_requires_exiftool(tmp_path):
    result = scan(tmp_path, EXIFTOOL=str(tmp_path / "missing-exiftool"))
    assert result.returncode == 1
    assert "FAIL" in result.stdout


def test_metadata_scan_rejects_unreadable_media(tmp_path):
    (tmp_path / "broken.jpg").write_bytes(b"not a jpeg")
    result = scan(tmp_path)
    assert result.returncode == 1
    assert "FAIL" in result.stdout


def test_metadata_scan_rejects_all_exif_not_just_gps(tmp_path):
    image = tmp_path / "generated.jpg"
    assert cv2.imwrite(str(image), np.full((24, 24, 3), 120, dtype=np.uint8))
    subprocess.run(
        ["exiftool", "-overwrite_original", "-DateTimeOriginal=2026:11:03 01:00:00", str(image)],
        capture_output=True,
        check=True,
    )
    result = scan(tmp_path)
    assert result.returncode == 1
    assert "DateTimeOriginal" in result.stdout


def test_metadata_scan_glb_checks_json_metadata(tmp_path):
    source = ROOT / "demo/synthetic/media/ground.glb"
    target = tmp_path / "massing.glb"
    target.write_bytes(source.read_bytes())
    assert scan(tmp_path).returncode == 0
    data = target.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20 : 20 + length])
    doc["asset"]["extras"] = {"GPSLatitude": "sensitive-value"}
    chunk = json.dumps(doc).encode()
    chunk += b" " * (-len(chunk) % 4)
    tail = data[20 + length :]
    target.write_bytes(
        struct.pack("<4sIIII", b"glTF", 2, 20 + len(chunk) + len(tail), len(chunk), 0x4E4F534A)
        + chunk
        + tail
    )
    result = scan(tmp_path)
    assert result.returncode == 1
    assert "GPSLatitude" in result.stdout
    assert "sensitive-value" not in result.stdout
