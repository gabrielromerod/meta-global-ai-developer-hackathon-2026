"""Uncompressed GLB import for the raycast scene and the house viewer."""

import json
import struct
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from vigil.spatial.geometry import Occluder, RaycastScene, TriMesh
from vigil.spatial.scan import read_glb, strip_glb_metadata, transform_points, write_glb

MAX_GLB_BYTES = 15_000_000
COMPRESSED = ("KHR_draco_mesh_compression", "EXT_meshopt_compression")
DTYPES = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}


def _read(path):
    if Path(path).stat().st_size >= MAX_GLB_BYTES:
        raise ValueError("GLB must be below 15 MB")
    try:
        data = Path(path).read_bytes()
        if len(data) < 12 or struct.unpack_from("<I", data, 8)[0] != len(data):
            raise ValueError("invalid GLB container length")
        doc, blob = read_glb(path)
    except (struct.error, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid GLB container") from exc
    text = json.dumps(doc)
    if any(extension in text for extension in COMPRESSED):
        raise ValueError("Draco/meshopt GLB is unsupported; export an uncompressed GLB below 15 MB")
    if any(b.get("uri") for b in doc.get("buffers", [])) or any(
        i.get("uri") for i in doc.get("images", [])
    ):
        raise ValueError(
            "GLB must embed its buffers and textures; external resources are unsupported"
        )
    return doc, blob


def _accessor(doc, blob, index, kind):
    accessor = doc["accessors"][index]
    if accessor["type"] != kind or accessor.get("sparse"):
        raise ValueError("unsupported GLB accessor (type or sparse data)")
    if (kind == "VEC3" and accessor["componentType"] != 5126) or (
        kind == "SCALAR" and accessor["componentType"] not in (5121, 5123, 5125)
    ):
        raise ValueError("GLB positions must be floats and indices must be unsigned integers")
    dtype = np.dtype(DTYPES[accessor["componentType"]])
    width = 3 if kind == "VEC3" else 1
    view = doc["bufferViews"][accessor["bufferView"]]
    count = int(accessor["count"])
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    stride = int(view.get("byteStride", width * dtype.itemsize))
    end = start + (count - 1) * stride + width * dtype.itemsize
    if (
        view.get("buffer", 0) != 0
        or count < 1
        or start < int(view.get("byteOffset", 0))
        or stride < width * dtype.itemsize
        or end > len(blob)
        or end > int(view.get("byteOffset", 0)) + int(view["byteLength"])
    ):
        raise ValueError("GLB accessor exceeds its embedded buffer")
    return np.ndarray(
        (count, width), dtype=dtype, buffer=blob, offset=start, strides=(stride, dtype.itemsize)
    ).copy()


def _transform(node):
    if "matrix" in node:
        matrix = np.asarray(node["matrix"], float).reshape(4, 4, order="F")
    else:
        x, y, z, w = np.asarray(node.get("rotation", [0, 0, 0, 1]), float)
        length = np.linalg.norm([x, y, z, w])
        if length < 1e-10:
            raise ValueError("invalid GLB rotation")
        x, y, z, w = np.array([x, y, z, w]) / length
        rotation = np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )
        matrix = np.eye(4)
        matrix[:3, :3] = rotation @ np.diag(node.get("scale", [1, 1, 1]))
        matrix[:3, 3] = node.get("translation", [0, 0, 0])
    if not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0, 0, 0, 1]):
        raise ValueError("invalid GLB transform")
    return matrix


def _compact(mesh, faces):
    ids, inverse = np.unique(faces, return_inverse=True)
    return TriMesh(mesh.vertices[ids], inverse.reshape(-1, 3))


def _occluders(mesh, faces):
    # Separate disconnected solids so a convex footprint cannot fill the yard between them.
    parent = list(range(len(faces)))
    owner = {}
    _, vertex_ids = np.unique(np.round(mesh.vertices, 6), axis=0, return_inverse=True)

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, face in enumerate(faces):
        for vertex in vertex_ids[face]:
            previous = owner.setdefault(int(vertex), i)
            parent[root(i)] = root(previous)
    groups = {}
    for i, face in enumerate(faces):
        groups.setdefault(root(i), []).append(face)
    return [
        Occluder(f"glb-solid-{i}", _compact(mesh, np.asarray(group)))
        for i, group in enumerate(groups.values())
    ]


