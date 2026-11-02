"""LiDAR scan build: scale, world frame, metadata stripping (FR-035; spec 7 "Processing").

Offline-testable parts live here in numpy and the standard library:

* ``scale_check``: compare 2 tape-measured distances with the scan; accept under 2% error,
  otherwise return the rescale factor.
* ``world_frame``: the world transform from 3 clicked points (origin at the front-door
  marker, +X along the front wall, +Y up, glTF convention).
* ``strip_image_metadata`` / ``strip_glb_metadata``: remove GPS and device metadata from
  JPEG/PNG stills and from GLB files (including JPEG textures embedded in the GLB).

Segment registration (3 point pairs then ICP), ground extraction from a real scan and mesh
simplification need the LiDAR export (T-06) and the optional ``spatial`` dependency group
(Open3D); ``build_model`` raises ``SpatialBuildBlockedError`` until both exist. The site-plan
fallback (flat ground plus boxes) is available today through ``vigil.spatial.geometry``.
"""

from __future__ import annotations

import contextlib
import io
import json
import struct
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

SCALE_ACCEPT = 0.02
GLB_MAX_MB = 15.0

Vec3 = tuple[float, float, float]


class SpatialBuildBlockedError(RuntimeError):
    """Raised when the build needs inputs or optional dependencies that are not available."""


class Distance(BaseModel):
    """A tape-measured distance between two points picked on the scan (scan units)."""

    model_config = ConfigDict(extra="forbid")

    a: Vec3
    b: Vec3
    measured_m: float
    name: str | None = None

    @property
    def scanned(self) -> float:
        return float(np.linalg.norm(np.subtract(self.b, self.a)))


class ScaleCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    errors: list[float]
    """Relative error |scanned - measured| / measured per distance."""
    max_error: float
    accepted: bool
    factor: float
    """Multiply scan coordinates by this (1.0 when accepted)."""


# ---------------------------------------------------------------------------
# Scale and frame
# ---------------------------------------------------------------------------


def scale_check(measured: Sequence[Distance], accept: float = SCALE_ACCEPT) -> ScaleCheck:
    """Check scan scale against at least 2 measured distances (FR-035, UC-10 errors)."""
    if len(measured) < 2:
        raise ValueError("scale check needs at least 2 measured distances")
    errors, ratios = [], []
    for d in measured:
        if d.measured_m <= 0 or d.scanned <= 0:
            raise ValueError(f"distance {d.name or ''} must be positive")
        errors.append(abs(d.scanned - d.measured_m) / d.measured_m)
        ratios.append(d.measured_m / d.scanned)
    max_err = float(max(errors))
    ok = max_err < accept
    return ScaleCheck(
        errors=[float(e) for e in errors],
        max_error=max_err,
        accepted=ok,
        factor=1.0 if ok else float(np.mean(ratios)),
    )


def apply_scale(points, factor: float) -> np.ndarray:
    return np.asarray(points, float) * factor


def world_frame(origin, x_point, up_point) -> np.ndarray:
    """4x4 transform from scan coordinates to the house frame (spec 7 step 3).

    ``origin`` is the front-door marker, ``x_point`` lies along the front wall (+X) and
    ``up_point`` is above the origin (+Y). +Y is orthogonalised against +X, and
    +Z = X x Y completes a right-handed frame, as glTF expects.
    """
    o = np.asarray(origin, float)
    x = np.asarray(x_point, float) - o
    if np.linalg.norm(x) < 1e-9:
        raise ValueError("the +X point coincides with the origin")
    x /= np.linalg.norm(x)
    y = np.asarray(up_point, float) - o
    y = y - (y @ x) * x
    if np.linalg.norm(y) < 1e-9:
        raise ValueError("the up point is collinear with the front wall")
    y /= np.linalg.norm(y)
    z = np.cross(x, y)
    r = np.stack([x, y, z])
    t = np.eye(4)
    t[:3, :3] = r
    t[:3, 3] = -r @ o
    return t


def transform_points(t: np.ndarray, points) -> np.ndarray:
    p = np.asarray(points, float).reshape(-1, 3)
    return p @ np.asarray(t)[:3, :3].T + np.asarray(t)[:3, 3]


# ---------------------------------------------------------------------------
# Image metadata (NFR-032)
# ---------------------------------------------------------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_PNG_DROP = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}


