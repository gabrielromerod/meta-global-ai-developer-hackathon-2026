"""Spatial build: the offline-testable parts of FR-035 (scale, world frame, metadata)."""

from __future__ import annotations

import io
import json
import struct

import cv2
import numpy as np
import pytest
from PIL import ExifTags, Image

from vigil.spatial.scan import (
    Distance,
    SpatialBuildBlockedError,
    apply_scale,
    build_model,
    glb_size_ok,
    image_has_gps,
    read_glb,
    scale_check,
    strip_glb_metadata,
    strip_image_metadata,
    transform_points,
    world_frame,
)

# ---------------------------------------------------------------------------
# Scale check
# ---------------------------------------------------------------------------


def _distances(scale: float) -> list[Distance]:
    a1, b1 = np.array([0.0, 0.0, 0.0]), np.array([4.0, 0.0, 3.0])  # 5 m
    a2, b2 = np.array([1.0, 0.0, 1.0]), np.array([1.0, 0.0, 9.0])  # 8 m
    return [
        Distance(a=tuple(a1 * scale), b=tuple(b1 * scale), measured_m=5.0, name="fence"),
        Distance(a=tuple(a2 * scale), b=tuple(b2 * scale), measured_m=8.0, name="path"),
    ]


def test_scale_within_2_percent_is_accepted():
    res = scale_check(_distances(1.01))
    assert res.accepted
    assert res.factor == 1.0
    assert res.max_error == pytest.approx(0.01, abs=1e-9)


def test_scale_over_2_percent_is_rescaled_from_two_distances():
    res = scale_check(_distances(1.05))
    assert not res.accepted
    assert res.max_error == pytest.approx(0.05, abs=1e-9)
    assert res.factor == pytest.approx(1 / 1.05)
    rescaled = [
        Distance(a=tuple(apply_scale(d.a, res.factor)), b=tuple(apply_scale(d.b, res.factor)),
                 measured_m=d.measured_m)
        for d in _distances(1.05)
    ]  # fmt: skip
    again = scale_check(rescaled)
    assert again.accepted
    assert again.max_error < 1e-9


def test_scale_check_needs_two_distances():
    with pytest.raises(ValueError, match="2 measured distances"):
        scale_check(_distances(1.0)[:1])


# ---------------------------------------------------------------------------
# World frame
# ---------------------------------------------------------------------------


def _random_rigid(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r, _ = cv2.Rodrigues(rng.uniform(-1.5, 1.5, 3))
    t = np.eye(4)
    t[:3, :3] = r
    t[:3, 3] = rng.uniform(-20, 20, 3)
    return t


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_world_frame_from_three_clicked_points(seed):
    world_to_scan = _random_rigid(seed)
    door = transform_points(world_to_scan, [[0.0, 0.0, 0.0]])[0]
    wall = transform_points(world_to_scan, [[3.2, 0.0, 0.0]])[0]
    # The "up" click is not exactly vertical (2 cm off): the frame must still be orthonormal.
    up = transform_points(world_to_scan, [[0.02, 2.0, 0.0]])[0]
    t = world_frame(door, wall, up)
    r = t[:3, :3]
    assert np.allclose(r @ r.T, np.eye(3), atol=1e-9)
    assert np.linalg.det(r) == pytest.approx(1.0)
    pts = np.random.default_rng(seed).uniform(-10, 10, (20, 3))
    scan_pts = transform_points(world_to_scan, pts)
    back = transform_points(t, scan_pts)
    assert np.allclose(back, pts, atol=1e-6)
    assert np.allclose(transform_points(t, [door])[0], 0.0, atol=1e-9)


def test_world_frame_rejects_degenerate_clicks():
    with pytest.raises(ValueError):
        world_frame([0, 0, 0], [0, 0, 0], [0, 1, 0])
    with pytest.raises(ValueError):
        world_frame([0, 0, 0], [1, 0, 0], [2, 0, 0])


# ---------------------------------------------------------------------------
# Metadata stripping (NFR-032)
# ---------------------------------------------------------------------------


def _jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (48, 32), (200, 40, 40))
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "Apple"
    exif[ExifTags.Base.Model] = "iPhone 15 Pro"
    exif[ExifTags.IFD.GPSInfo] = {
        ExifTags.GPS.GPSLatitudeRef: "N",
        ExifTags.GPS.GPSLatitude: (1.0, 2.0, 3.0),
        ExifTags.GPS.GPSLongitudeRef: "E",
        ExifTags.GPS.GPSLongitude: (4.0, 5.0, 6.0),
    }
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes(), quality=90)
    return buf.getvalue()


