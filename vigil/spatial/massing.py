"""Simplified house massing from LiDAR scan segments (FR-035, fallback ladder level 2).

A handheld LiDAR scan sees ground, walls and fences but not roofs, and two loops rarely share
enough surface for ICP. This module turns aligned scan segments plus an operator recipe
(rectangles traced on a top-down orthophoto) into a light, untextured massing for the viewer:

1. ``sample_glb_points``: uniform surface samples (and texture colours) from each GLB.
2. ``align_segment``: rotate/translate a segment into the reference segment (yaw about +Y,
   ground level matched). The pose comes from wall lines (``wall_peaks``/``axis_angle``),
   because gravity-aligned phone scans only differ by yaw and translation.
3. ``house_frame``: the Vigil frame (origin at the front door, +Y up, +Z into the house,
   right-handed; a rotation, never a mirror).
4. ``build_massing``: measures eave and fence heights and classifies ground surfaces from the
   points; roofs are inferred from an assumed pitch because the scan cannot see them.

The output never carries textures, coordinates on Earth, addresses or meshes
(``validate_massing``). It is private: it stays in ``data/spatial`` and is only served to
LAN or loopback clients. See ``docs/runbooks/house-massing.md``.
"""

from __future__ import annotations

import io
import math
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

UNTEXTURED = np.array([180, 180, 180], np.uint8)
BOX_KINDS = {"building", "tree_barrier"}
ROOF_TYPES = {"hip", "gable_x", "gable_z", "flat"}
SURFACE_KINDS = {"lawn", "paving", "gravel", "planting"}
DETAIL_KEYS = {
    "roofs",
    "fences",
    "surfaces",
    "porches",
    "pergolas",
    "doors",
    "trees",
    "solar",
    "notes",
}
FORBIDDEN = {
    "address",
    "lat",
    "lon",
    "lng",
    "latitude",
    "longitude",
    "gps",
    "street",
    "house_number",
    "glb_url",
    "texture",
    "image",
    "mesh",
    "compass",
    "north",
}
EAVE_RANGE = (2.0, 4.0)
FENCE_RANGE = (0.6, 3.0)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def sample_glb_points(path: Path, per_m2: float = 1500, seed: int = 0, max_per_face: int = 2000):
    """Area-weighted surface samples and base-colour texels of every triangle in a GLB."""
    from vigil.spatial.glb import _accessor, _read

    doc, blob = _read(path)
    rng = np.random.default_rng(seed)
    images = _images(doc, blob)
    points, colors = [], []
    for mesh in doc.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4:
                continue
            pos = _accessor(doc, blob, primitive["attributes"]["POSITION"], "VEC3").astype(float)
            idx = (
                _accessor(doc, blob, primitive["indices"], "SCALAR").reshape(-1, 3).astype(np.int64)
                if "indices" in primitive
                else np.arange(len(pos)).reshape(-1, 3)
            )
            a, b, c = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
            area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
            n = np.clip(np.ceil(area * per_m2).astype(int), 1, max_per_face)
            tri = np.repeat(np.arange(len(idx)), n)
            r1 = np.sqrt(rng.random(len(tri)))
            r2 = rng.random(len(tri))
            w = np.c_[1 - r1, r1 * (1 - r2), r1 * r2]
            corners = idx[tri]
            p = sum(pos[corners[:, k]] * w[:, k : k + 1] for k in range(3))
            points.append(p)
            colors.append(_texels(doc, blob, primitive, corners, w, images))
    if not points:
        raise ValueError("GLB has no triangle geometry")
    return np.concatenate(points), np.concatenate(colors)


def _images(doc, blob):
    if not doc.get("images"):
        return []
    try:
        from PIL import Image
    except ImportError:  # optional: colours fall back to grey
        return []
    out = []
    for image in doc["images"]:
        view = doc["bufferViews"][image["bufferView"]]
        start = int(view.get("byteOffset", 0))
        data = blob[start : start + int(view["byteLength"])]
        out.append(np.asarray(Image.open(io.BytesIO(data)).convert("RGB")))
    return out


