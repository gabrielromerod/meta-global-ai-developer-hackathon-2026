"""Numpy geometry for the spatial model (spec 7): meshes, ray casting, height grid, cameras.

Open3D and trimesh are optional (pyproject ``spatial`` group), so everything the pipeline
needs at run time lives here in plain numpy plus OpenCV:

* ``TriMesh`` with vectorised Möller–Trumbore ray intersection.
* ``HeightGrid``: the 0.1 m ground height lookup from spec 7 step 4 (yards slope).
* ``RaycastScene``: the ground mesh (ray-cast target) plus named occluders (house, shed,
  fences) used for line of sight in the coverage map.
* ``CameraGeom``: projection and back-projection for a ``vigil.models.Calibration``.
* COCO RLE decode/encode for ``TrackFrame.mask_rle``.

World frame (spec 7 and ``vigil.models``): metres, origin at the front-door marker, +X along
the front wall, +Y up (glTF). The ground is the x/z plane. Camera frame follows OpenCV:
x right, y down, z forward; ``Extrinsics`` holds the world -> camera Rodrigues rotation.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np

from vigil.models import Calibration, Extrinsics, Intrinsics

FloatArray = np.ndarray

# ---------------------------------------------------------------------------
# Meshes and ray casting
# ---------------------------------------------------------------------------

_EPS = 1e-12
_PAIR_BUDGET = 250_000
"""Ray x triangle pairs evaluated per chunk; bounds memory to a few MB per array."""


@dataclass
class TriMesh:
    """An indexed triangle mesh in world metres."""

    vertices: FloatArray
    faces: np.ndarray

    def __post_init__(self) -> None:
        self.vertices = np.asarray(self.vertices, dtype=np.float64).reshape(-1, 3)
        self.faces = np.asarray(self.faces, dtype=np.int64).reshape(-1, 3)
        v = self.vertices
        f = self.faces
        if len(f):
            self._v0 = v[f[:, 0]]
            self._e1 = v[f[:, 1]] - self._v0
            self._e2 = v[f[:, 2]] - self._v0
        else:
            self._v0 = self._e1 = self._e2 = np.zeros((0, 3))

    @property
    def n_faces(self) -> int:
        return len(self.faces)

    @staticmethod
    def concat(meshes: Iterable[TriMesh]) -> TriMesh:
        verts: list[FloatArray] = []
        faces: list[np.ndarray] = []
        offset = 0
        for m in meshes:
            verts.append(m.vertices)
            faces.append(m.faces + offset)
            offset += len(m.vertices)
        if not verts:
            return TriMesh(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
        return TriMesh(np.vstack(verts), np.vstack(faces))

    def xz_bounds(self) -> tuple[float, float, float, float]:
        """(xmin, zmin, xmax, zmax) of the vertices."""
        v = self.vertices
        return (
            float(v[:, 0].min()),
            float(v[:, 2].min()),
            float(v[:, 0].max()),
            float(v[:, 2].max()),
        )

    def intersect(
        self,
        origins: FloatArray,
        dirs: FloatArray,
        t_min: float = 1e-9,
        t_max: float | FloatArray = np.inf,
    ) -> tuple[FloatArray, np.ndarray]:
        """Nearest hit per ray (Möller–Trumbore, two-sided).

        Returns ``(t, face)`` where ``origin + t * dir`` is the hit; ``t`` is ``inf`` and
        ``face`` is -1 for rays that miss. ``dirs`` need not be unit length; ``t`` is in units
        of ``dirs``. ``t_max`` may be a scalar or one value per ray.
        """
        o = np.asarray(origins, dtype=np.float64).reshape(-1, 3)
        d = np.asarray(dirs, dtype=np.float64).reshape(-1, 3)
        n = len(o)
        t_out = np.full(n, np.inf)
        f_out = np.full(n, -1, dtype=np.int64)
        m = self.n_faces
        if n == 0 or m == 0:
            return t_out, f_out
        tmax = np.broadcast_to(np.asarray(t_max, dtype=np.float64), (n,))
        chunk = max(1, _PAIR_BUDGET // m)
        v0, e1, e2 = self._v0[None], self._e1[None], self._e2[None]
        for a in range(0, n, chunk):
            oc = o[a : a + chunk, None, :]
            dc = d[a : a + chunk, None, :]
            p = np.cross(dc, e2)
            det = np.einsum("rmk,rmk->rm", np.broadcast_to(e1, p.shape), p)
            ok = np.abs(det) > _EPS
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            s = oc - v0
            u = np.einsum("rmk,rmk->rm", s, p) * inv
            q = np.cross(s, np.broadcast_to(e1, s.shape))
            v = np.einsum("rmk,rmk->rm", np.broadcast_to(dc, q.shape), q) * inv
            t = np.einsum("rmk,rmk->rm", np.broadcast_to(e2, q.shape), q) * inv
            tm = tmax[a : a + chunk, None]
            valid = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > t_min) & (t < tm)
            t = np.where(valid, t, np.inf)
            idx = np.argmin(t, axis=1)
            best = t[np.arange(len(idx)), idx]
            t_out[a : a + chunk] = best
            f_out[a : a + chunk] = np.where(np.isfinite(best), idx, -1)
        return t_out, f_out


def grid_ground(
    xmin: float,
    zmin: float,
    xmax: float,
    zmax: float,
    height_fn=None,
    step: float = 0.5,
) -> TriMesh:
    """A regular triangulated ground patch; ``height_fn(x, z) -> y`` (default flat at 0)."""
    nx = max(1, round((xmax - xmin) / step))
    nz = max(1, round((zmax - zmin) / step))
    xs = np.linspace(xmin, xmax, nx + 1)
    zs = np.linspace(zmin, zmax, nz + 1)
    gx, gz = np.meshgrid(xs, zs)  # rows along z
    gy = np.zeros_like(gx) if height_fn is None else np.asarray(height_fn(gx, gz), float)
    gy = np.broadcast_to(gy, gx.shape)
    verts = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)
    faces = []
    for i in range(nz):
        for j in range(nx):
            a = i * (nx + 1) + j
            b, c, d = a + 1, a + nx + 1, a + nx + 2
            faces.append((a, c, b))
            faces.append((b, c, d))
    return TriMesh(verts, np.asarray(faces))


def plane_ground(xmin: float, zmin: float, xmax: float, zmax: float, y: float = 0.0) -> TriMesh:
    """Flat ground rectangle at height ``y`` (site-plan fallback, spec 7 ladder level 3)."""
    return grid_ground(
        xmin, zmin, xmax, zmax, lambda x, z: np.full_like(x, y), step=max(xmax - xmin, zmax - zmin)
    )


def box_mesh(lo: Sequence[float], hi: Sequence[float]) -> TriMesh:
    """Closed axis-aligned box from corner ``lo`` to ``hi`` (x, y, z), 12 triangles."""
    x0, y0, z0 = (float(c) for c in lo)
    x1, y1, z1 = (float(c) for c in hi)
    v = np.array(
        [
            [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
            [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
        ]
    )  # fmt: skip
    f = np.array(
        [
            [0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6], [0, 4, 5], [0, 5, 1],
            [3, 2, 6], [3, 6, 7], [0, 3, 7], [0, 7, 4], [1, 5, 6], [1, 6, 2],
        ]
    )  # fmt: skip
    return TriMesh(v, f)


# ---------------------------------------------------------------------------
# Height grid (spec 7 step 4: 0.1 m)
# ---------------------------------------------------------------------------


@dataclass
class HeightGrid:
    """Ground height on a regular x/z grid; NaN where the ground mesh has no surface."""

    x0: float
    z0: float
    res: float
    heights: FloatArray
    """Shape (rows along z, cols along x); node (i, j) is at (x0 + j*res, z0 + i*res)."""

    @classmethod
    def from_mesh(cls, mesh: TriMesh, res: float = 0.1) -> HeightGrid:
        xmin, zmin, xmax, zmax = mesh.xz_bounds()
        x0 = np.floor(xmin / res) * res
        z0 = np.floor(zmin / res) * res
        nx = round((xmax - x0) / res) + 2
        nz = round((zmax - z0) / res) + 2
        h = np.full((nz, nx), np.nan)
        v = mesh.vertices
        for tri in mesh.faces:
            p = v[tri]
            ax, az = p[:, 0], p[:, 2]
            j0 = max(0, int(np.floor((ax.min() - x0) / res)))
            j1 = min(nx - 1, int(np.ceil((ax.max() - x0) / res)))
            i0 = max(0, int(np.floor((az.min() - z0) / res)))
            i1 = min(nz - 1, int(np.ceil((az.max() - z0) / res)))
            if j1 < j0 or i1 < i0:
                continue
            gx, gz = np.meshgrid(x0 + np.arange(j0, j1 + 1) * res, z0 + np.arange(i0, i1 + 1) * res)
            (xa, za), (xb, zb), (xc, zc) = (ax[0], az[0]), (ax[1], az[1]), (ax[2], az[2])
            den = (zb - zc) * (xa - xc) + (xc - xb) * (za - zc)
            if abs(den) < _EPS:
                continue  # vertical triangle: no ground surface
            w1 = ((zb - zc) * (gx - xc) + (xc - xb) * (gz - zc)) / den
            w2 = ((zc - za) * (gx - xc) + (xa - xc) * (gz - zc)) / den
            w3 = 1.0 - w1 - w2
            tol = -1e-9
            inside = (w1 >= tol) & (w2 >= tol) & (w3 >= tol)
            if not inside.any():
                continue
            y = w1 * p[0, 1] + w2 * p[1, 1] + w3 * p[2, 1]
            block = h[i0 : i1 + 1, j0 : j1 + 1]
            cur = np.where(np.isnan(block), -np.inf, block)
            block[inside] = np.maximum(cur[inside], y[inside])
        return cls(float(x0), float(z0), float(res), h)

    def height(self, x: FloatArray, z: FloatArray) -> FloatArray:
        """Bilinear height at (x, z); NaN outside the grid or where the ground is missing."""
        x = np.asarray(x, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)
        fx = (x - self.x0) / self.res
        fz = (z - self.z0) / self.res
        nz, nx = self.heights.shape
        j = np.floor(fx).astype(np.int64)
        i = np.floor(fz).astype(np.int64)
        inside = (j >= 0) & (i >= 0) & (j < nx - 1) & (i < nz - 1)
        jc = np.clip(j, 0, nx - 2)
        ic = np.clip(i, 0, nz - 2)
        tx = fx - jc
        tz = fz - ic
        h = self.heights
        out = (
            h[ic, jc] * (1 - tx) * (1 - tz)
            + h[ic, jc + 1] * tx * (1 - tz)
            + h[ic + 1, jc] * (1 - tx) * tz
            + h[ic + 1, jc + 1] * tx * tz
        )
        return np.where(inside, out, np.nan)


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


@dataclass
class Occluder:
    """A named solid in the scene (house, shed, fence) used for line of sight."""

    name: str
    mesh: TriMesh

    def footprint_xz(self):
        """Convex hull of the occluder's vertices on the ground plane (shapely Polygon)."""
        from shapely.geometry import MultiPoint

        return MultiPoint([(float(x), float(z)) for x, _, z in self.mesh.vertices]).convex_hull