def strip_jpeg_bytes(data: bytes) -> bytes:
    """Remove EXIF/XMP (APP1), IPTC (APP13), other APPn and comments from a JPEG, losslessly.

    Keeps APP0 (JFIF), the ICC profile (APP2 ``ICC_PROFILE``) and APP14 (Adobe colour
    transform), which affect how pixels decode. Entropy-coded data is copied untouched.
    """
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    out = bytearray(b"\xff\xd8")
    i = 2
    n = len(data)
    while i < n:
        if data[i] != 0xFF:
            raise ValueError("corrupt JPEG marker stream")
        while i < n and data[i] == 0xFF:
            i += 1
        marker = data[i]
        i += 1
        if marker == 0xD9:
            out += b"\xff\xd9"
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            out += bytes([0xFF, marker])
            continue
        seg_len = struct.unpack(">H", data[i : i + 2])[0]
        segment = data[i : i + seg_len]
        payload = segment[2:]
        keep = True
        if 0xE1 <= marker <= 0xEF:
            keep = (marker == 0xE2 and payload.startswith(b"ICC_PROFILE")) or marker == 0xEE
        elif marker == 0xFE:
            keep = False
        if keep:
            out += bytes([0xFF, marker]) + segment
        i += seg_len
        if marker == 0xDA:  # start of scan: the rest is image data
            out += data[i:]
            break
    return bytes(out)


def strip_png_bytes(data: bytes) -> bytes:
    if not data.startswith(_PNG_SIG):
        raise ValueError("not a PNG")
    out = bytearray(_PNG_SIG)
    i = len(_PNG_SIG)
    while i < len(data):
        length = struct.unpack(">I", data[i : i + 4])[0]
        ctype = data[i + 4 : i + 8]
        end = i + 12 + length
        if ctype not in _PNG_DROP:
            out += data[i:end]
        i = end
    return bytes(out)


def _strip_any_image(data: bytes) -> bytes:
    if data[:2] == b"\xff\xd8":
        return strip_jpeg_bytes(data)
    if data.startswith(_PNG_SIG):
        return strip_png_bytes(data)
    from PIL import Image  # other formats: re-encode pixels only

    with Image.open(io.BytesIO(data)) as im:
        fmt = im.format or "PNG"
        clean = Image.frombytes(im.mode, im.size, im.tobytes())
    buf = io.BytesIO()
    clean.save(buf, fmt)
    return buf.getvalue()


def strip_image_metadata(src: Path | str, dst: Path | str | None = None) -> Path:
    """Write ``src`` without GPS, device or text metadata to ``dst`` (in place by default)."""
    s = Path(src)
    d = Path(dst) if dst is not None else s
    d.write_bytes(_strip_any_image(s.read_bytes()))
    return d


def image_has_gps(path: Path | str) -> bool:
    """True when the image carries an EXIF GPS block (the CI exiftool check, in Python)."""
    from PIL import Image

    with Image.open(path) as im:
        exif = im.getexif()
        return bool(exif.get_ifd(0x8825)) or 0x8825 in exif


# ---------------------------------------------------------------------------
# GLB metadata
# ---------------------------------------------------------------------------

_GLB_MAGIC = b"glTF"
_CHUNK_JSON = b"JSON"
_CHUNK_BIN = b"BIN\x00"
_META_EXTENSIONS = {"KHR_xmp_json_ld", "KHR_xmp"}


def read_glb(path: Path | str) -> tuple[dict, bytes]:
    data = Path(path).read_bytes()
    magic, version, _length = struct.unpack_from("<4sII", data, 0)
    if magic != _GLB_MAGIC or version != 2:
        raise ValueError("not a glTF 2.0 binary (GLB) file")
    i = 12
    doc: dict | None = None
    blob = b""
    while i < len(data):
        clen, ctype = struct.unpack_from("<I4s", data, i)
        chunk = data[i + 8 : i + 8 + clen]
        if ctype == _CHUNK_JSON:
            doc = json.loads(chunk.decode("utf-8"))
        elif ctype == _CHUNK_BIN and not blob:
            blob = chunk
        i += 8 + clen
    if doc is None:
        raise ValueError("GLB has no JSON chunk")
    return doc, blob