def _texels(doc, blob, primitive, corners, w, images):
    from vigil.spatial.glb import DTYPES

    material = (
        doc.get("materials", [{}])[primitive.get("material", 0)] if doc.get("materials") else {}
    )
    texture = material.get("pbrMetallicRoughness", {}).get("baseColorTexture", {}).get("index")
    if texture is None or "TEXCOORD_0" not in primitive["attributes"] or not images:
        return np.tile(UNTEXTURED, (len(corners), 1))
    accessor = doc["accessors"][primitive["attributes"]["TEXCOORD_0"]]
    view = doc["bufferViews"][accessor["bufferView"]]
    dtype = np.dtype(DTYPES[accessor["componentType"]])
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    stride = int(view.get("byteStride", 2 * dtype.itemsize))
    uv = np.ndarray(
        (int(accessor["count"]), 2),
        dtype=dtype,
        buffer=blob,
        offset=start,
        strides=(stride, dtype.itemsize),
    ).astype(float)
    if dtype != np.float32:
        uv /= np.iinfo(dtype).max
    t = sum(uv[corners[:, k]] * w[:, k : k + 1] for k in range(3))
    img = images[doc["textures"][texture]["source"]]
    h, wd = img.shape[:2]
    x = np.clip(((t[:, 0] % 1) * wd).astype(int), 0, wd - 1)
    y = np.clip(((t[:, 1] % 1) * h).astype(int), 0, h - 1)
    return img[y, x]


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------


def wall_peaks(values, lo: float, hi: float, res: float = 0.05, top: int = 6, min_sep: float = 0.3):
    """Strongest wall/fence lines along one axis: histogram peaks at least ``min_sep`` apart."""
    bins = np.arange(lo, hi + res, res)
    counts, _ = np.histogram(np.asarray(values, float), bins)
    peaks: list[tuple[float, int]] = []
    for i in np.argsort(counts)[::-1]:
        if counts[i] == 0 or len(peaks) >= top:
            break
        centre = float(bins[i] + res / 2)
        if all(abs(centre - p) > min_sep for p, _ in peaks):
            peaks.append((centre, int(counts[i])))
    return sorted(peaks, key=lambda p: -p[1])


def axis_angle(xz) -> float:
    """Direction (degrees, -90..90) of a straight wall from its points' principal axis."""
    q = np.asarray(xz, float)
    q = q - q.mean(axis=0)
    _, _, vt = np.linalg.svd(q, full_matrices=False)
    dx, dz = vt[0]
    if dx < 0:
        dx, dz = -dx, -dz
    return math.degrees(math.atan2(dz, dx))


def _yaw(deg: float) -> np.ndarray:
    r = math.radians(deg)
    return np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]])


def align_segment(points, segment: dict) -> np.ndarray:
    """Segment into reference coordinates: yaw about +Y, then translate in X/Z, match ground."""
    p = np.asarray(points, float).copy()
    p[:, [0, 2]] = p[:, [0, 2]] @ _yaw(segment.get("rotate_deg", 0.0)).T + segment.get(
        "translate", [0.0, 0.0]
    )
    p[:, 1] += segment.get("reference_base_y", 0.0) - segment.get("base_y", 0.0)
    return p


def ground_level(points, region: Sequence[float], q: float = 3) -> float:
    """Ground height next to the house: a low percentile inside ``[x0, z0, x1, z1]``."""
    p = np.asarray(points, float)
    x0, z0, x1, z1 = region
    m = (p[:, 0] > x0) & (p[:, 0] < x1) & (p[:, 2] > z0) & (p[:, 2] < z1)
    if m.sum() < 20:
        raise ValueError("too few points to estimate the ground level in that region")
    return float(np.percentile(p[m, 1], q))


def house_rotation(front_angle_deg: float) -> np.ndarray:
    """3x3 rotation: front wall along X, then 180 degrees about +Y so the house lies at +Z."""
    level = np.eye(3)
    level[np.ix_([0, 2], [0, 2])] = _yaw(-front_angle_deg)
    turn = np.diag([-1.0, 1.0, -1.0])
    return turn @ level


def house_frame(door, front_angle_deg: float, base_y: float) -> Callable[[np.ndarray], np.ndarray]:
    """Reference scan coordinates -> Vigil house frame (metres, origin at the front door)."""
    rot = house_rotation(front_angle_deg)
    origin = np.array([door[0], base_y, door[1]], float)

    def apply(points):
        return (np.asarray(points, float) - origin) @ rot.T

    return apply


# ---------------------------------------------------------------------------
# Massing
# ---------------------------------------------------------------------------


def _inside(p, lo, hi, pad=0.0):
    return (
        (p[:, 0] > lo[0] - pad)
        & (p[:, 0] < hi[0] + pad)
        & (p[:, 2] > lo[1] - pad)
        & (p[:, 2] < hi[1] + pad)
    )