@dataclass
class RaycastScene:
    """Ground mesh (ray-cast target) plus occluders, with a lazily built height grid.

    This is the ``SpatialModel`` / ``RaycastScene`` of spec 9.4-9.5. A LiDAR build splits the
    scan into ground and the rest; the site-plan fallback builds it from a flat ground and
    boxes (``plane_ground`` and ``box_mesh``).
    """

    ground: TriMesh
    occluders: list[Occluder] = field(default_factory=list)
    grid_res: float = 0.1
    _grid: HeightGrid | None = field(default=None, init=False, repr=False)
    _occ: TriMesh | None = field(default=None, init=False, repr=False)

    @property
    def height_grid(self) -> HeightGrid:
        if self._grid is None:
            self._grid = HeightGrid.from_mesh(self.ground, self.grid_res)
        return self._grid

    @property
    def occluder_mesh(self) -> TriMesh:
        if self._occ is None:
            self._occ = TriMesh.concat(o.mesh for o in self.occluders)
        return self._occ

    def height_at(self, x: FloatArray, z: FloatArray) -> FloatArray:
        return self.height_grid.height(x, z)

    def cast_ground(
        self, origins: FloatArray, dirs: FloatArray, max_t: float = 200.0
    ) -> tuple[FloatArray, np.ndarray]:
        """Hit points on the ground mesh; ``(points (N, 3), hit (N,))``."""
        o = np.asarray(origins, float).reshape(-1, 3)
        d = np.asarray(dirs, float).reshape(-1, 3)
        t, _ = self.ground.intersect(o, d, t_max=max_t)
        hit = np.isfinite(t)
        pts = o + np.where(hit, t, 0.0)[:, None] * d
        return pts, hit

    def segment_clear(
        self, origins: FloatArray, targets: FloatArray, end_margin_m: float = 0.05
    ) -> np.ndarray:
        """True where the straight segment origin -> target hits no occluder and stays above
        the ground (terrain checked on the height grid every ~0.2 m)."""
        o = np.asarray(origins, float).reshape(-1, 3)
        tg = np.asarray(targets, float).reshape(-1, 3)
        o = np.broadcast_to(o, tg.shape)
        d = tg - o
        length = np.linalg.norm(d, axis=1)
        safe_len = np.maximum(length, _EPS)
        t_end = 1.0 - end_margin_m / safe_len
        t_occ, _ = self.occluder_mesh.intersect(o, d, t_min=1e-6, t_max=t_end)
        clear = ~np.isfinite(t_occ)
        # Terrain occlusion: sample along the segment, skipping the last end_margin metres.
        n_s = int(np.clip(np.ceil(length.max(initial=0.0) / 0.2), 2, 400))
        s = np.linspace(0.0, 1.0, n_s, endpoint=False)[1:]
        pts = o[:, None, :] + s[None, :, None] * d[:, None, :]
        near_end = s[None, :] > (1.0 - (end_margin_m + 0.25) / safe_len)[:, None]
        h = self.height_at(pts[..., 0], pts[..., 2])
        below = (pts[..., 1] < h - 0.02) & ~near_end & np.isfinite(h)
        return clear & ~below.any(axis=1)

    def inside_occluder(self, x: FloatArray, z: FloatArray) -> np.ndarray:
        """True where a vertical ray from above meets an occluder above the ground first."""
        x = np.asarray(x, float).ravel()
        z = np.asarray(z, float).ravel()
        if self.occluder_mesh.n_faces == 0:
            return np.zeros(x.shape, bool)
        g = self.height_at(x, z)
        top = 1000.0
        o = np.stack([x, np.full_like(x, top), z], axis=1)
        d = np.tile([0.0, -1.0, 0.0], (len(x), 1))
        t, _ = self.occluder_mesh.intersect(o, d)
        hit_y = top - t
        return np.isfinite(t) & (hit_y > np.where(np.isfinite(g), g, -np.inf) + 0.01)


