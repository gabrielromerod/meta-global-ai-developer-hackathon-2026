"""Coverage map and blind regions (FR-038; spec 7 "Coverage map and blind spots").

On a 0.25 m ground grid a cell is visible to a camera when its ground point projects inside
the image, falls outside every privacy polygon, and has a clear line of sight (ray cast
against the occluder mesh and the terrain height grid). Cells no camera sees form the blind
regions, such as "behind the shed"; they are 4-connected components turned into polygons in
world metres (x, z) and written to ``cameras.yaml`` as ``blind_regions`` so the topology and
gap logic (FR-010, FR-011) come from measured geometry.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml
from shapely.geometry import LineString, box
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.ops import unary_union

from vigil.models import BlindRegion, Calibration, Config, Polygon
from vigil.spatial.geometry import CameraGeom, RaycastScene

CELL_M = 0.25
MIN_REGION_CELLS = 4
"""Components smaller than this (0.25 m² at 0.25 m cells) are noise, not regions."""


@dataclass
class Coverage:
    """Per-camera visibility on a regular x/z grid plus the blind regions.

    Arrays have shape (rows along z, cols along x); cell (i, j) is centred at
    ``(x0 + (j + 0.5) * cell_m, z0 + (i + 0.5) * cell_m)``.
    """

    x0: float
    z0: float
    cell_m: float
    site: np.ndarray
    """Cells that are walkable ground (on the mesh, not inside an occluder or excluded)."""
    visible: dict[str, np.ndarray]
    regions: list[BlindRegion] = field(default_factory=list)
    region_masks: list[np.ndarray] = field(default_factory=list)
    """Cell mask of each region, in the same order as ``regions``."""

    @property
    def shape(self) -> tuple[int, int]:
        return self.site.shape

    @property
    def seen(self) -> np.ndarray:
        out = np.zeros(self.shape, bool)
        for v in self.visible.values():
            out |= v
        return out

    @property
    def blind(self) -> np.ndarray:
        return self.site & ~self.seen

    def cell_index(self, x: float, z: float) -> tuple[int, int] | None:
        j = int(np.floor((x - self.x0) / self.cell_m))
        i = int(np.floor((z - self.z0) / self.cell_m))
        rows, cols = self.shape
        if 0 <= i < rows and 0 <= j < cols:
            return i, j
        return None

    def visible_at(self, camera_id: str, x: float, z: float) -> bool:
        ij = self.cell_index(x, z)
        return bool(ij is not None and self.visible[camera_id][ij])

    def is_blind(self, x: float, z: float) -> bool:
        ij = self.cell_index(x, z)
        return bool(ij is not None and self.blind[ij])

    def cell_centers(self) -> tuple[np.ndarray, np.ndarray]:
        rows, cols = self.shape
        xs = self.x0 + (np.arange(cols) + 0.5) * self.cell_m
        zs = self.z0 + (np.arange(rows) + 0.5) * self.cell_m
        return np.meshgrid(xs, zs)

    def to_dict(self) -> dict:
        """JSON-ready form for the 3D viewer's coverage layer (one '0'/'1' string per row)."""

        def rows(a: np.ndarray) -> list[str]:
            return ["".join("1" if c else "0" for c in r) for r in a]

        return {
            "x0": self.x0,
            "z0": self.z0,
            "cell_m": self.cell_m,
            "rows": self.shape[0],
            "cols": self.shape[1],
            "site": rows(self.site),
            "visible": {k: rows(v) for k, v in self.visible.items()},
            "blind_regions": [r.model_dump(mode="json") for r in self.regions],
        }


def privacy_from_config(cfg: Config) -> dict[str, list[Polygon]]:
    """Pixel privacy polygons per camera, as configured for FR-003."""
    return {c.id: [list(p) for p in c.privacy] for c in cfg.cameras if c.privacy}


def _privacy_mask(geom: CameraGeom, polys: Sequence[Polygon]) -> np.ndarray:
    mask = np.zeros((geom.height, geom.width), np.uint8)
    for poly in polys:
        pts = np.round(np.asarray(poly, float)).astype(np.int32)
        if len(pts) >= 3:
            cv2.fillPoly(mask, [pts], 1)
    return mask.astype(bool)