def _eave(points, lo, hi, band=0.4) -> float | None:
    """Top of the walls: median over 0.5 m wall stretches of each stretch's top.

    Points within ``band`` of the footprint edges are cut into stretches along the perimeter;
    each stretch reports its 98th-percentile height. The median ignores the few stretches that
    carry a gable, a gutter or a shrub.
    """
    p = points
    near = _inside(p, lo, hi, band) & ~_inside(p, np.add(lo, band), np.subtract(hi, band))
    near &= p[:, 1] > 0.5
    if near.sum() < 50:
        return None
    q = p[near]
    (x0, z0), (x1, z1) = lo, hi
    w, d = x1 - x0, z1 - z0
    x, z = np.clip(q[:, 0], x0, x1), np.clip(q[:, 2], z0, z1)
    gaps = np.c_[z - z0, x1 - x, z1 - z, x - x0]
    side = np.argmin(gaps, axis=1)
    along = np.choose(side, [x - x0, w + z - z0, w + d + x1 - x, 2 * w + d + z1 - z])
    stretch = np.floor(along / 0.5).astype(int)
    tops = [
        np.percentile(q[stretch == s, 1], 98)
        for s in np.unique(stretch)
        if (stretch == s).sum() >= 10
    ]
    if not tops:
        return None
    return float(np.clip(np.median(tops), *EAVE_RANGE))


def _fence_height(points, a, b, band=0.25) -> float | None:
    p = points
    d = np.subtract(b, a)
    length = float(np.hypot(*d))
    if length < 1e-6:
        return None
    rel = p[:, [0, 2]] - a
    along = rel @ d / length
    across = np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0]) / length
    m = (along > 0) & (along < length) & (across < band) & (p[:, 1] > 0.2)
    if m.sum() < 50:
        return None
    return float(np.clip(np.percentile(p[m, 1], 97), *FENCE_RANGE))


def surface_kind(colors) -> str:
    """Majority class of ground texels: green -> lawn, rough grey -> gravel, else paving."""
    c = np.asarray(colors, float)
    if not len(c):
        return "paving"
    r, g, b = c.T
    green = (g > r * 1.02) & (g > b * 1.08)
    if green.mean() > 0.35:
        return "lawn"
    lum = c @ [0.299, 0.587, 0.114]
    return "gravel" if lum.std() > 34 else "paving"


def roof_rise(width: float, depth: float, roof: str, pitch: float) -> float:
    if roof == "flat":
        return 0.0
    if roof == "gable_x":  # ridge along X: slopes span the depth
        return depth / 2 * pitch
    if roof == "gable_z":
        return width / 2 * pitch
    return min(width, depth) / 2 * pitch