def write_glb(path: Path | str, doc: dict, blob: bytes) -> Path:
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    parts = [struct.pack("<I4s", len(js), _CHUNK_JSON), js]
    if blob:
        bn = blob + b"\x00" * (-len(blob) % 4)
        parts += [struct.pack("<I4s", len(bn), _CHUNK_BIN), bn]
    body = b"".join(parts)
    p = Path(path)
    p.write_bytes(struct.pack("<4sII", _GLB_MAGIC, 2, 12 + len(body)) + body)
    return p


def _drop_extras(node):
    if isinstance(node, dict):
        return {k: _drop_extras(v) for k, v in node.items() if k != "extras"}
    if isinstance(node, list):
        return [_drop_extras(v) for v in node]
    return node


def strip_glb_metadata(src: Path | str, dst: Path | str | None = None) -> Path:
    """Remove location and device metadata from a GLB (NFR-032).

    Drops every ``extras`` object, the asset generator and copyright, XMP extensions, and
    EXIF/text metadata inside embedded JPEG/PNG textures (repacking the binary buffer with
    4-byte alignment and updated buffer views).
    """
    doc, blob = read_glb(src)
    doc = _drop_extras(doc)
    asset = doc.get("asset", {})
    doc["asset"] = {k: asset[k] for k in ("version", "minVersion") if k in asset}
    if "extensions" in doc:
        doc["extensions"] = {
            k: v for k, v in doc["extensions"].items() if k not in _META_EXTENSIONS
        }
        if not doc["extensions"]:
            del doc["extensions"]
    for key in ("extensionsUsed", "extensionsRequired"):
        if key in doc:
            doc[key] = [e for e in doc[key] if e not in _META_EXTENSIONS]
            if not doc[key]:
                del doc[key]

    views = doc.get("bufferViews", [])
    image_views = {img["bufferView"] for img in doc.get("images", []) if "bufferView" in img}
    if blob and views:
        new_blob = bytearray()
        for idx, view in enumerate(views):
            if view.get("buffer", 0) != 0:
                continue
            start = view.get("byteOffset", 0)
            chunk = blob[start : start + view["byteLength"]]
            if idx in image_views:
                with contextlib.suppress(ValueError, OSError):  # unknown format: keep bytes
                    chunk = _strip_any_image(chunk)
            new_blob += b"\x00" * (-len(new_blob) % 4)
            view["byteOffset"] = len(new_blob)
            view["byteLength"] = len(chunk)
            new_blob += chunk
        blob = bytes(new_blob)
        if doc.get("buffers"):
            doc["buffers"][0]["byteLength"] = len(blob)
    return write_glb(dst if dst is not None else src, doc, blob)


def glb_size_ok(path: Path | str, max_mb: float = GLB_MAX_MB) -> bool:
    """FR-035 / NFR-030: the compressed GLB must be under 15 MB."""
    return Path(path).stat().st_size < max_mb * 1024 * 1024


# ---------------------------------------------------------------------------
# Build (blocked until the scan exists)
# ---------------------------------------------------------------------------

BLOCKED_MSG = "blocked: needs LiDAR scan export (T-06) and the optional spatial group (open3d)"


def build_model(segments: Sequence[Path], measured: Sequence[Distance]):
    """``vigil spatial build`` (FR-035): scale, register, world frame, ground, GLB.

    Registration (3 point pairs, then ICP) and meshing need Open3D and the real scan
    export, so this raises ``SpatialBuildBlockedError`` until both are available. Use the
    site-plan fallback (``geometry.plane_ground`` + ``geometry.box_mesh``) meanwhile.
    """
    if not segments:
        raise SpatialBuildBlockedError(f"{BLOCKED_MSG}: no scan segments given")
    missing = [str(p) for p in segments if not Path(p).exists()]
    if missing:
        raise SpatialBuildBlockedError(f"{BLOCKED_MSG}: missing segments {missing}")
    if len(measured) >= 2:
        scale_check(measured)  # validates the measurements early
    try:
        import open3d  # noqa: F401
    except ImportError as exc:
        raise SpatialBuildBlockedError(
            f"{BLOCKED_MSG}: open3d is not installed (uv sync --extra spatial)"
        ) from exc
    raise SpatialBuildBlockedError(
        f"{BLOCKED_MSG}: segment registration and meshing are not implemented until the scan "
        "export exists"
    )