SpatialModel = RaycastScene
"""Alias used by the spec 9.5 signature ``coverage(model: SpatialModel, ...)``."""


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------


def look_at_extrinsics(
    position: Sequence[float], target: Sequence[float], up: Sequence[float] = (0.0, 1.0, 0.0)
) -> Extrinsics:
    """World -> camera pose for a camera at ``position`` looking at ``target`` (+Y up)."""
    c = np.asarray(position, float)
    fwd = np.asarray(target, float) - c
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, np.asarray(up, float))
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    r = np.stack([right, down, fwd])
    t = -r @ c
    rvec, _ = cv2.Rodrigues(r)
    return Extrinsics(rvec=[float(v) for v in rvec.ravel()], tvec=[float(v) for v in t])


def pinhole_intrinsics(width: int, height: int, f: float, dist: Sequence[float] = ()) -> Intrinsics:
    k = [[float(f), 0.0, width / 2.0], [0.0, float(f), height / 2.0], [0.0, 0.0, 1.0]]
    return Intrinsics(model="pinhole", k=k, dist=list(dist), width=width, height=height)


@dataclass
class CameraGeom:
    """Projection maths for one calibrated camera."""

    camera_id: str
    k: FloatArray
    dist: FloatArray
    model: str
    width: int
    height: int
    rvec: FloatArray
    tvec: FloatArray
    r: FloatArray
    center: FloatArray
    heldout_ground_m: float
    """Audit-harness ground error in metres, 0.0 when not measured (see ``audit_ground_m``)."""
    audit_ground_m: float | None = None
    """Audit-harness held-out ground error (m) when measured, else None."""
    reproj_mean_px: float | None = None
    """Mean landmark reprojection error (px) of the extrinsic solve."""
    nominal: bool = False
    """True for nominal-FOV intrinsics (``fov_nominal``): no measured lens model."""

    @classmethod
    def from_calibration(cls, cal: Calibration) -> CameraGeom:
        intr, ext = cal.intrinsics, cal.extrinsics
        rvec = np.asarray(ext.rvec, float).reshape(3, 1)
        tvec = np.asarray(ext.tvec, float).reshape(3, 1)
        r, _ = cv2.Rodrigues(rvec)
        center = (-r.T @ tvec).ravel()
        dist = np.asarray(intr.dist, float)
        if intr.model == "fisheye":
            dist = np.pad(dist, (0, max(0, 4 - len(dist))))[:4]
        return cls(
            camera_id=cal.camera_id,
            k=np.asarray(intr.k, float),
            dist=dist,
            model=intr.model,
            width=intr.width,
            height=intr.height,
            rvec=rvec,
            tvec=tvec,
            r=r,
            center=center,
            heldout_ground_m=float(ext.heldout_ground_m or 0.0),
            audit_ground_m=ext.heldout_ground_m,
            reproj_mean_px=ext.reproj_mean_px,
            nominal=intr.source == "fov_nominal" or intr.fov_fallback,
        )

    def project(self, points: FloatArray) -> tuple[FloatArray, np.ndarray]:
        """Pixel coordinates of world points and whether each is in front of the camera."""
        p = np.asarray(points, float).reshape(-1, 3)
        cam = (self.r @ p.T + self.tvec).T
        front = cam[:, 2] > 1e-6
        if len(p) == 0:
            return np.zeros((0, 2)), front
        if self.model == "fisheye":
            uv, _ = cv2.fisheye.projectPoints(
                p.reshape(-1, 1, 3), self.rvec, self.tvec, self.k, self.dist
            )
        else:
            uv, _ = cv2.projectPoints(p, self.rvec, self.tvec, self.k, self.dist)
        return uv.reshape(-1, 2), front

    def undistort(self, uv: FloatArray) -> FloatArray:
        """Pixels -> ideal normalised image coordinates (x/z, y/z)."""
        return undistort_normalized(self.k, self.dist, self.model, uv)

    def pixel_rays(self, uv: FloatArray) -> FloatArray:
        """Unit world-frame ray directions through the given pixels (from ``center``)."""
        n = self.undistort(uv)
        d_cam = np.column_stack([n, np.ones(len(n))])
        d = (self.r.T @ d_cam.T).T
        return d / np.linalg.norm(d, axis=1, keepdims=True)