def test_strip_jpeg_removes_gps_and_device(tmp_path):
    src = tmp_path / "still.jpg"
    src.write_bytes(_jpeg_with_gps())
    assert image_has_gps(src)
    dst = strip_image_metadata(src, tmp_path / "clean.jpg")
    data = dst.read_bytes()
    assert b"Exif" not in data
    assert b"iPhone" not in data
    assert b"Apple" not in data
    assert not image_has_gps(dst)
    with Image.open(dst) as im:
        assert im.size == (48, 32)
        assert len(im.getexif()) == 0
    # Pixels are untouched (lossless marker strip, no re-encode).
    with Image.open(src) as a, Image.open(dst) as b:
        assert np.array_equal(np.asarray(a), np.asarray(b))


def test_strip_png_text_chunks_in_place(tmp_path):
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Location", "somewhere secret")
    p = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), "blue").save(p, pnginfo=info)
    assert b"somewhere secret" in p.read_bytes()
    strip_image_metadata(p)
    assert b"somewhere secret" not in p.read_bytes()
    with Image.open(p) as im:
        assert im.size == (8, 8)


def _glb(doc: dict, bin_chunk: bytes) -> bytes:
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    bn = bin_chunk + b"\0" * (-len(bin_chunk) % 4)
    total = 12 + 8 + len(js) + 8 + len(bn)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(js), b"JSON") + js
        + struct.pack("<I4s", len(bn), b"BIN\0") + bn
    )  # fmt: skip


def test_strip_glb_metadata(tmp_path):
    jpeg = _jpeg_with_gps()
    mesh_bytes = bytes(range(24))
    blob = mesh_bytes + jpeg
    doc = {
        "asset": {"version": "2.0", "generator": "Scaniverse 4.1 iPhone 15 Pro",
                  "copyright": "home", "extras": {"gps": [1.0, 2.0]}},
        "extras": {"location": "lat 1 lon 2"},
        "extensionsUsed": ["KHR_xmp_json_ld"],
        "extensions": {"KHR_xmp_json_ld": {"packets": [{"dc:creator": "owner"}]}},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(mesh_bytes)},
            {"buffer": 0, "byteOffset": len(mesh_bytes), "byteLength": len(jpeg)},
        ],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 2, "type": "VEC3"}],
        "images": [{"bufferView": 1, "mimeType": "image/jpeg"}],
        "nodes": [{"name": "scan", "extras": {"device": "iPhone"}}],
    }  # fmt: skip
    src = tmp_path / "house.glb"
    src.write_bytes(_glb(doc, blob))
    dst = strip_glb_metadata(src, tmp_path / "house_clean.glb")
    raw = dst.read_bytes()
    assert struct.unpack_from("<I", raw, 8)[0] == len(raw)
    assert b"iPhone" not in raw
    assert b"Exif" not in raw
    assert b"lat 1" not in raw
    out, bin_out = read_glb(dst)
    assert out["asset"] == {"version": "2.0"}
    assert "extras" not in out
    assert "extras" not in out["nodes"][0]
    assert "KHR_xmp_json_ld" not in json.dumps(out)
    views = out["bufferViews"]
    assert (
        bin_out[views[0]["byteOffset"] : views[0]["byteOffset"] + views[0]["byteLength"]]
        == mesh_bytes
    )
    img = bin_out[views[1]["byteOffset"] : views[1]["byteOffset"] + views[1]["byteLength"]]
    with Image.open(io.BytesIO(img)) as im:
        assert im.size == (48, 32)
        assert len(im.getexif()) == 0
    assert out["buffers"][0]["byteLength"] <= len(bin_out)
    assert all(v["byteOffset"] % 4 == 0 for v in views)
    assert glb_size_ok(dst)


def test_glb_size_limit(tmp_path):
    p = tmp_path / "big.glb"
    p.write_bytes(b"\0" * 2048)
    assert glb_size_ok(p, max_mb=0.01)
    assert not glb_size_ok(p, max_mb=0.001)


# ---------------------------------------------------------------------------
# Registration and meshing are blocked offline
# ---------------------------------------------------------------------------


def test_build_model_is_blocked_with_a_clear_reason(tmp_path):
    with pytest.raises(
        SpatialBuildBlockedError, match=r"blocked: needs LiDAR scan export \(T-06\)"
    ):
        build_model([], _distances(1.0))
    seg = tmp_path / "front.ply"
    seg.write_text("ply\n", encoding="utf-8")
    with pytest.raises(SpatialBuildBlockedError, match="open3d"):
        build_model([seg], _distances(1.0))