def _camera_visibility(
    geom: CameraGeom,
    scene: RaycastScene,
    points: np.ndarray,
    privacy: Sequence[Polygon],
    max_range_m: float | None,
) -> np.ndarray:
    n = len(points)
    vis = np.zeros(n, bool)
    if n == 0:
        return vis
    uv, front = geom.project(points)
    # Guard against lens models wrapping far off-axis points back into the frame: the
    # point's ideal (undistorted) direction must lie within the image corners' directions.
    w1, h1 = geom.width - 1, geom.height - 1
    corners = np.array([[0, 0], [w1, 0], [0, h1], [w1, h1]], float)
    lim = np.abs(geom.undistort(corners)).max(axis=0) * 1.02
    cam = (geom.r @ points.T + geom.tvec).T
    with np.errstate(divide="ignore", invalid="ignore"):
        nx = cam[:, 0] / cam[:, 2]
        ny = cam[:, 1] / cam[:, 2]
    ok = front & (np.abs(nx) <= lim[0]) & (np.abs(ny) <= lim[1])
    ok &= (uv[:, 0] >= 0) & (uv[:, 0] < geom.width) & (uv[:, 1] >= 0) & (uv[:, 1] < geom.height)
    if max_range_m is not None:
        ok &= np.linalg.norm(points - geom.center, axis=1) <= max_range_m
    if privacy and ok.any():
        pm = _privacy_mask(geom, privacy)
        idx = np.flatnonzero(ok)
        u = np.clip(uv[idx, 0].astype(np.int64), 0, geom.width - 1)
        v = np.clip(uv[idx, 1].astype(np.int64), 0, geom.height - 1)
        ok[idx[pm[v, u]]] = False
    if ok.any():
        idx = np.flatnonzero(ok)
        clear = scene.segment_clear(geom.center[None], points[idx])
        vis[idx[clear]] = True
    return vis


def coverage(
    ground: RaycastScene,
    cams: Sequence[Calibration],
    privacy: Mapping[str, Sequence[Polygon]] | None = None,
    cell_m: float = CELL_M,
    *,
    bounds: tuple[float, float, float, float] | None = None,
    max_range_m: float | None = None,
    min_region_cells: int = MIN_REGION_CELLS,
) -> Coverage:
    """Visibility grid and blind regions for a scene and calibrated cameras (FR-038).

    ``privacy`` maps camera id to pixel polygons (``privacy_from_config``). ``bounds`` is
    ``(xmin, zmin, xmax, zmax)`` in metres, defaulting to the ground mesh's extent.
    """
    privacy = privacy or {}
    xmin, zmin, xmax, zmax = bounds or ground.ground.xz_bounds()
    cols = max(1, int(np.floor((xmax - xmin) / cell_m + 1e-9)))
    rows = max(1, int(np.floor((zmax - zmin) / cell_m + 1e-9)))
    xs = xmin + (np.arange(cols) + 0.5) * cell_m
    zs = zmin + (np.arange(rows) + 0.5) * cell_m
    gx, gz = np.meshgrid(xs, zs)
    gy = ground.height_at(gx, gz)
    site = np.isfinite(gy)
    site &= ~ground.inside_occluder(gx, gz).reshape(gx.shape)
    flat_idx = np.flatnonzero(site.ravel())
    points = np.column_stack([gx.ravel()[flat_idx], gy.ravel()[flat_idx], gz.ravel()[flat_idx]])

    visible: dict[str, np.ndarray] = {}
    geoms = [CameraGeom.from_calibration(c) for c in cams]
    for geom in geoms:
        v = np.zeros(rows * cols, bool)
        v[flat_idx] = _camera_visibility(
            geom, ground, points, privacy.get(geom.camera_id, []), max_range_m
        )
        visible[geom.camera_id] = v.reshape(rows, cols)

    cov = Coverage(x0=float(xmin), z0=float(zmin), cell_m=float(cell_m), site=site, visible=visible)
    cov.regions, cov.region_masks = blind_regions(cov, ground, geoms, min_region_cells)
    return cov