def undistort_normalized(k: FloatArray, dist: FloatArray, model: str, uv: FloatArray) -> FloatArray:
    pts = np.asarray(uv, float).reshape(-1, 1, 2)
    if len(pts) == 0:
        return np.zeros((0, 2))
    if model == "fisheye":
        d4 = np.pad(np.asarray(dist, float), (0, 4))[:4]
        out = cv2.fisheye.undistortPoints(pts, np.asarray(k, float), d4)
    else:
        d = np.asarray(dist, float)
        if d.size == 0 or not np.any(d):
            kk = np.asarray(k, float)
            out = np.empty_like(pts)
            out[..., 0] = (
                pts[..., 0] - kk[0, 2] - kk[0, 1] * (pts[..., 1] - kk[1, 2]) / kk[1, 1]
            ) / kk[0, 0]
            out[..., 1] = (pts[..., 1] - kk[1, 2]) / kk[1, 1]
        else:
            crit = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 50, 1e-10)
            out = cv2.undistortPoints(pts, np.asarray(k, float), d, criteria=crit)
    return out.reshape(-1, 2)


def rotation_angle_deg(r_a: FloatArray, r_b: FloatArray) -> float:
    """Angle of the relative rotation between two 3x3 rotation matrices, in degrees."""
    rel = np.asarray(r_a) @ np.asarray(r_b).T
    c = np.clip((np.trace(rel) - 1.0) / 2.0, -1.0, 1.0)
    return float(np.degrees(np.arccos(c)))