def load_glb_scene(path: Path, *, frame=None) -> RaycastScene:
    """Read static triangle geometry, applying scene/node transforms then the house frame.

    Ground is the lowest approximate horizontal plane (within 0.3 m, slope <= 35 degrees).
    Field review is required for steps, multiple levels and nonplanar terrain.
    """
    doc, blob = _read(path)
    nodes = doc.get("nodes", [])
    roots = doc.get("scenes", [{"nodes": list(range(len(nodes)))}])[doc.get("scene", 0)]["nodes"]
    meshes, visited = [], set()
    world = np.eye(4) if frame is None else np.asarray(frame, float).reshape(4, 4)
    if not np.isfinite(world).all() or not np.allclose(world[3], [0, 0, 0, 1]):
        raise ValueError("invalid house world frame")

    def visit(index, transform):
        if index < 0 or index >= len(nodes):
            raise ValueError("GLB node index is out of bounds")
        if index in visited:
            raise ValueError("GLB nodes have a cycle or multiple parents")
        visited.add(index)
        node = nodes[index]
        if "skin" in node:
            raise ValueError("animated/skinned GLB geometry is unsupported")
        transform = transform @ _transform(node)
        if "mesh" in node:
            for primitive in doc["meshes"][node["mesh"]]["primitives"]:
                if primitive.get("mode", 4) != 4 or primitive.get("targets"):
                    raise ValueError("GLB import requires static triangle primitives")
                vertices = _accessor(doc, blob, primitive["attributes"]["POSITION"], "VEC3")
                indices = (
                    _accessor(doc, blob, primitive["indices"], "SCALAR").ravel()
                    if "indices" in primitive
                    else np.arange(len(vertices))
                )
                if (
                    len(indices) % 3
                    or np.any(indices >= len(vertices))
                    or not np.isfinite(vertices).all()
                ):
                    raise ValueError("invalid GLB triangle indices or positions")
                meshes.append(
                    TriMesh(transform_points(world @ transform, vertices), indices.reshape(-1, 3))
                )
        for child in node.get("children", []):
            visit(child, transform)

    try:
        for index in roots:
            visit(index, np.eye(4))
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("malformed or unsupported GLB geometry") from exc
    mesh = TriMesh.concat(meshes)
    if not mesh.n_faces:
        raise ValueError("GLB has no triangle geometry")
    triangles = mesh.vertices[mesh.faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    areas = np.linalg.norm(normals, axis=1)
    horizontal = np.abs(normals[:, 1]) >= np.cos(np.deg2rad(35)) * areas
    horizontal &= areas > 1e-10
    if not horizontal.any():
        raise ValueError("GLB has no ground plane")
    centers = triangles.mean(axis=1)
    low = horizontal & (centers[:, 1] <= np.quantile(centers[horizontal, 1], 0.25))
    seed = np.flatnonzero(low)[np.argmax(areas[low])]
    normal = normals[seed] / areas[seed]
    ground = horizontal & (np.abs((centers - centers[seed]) @ normal) <= 0.3)
    return RaycastScene(_compact(mesh, mesh.faces[ground]), _occluders(mesh, mesh.faces[~ground]))


def import_glb(path: Path, out: Path, *, frame) -> Path:
    """Validate before writes, bake the same house frame into the viewer asset, strip metadata."""
    scene = load_glb_scene(path, frame=frame)
    doc, blob = _read(path)
    active = doc.setdefault("scenes", [{"nodes": list(range(len(doc["nodes"])))}])[
        doc.get("scene", 0)
    ]
    doc["nodes"].append(
        {"matrix": np.asarray(frame).flatten(order="F").tolist(), "children": active["nodes"]}
    )
    active["nodes"] = [len(doc["nodes"]) - 1]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    xmin, zmin, xmax, zmax = scene.ground.xz_bounds()
    twin = {
        "glb_url": "/media/model.glb",
        "ground": {"min": [xmin, zmin], "max": [xmax, zmax]},
        "spatial_acceptance": "Not verified: imported geometry needs field review",
    }
    with TemporaryDirectory(prefix="glb-import-", dir=out) as scratch:
        model = write_glb(Path(scratch) / "model.glb", doc, blob)
        strip_glb_metadata(model)
        _read(model)  # enforce the limit again after adding the frame
        twin_path = Path(scratch) / "twin.json"
        twin_path.write_text(json.dumps(twin, indent=2) + "\n", encoding="utf-8")
        model.replace(out / "model.glb")
        twin_path.replace(out / "twin.json")
    return out / "model.glb"