def _component_polygon(mask: np.ndarray, x0: float, z0: float, cell: float) -> ShapelyPolygon:
    ii, jj = np.nonzero(mask)
    cells = [
        box(x0 + j * cell, z0 + i * cell, x0 + (j + 1) * cell, z0 + (i + 1) * cell)
        for i, j in zip(ii.tolist(), jj.tolist(), strict=True)
    ]
    merged = unary_union(cells)
    if merged.geom_type != "Polygon":  # 4-connected cells always merge to one polygon
        merged = max(merged.geoms, key=lambda g: g.area)
    return merged.simplify(0.0)


def _behind(poly: ShapelyPolygon, scene: RaycastScene, geoms: Sequence[CameraGeom]) -> str | None:
    """Name of the occluder standing between a camera and the region, nearest first."""
    rep = poly.representative_point()
    hits: list[tuple[float, str]] = []
    for occ in scene.occluders:
        fp = occ.footprint_xz()
        for g in geoms:
            sight = LineString([(g.center[0], g.center[2]), (rep.x, rep.y)])
            if sight.intersects(fp):
                hits.append((fp.distance(poly), occ.name))
                break
    return min(hits)[1] if hits else None


def blind_regions(
    cov: Coverage,
    scene: RaycastScene,
    geoms: Sequence[CameraGeom] = (),
    min_cells: int = MIN_REGION_CELLS,
) -> tuple[list[BlindRegion], list[np.ndarray]]:
    """Connected blind components as ``BlindRegion`` polygons (largest first)."""
    blind = cov.blind.astype(np.uint8)
    n, labels = cv2.connectedComponents(blind, connectivity=4)
    comps = []
    for lab in range(1, n):
        m = labels == lab
        if int(m.sum()) >= min_cells:
            comps.append(m)
    comps.sort(key=lambda m: (-int(m.sum()), *np.argwhere(m)[0]))
    regions: list[BlindRegion] = []
    masks: list[np.ndarray] = []
    used: dict[str, int] = {}
    anon = 0
    for m in comps:
        poly = _component_polygon(m, cov.x0, cov.z0, cov.cell_m)
        name = _behind(poly, scene, geoms)
        if name is not None:
            used[name] = used.get(name, 0) + 1
            suffix = "" if used[name] == 1 else f"_{used[name]}"
            rid = f"{_slug(name)}_back{suffix}"
            label = f"behind the {name}" + (f" ({used[name]})" if used[name] > 1 else "")
        else:
            anon += 1
            rid, label = f"blind_{anon}", f"blind region {anon}"
        coords = [(round(float(x), 3), round(float(z), 3)) for x, z in poly.exterior.coords[:-1]]
        regions.append(BlindRegion(id=rid, name=label, polygon_m=coords))
        masks.append(m)
    return regions, masks


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_") or "occluder"


# ---------------------------------------------------------------------------
# cameras.yaml
# ---------------------------------------------------------------------------


def blind_regions_to_config(
    cfg: Mapping, regions: Sequence[BlindRegion], replace_all: bool = False
) -> dict:
    """Return a copy of a ``cameras.yaml`` dict with ``blind_regions`` updated.

    Regions with an existing id are replaced in place; new ones are appended. With
    ``replace_all`` the list is exactly ``regions``. The input is not modified.
    """
    out = copy.deepcopy(dict(cfg))
    new = [
        {"id": r.id, "name": r.name, "polygon_m": [[float(x), float(z)] for x, z in r.polygon_m]}
        for r in regions
    ]
    if replace_all:
        out["blind_regions"] = new
        return out
    existing = list(out.get("blind_regions") or [])
    pos = {r.get("id"): i for i, r in enumerate(existing)}
    for r in new:
        if r["id"] in pos:
            existing[pos[r["id"]]] = r
        else:
            pos[r["id"]] = len(existing)
            existing.append(r)
    out["blind_regions"] = existing
    return out


def write_blind_regions(
    path: Path | str,
    regions: Sequence[BlindRegion],
    out_path: Path | str | None = None,
    replace_all: bool = False,
) -> Path:
    """Read a cameras.yaml, update its blind regions, validate it and write it back.

    YAML comments are not preserved (PyYAML); the result is validated against
    ``vigil.models.Config`` before anything is written.
    """
    src = Path(path)
    raw = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    updated = blind_regions_to_config(raw, regions, replace_all=replace_all)
    Config.model_validate(updated)
    dst = Path(out_path) if out_path is not None else src
    dst.write_text(yaml.safe_dump(updated, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return dst