# ---------------------------------------------------------------------------
# COCO RLE (compressed counts string, column-major, as in pycocotools)
# ---------------------------------------------------------------------------


def rle_encode(mask: np.ndarray) -> str:
    """Binary mask (H, W) -> COCO compressed counts string."""
    flat = np.asarray(mask, dtype=bool).ravel(order="F").astype(np.int8)
    if flat.size == 0:
        return ""
    change = np.flatnonzero(np.diff(flat)) + 1
    bounds = np.concatenate([[0], change, [flat.size]])
    counts = np.diff(bounds).tolist()
    if flat[0]:
        counts = [0, *counts]
    out: list[str] = []
    for i, cnt in enumerate(counts):
        x = int(cnt)
        if i > 2:
            x -= int(counts[i - 2])
        more = True
        while more:
            c = x & 0x1F
            x >>= 5
            more = (x != -1) if (c & 0x10) else (x != 0)
            if more:
                c |= 0x20
            out.append(chr(c + 48))
    return "".join(out)


def _rle_counts(s: str) -> list[int]:
    counts: list[int] = []
    p = 0
    n = len(s)
    while p < n:
        x = 0
        k = 0
        more = True
        while more:
            c = ord(s[p]) - 48
            x |= (c & 0x1F) << (5 * k)
            more = bool(c & 0x20)
            p += 1
            k += 1
            if not more and (c & 0x10):
                x |= -1 << (5 * k)
        if len(counts) > 2:
            x += counts[-2]
        counts.append(x)
    return counts


def rle_decode(rle: str, height: int, width: int) -> np.ndarray:
    """COCO counts string (or a JSON ``{"size": [h, w], "counts": ...}``) -> bool (H, W).

    Raises ``ValueError`` when the counts do not cover exactly ``height * width`` pixels.
    """
    text = rle.strip()
    if text.startswith("{"):
        obj = json.loads(text)
        height, width = (int(v) for v in obj["size"])
        raw = obj["counts"]
        counts = [int(c) for c in raw] if isinstance(raw, list) else _rle_counts(str(raw))
    else:
        counts = _rle_counts(text)
    total = height * width
    if any(c < 0 for c in counts) or sum(counts) != total:
        raise ValueError(f"RLE covers {sum(counts)} pixels, expected {total}")
    values = np.zeros(len(counts), dtype=bool)
    values[1::2] = True
    flat = np.repeat(values, counts)
    return flat.reshape((width, height)).T