def build_massing(recipe: dict, points=None, colors=None) -> dict:
    """Massing document from a recipe in house-frame metres, measuring what the scan supports."""
    p = np.zeros((0, 3)) if points is None else np.asarray(points, float)
    c = np.zeros((0, 3), np.uint8) if colors is None else np.asarray(colors)
    pitch = float(recipe.get("pitch", 4 / 12))
    boxes, roofs, fences, surfaces = [], [], [], []
    measured: list[str] = []
    for b in recipe.get("buildings", []):
        lo, hi = b["min"], b["max"]
        h = b.get("h")
        if h is None and b.get("eave_from"):
            # A wing whose street face is a gable shares the eave of the body it joins.
            h = next(x["h"] for x in boxes if x["id"] == b["eave_from"])
        if h is None:
            h = _eave(p, lo, hi) if len(p) else None
            measured += [f"{b['id']} eave"] if h is not None else []
        h = float(h if h is not None else 2.8)
        boxes.append(
            {"id": b["id"], "kind": "building", "min": list(lo), "max": list(hi), "h": round(h, 2)}
        )
        roof = b.get("roof", "hip")
        rise = roof_rise(hi[0] - lo[0], hi[1] - lo[1], roof, pitch)
        roofs.append(
            {
                "id": b["id"],
                "type": roof,
                "min": list(lo),
                "max": list(hi),
                "eave": round(h, 2),
                "rise": round(rise, 2),
                "overhang": float(b.get("overhang", 0.4)),
            }
        )
    for f in recipe.get("fences", []):
        h = f.get("h")
        if h is None:
            h = _fence_height(p, f["from"], f["to"]) if len(p) else None
            measured += [f"{f['id']} height"] if h is not None else []
        fences.append(
            {
                "id": f["id"],
                "from": list(f["from"]),
                "to": list(f["to"]),
                "h": round(float(h if h is not None else 1.8), 2),
                "observed": bool(f.get("observed", h is not None)),
            }
        )
    for porch in recipe.get("porches", []):
        if porch.get("roof"):  # a porch roof seen on the satellite view, not by the scan
            roofs.append(
                {
                    "id": porch["id"],
                    "type": porch["roof"],
                    "min": list(porch["min"]),
                    "max": list(porch["max"]),
                    "eave": float(porch["h"]),
                    "rise": float(porch.get("rise", 0.5)),
                    "overhang": float(porch.get("overhang", 0.2)),
                }
            )
    for s in recipe.get("surfaces", []):
        kind = s.get("kind")
        if kind is None:
            m = (
                _inside(p, s["min"], s["max"]) & (np.abs(p[:, 1]) < 0.3)
                if len(p)
                else np.zeros(0, bool)
            )
            kind = surface_kind(c[m]) if m.any() else "paving"
            measured += [f"{s['id']} surface"]
        surfaces.append({"id": s["id"], "kind": kind, "min": list(s["min"]), "max": list(s["max"])})
    cameras = {
        cid: {**cam, "placement_measured": bool(cam.get("placement_measured", False))}
        for cid, cam in recipe.get("cameras", {}).items()
    }
    xs = [v for b in boxes for v in (b["min"][0], b["max"][0])] or [0.0]
    zs = [v for b in boxes for v in (b["min"][1], b["max"][1])] or [0.0]
    ground = recipe.get("ground") or {
        "min": [min(xs) - 3, min(zs) - 6],
        "max": [max(xs) + 3, max(zs) + 6],
    }
    doc = {
        "version": 1,
        "generic_massing": False,
        "ground": ground,
        "site_plan": {"boxes": boxes + [dict(t) for t in recipe.get("barriers", [])]},
        "detail": {
            "roofs": roofs,
            "fences": fences,
            "surfaces": surfaces,
            "porches": [dict(x) for x in recipe.get("porches", [])],
            "pergolas": [dict(x) for x in recipe.get("pergolas", [])],
            "solar": [dict(x) for x in recipe.get("solar", [])],
            "doors": [dict(x) for x in recipe.get("doors", [])],
            "trees": [dict(x) for x in recipe.get("trees", [])],
            "notes": {
                "measured": measured,
                "assumed": recipe.get(
                    "assumed",
                    [f"roof pitch {pitch:.3f} (roofs are not visible to a handheld scan)"],
                ),
            },
        },
        "camera_layout": cameras,
    }
    return validate_massing(doc)


def _walk(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield path + "." + str(k), k, v
            yield from _walk(v, path + "." + str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")


def validate_massing(doc: dict) -> dict:
    """Reject identifying fields, unknown kinds and non-finite numbers before anything is served."""
    for where, key, value in _walk(doc):
        if str(key).lower() in FORBIDDEN:
            raise ValueError(f"identifying field not allowed in a massing: {where}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"non-finite number at {where}")
    for box in doc.get("site_plan", {}).get("boxes", []):
        if box.get("kind") not in BOX_KINDS:
            raise ValueError(f"unknown box kind: {box.get('kind')}")
    detail = doc.get("detail", {})
    if set(detail) - DETAIL_KEYS:
        raise ValueError(f"unknown detail keys: {sorted(set(detail) - DETAIL_KEYS)}")
    for s in detail.get("surfaces", []):
        if s.get("kind") not in SURFACE_KINDS:
            raise ValueError(f"unknown surface kind: {s.get('kind')}")
    for r in detail.get("roofs", []):
        if r.get("type") not in ROOF_TYPES:
            raise ValueError(f"unknown roof type: {r.get('type')}")
    return doc


def private_twin(config, doc: dict) -> dict:
    """The /api/ui/twin payload for a private massing (LAN or loopback only)."""
    layout = doc.get("camera_layout", {})
    return {
        "generic_massing": False,
        "private_massing": True,
        "glb_url": None,
        "note": "Private house model from your LiDAR scan, simplified (no textures). "
        "Roof shape and camera placement are approximate until measured.",
        "ground": doc["ground"],
        "site_plan": doc["site_plan"],
        "detail": doc.get("detail", {}),
        "cameras": [
            {"id": c.id, "name": c.name, "width": c.width, "height": c.height, **layout[c.id]}
            for c in (config.cameras if config else [])
            if c.id in layout
        ],
        # Config blind regions are authored in the generic layout; coverage is recomputed later.
        "blind_regions": [],
        "coverage": [],
    }
