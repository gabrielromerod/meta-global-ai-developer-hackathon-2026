"""Load and validate ``config/cameras.yaml`` with named errors (FR-001, spec 9.4, UC-01).

Every problem raises a subclass of :class:`ConfigError` (itself a ``ValueError``) that names
the offending reference (``err.ref``) and, when the config came from a file, the 1-based
YAML line (``err.line``), so "an edge names an unknown camera" reports the line (UC-01).

Checks on top of the pydantic contract (``vigil.models.Config``):

- camera ids unique; blind-region ids unique and never equal to a camera id;
- zone and line names unique across all cameras (rule targets name them without a camera);
- polygons (zones, exits, privacy, blind regions) have at least 3 points and non-zero area;
  lines have exactly 2 points; pixel coordinates lie inside the camera frame;
- topology edges name known cameras or blind regions (:class:`UnknownCameraError`), any
  ``exit`` exists on the ``from`` camera (:class:`UnknownExitError`), no self loops,
  ``0 <= min_s <= max_s``, an edge touching a blind region has ``blind: true``, no duplicates.

Privacy polygons come from the camera's ``privacy`` list plus an optional
``config/privacy/<camera_id>.json`` (spec 9.1) of the form
``{"camera_id": "front", "width": 1280, "height": 720, "polygons": [[[x, y], ...], ...]}``;
``width``/``height`` give the frame the JSON points are drawn in (defaults to the camera's
frame) and are rescaled to the camera frame.
"""

from __future__ import annotations

import json
import zoneinfo
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from vigil.models import CameraCfg, Config, Point, Polygon

__all__ = [
    "ConfigError",
    "ConfigFileError",
    "ConfigSchemaError",
    "DuplicateIdError",
    "GeometryError",
    "TopologyError",
    "UnknownCameraError",
    "UnknownExitError",
    "UnknownZoneError",
    "find_geometry",
    "load_config",
    "privacy_polygons",
    "validate_config",
]

Loc = tuple[str | int, ...]


# ---------------------------------------------------------------------------
# Named errors
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """Base class: a config problem, with the offending reference and YAML line if known."""

    def __init__(
        self,
        message: str,
        *,
        ref: str | None = None,
        loc: Loc = (),
        line: int | None = None,
        file: Path | str | None = None,
    ) -> None:
        self.message = message
        self.ref = ref
        self.loc = loc
        self.line = line
        self.file = str(file) if file is not None else None
        super().__init__(self._render())

    def _render(self) -> str:
        where = ""
        if self.file is not None:
            where = f"{self.file}:{self.line}: " if self.line else f"{self.file}: "
        elif self.line:
            where = f"line {self.line}: "
        path = "/".join(str(p) for p in self.loc)
        return f"{where}{self.message}" + (f" (at {path})" if path else "")

    def locate(self, lines: dict[Loc, int] | None, file: Path | str | None) -> ConfigError:
        """Attach file and line information found from ``loc`` and re-render the message."""
        if lines is not None and self.line is None:
            self.line = _line_for(lines, self.loc)
        if file is not None and self.file is None:
            self.file = str(file)
        self.args = (self._render(),)
        return self


class ConfigFileError(ConfigError):
    """The file is missing, unreadable, not YAML, or not a mapping at the top level."""


class ConfigSchemaError(ConfigError):
    """The YAML does not match the ``vigil.models.Config`` contract (types, unknown keys)."""


class DuplicateIdError(ConfigError):
    """Two cameras, blind regions, zones/lines, edges or YAML keys share an id."""


class GeometryError(ConfigError):
    """A polygon has fewer than 3 points or no area, a line is not 2 points, or a point is
    outside the camera frame."""


class TopologyError(ConfigError):
    """A topology edge is inconsistent (self loop, bad transit times, blind flag)."""


class UnknownCameraError(ConfigError):
    """A reference names a camera (or blind region, for topology) that does not exist."""


class UnknownZoneError(ConfigError):
    """A reference names a zone, line or exit that does not exist."""


class UnknownExitError(UnknownZoneError):
    """A topology edge names an exit the ``from`` camera does not define."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_config(path: Path | str) -> Config:
    """Read ``cameras.yaml`` into a validated :class:`vigil.models.Config`.

    Raises a :class:`ConfigError` subclass naming the bad reference and its YAML line.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigFileError(f"config file not found: {path}", file=path) from None
    except OSError as exc:
        raise ConfigFileError(f"cannot read config: {exc}", file=path) from exc

    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        raw = yaml.safe_load(text)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark is not None else None
        raise ConfigFileError(f"invalid YAML: {exc.problem or exc}", line=line, file=path) from exc
    except yaml.YAMLError as exc:
        raise ConfigFileError(f"invalid YAML: {exc}", file=path) from exc

    if not isinstance(raw, dict):
        raise ConfigFileError("top level must be a mapping with a 'cameras' key", file=path)

    lines: dict[Loc, int] = {}
    if node is not None:
        _index_lines(node, (), lines, path)

    try:
        cfg = Config.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = tuple(first["loc"])
        msgs = "; ".join(
            f"{'/'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        ref = str(loc[-1]) if loc else None
        raise ConfigSchemaError(f"schema error: {msgs}", ref=ref, loc=loc).locate(
            lines, path
        ) from exc

    return validate_config(cfg, lines=lines, file=path)


def validate_config(
    cfg: Config, *, lines: dict[Loc, int] | None = None, file: Path | str | None = None
) -> Config:
    """Run the FR-001 reference and geometry checks on an already-parsed config.

    Returns ``cfg`` unchanged so it can be chained; raises a :class:`ConfigError` subclass.
    """
    try:
        _check(cfg)
    except ConfigError as err:
        raise err.locate(lines, file) from None
    return cfg


# ---------------------------------------------------------------------------
# Lookups used by other modules
# ---------------------------------------------------------------------------

GeometryKind = Literal["zone", "line", "exit"]
_KIND_FIELD = {"zone": "zones", "line": "lines", "exit": "exits"}


def find_geometry(
    cfg: Config, kind: GeometryKind, name: str, camera_id: str | None = None
) -> tuple[CameraCfg, list[Point]]:
    """Return ``(camera, points)`` for a named zone, line or exit.

    Zone and line names are unique across cameras (enforced by the loader); exits are per
    camera, so pass ``camera_id`` for them. Raises :class:`UnknownZoneError`
    (:class:`UnknownExitError` for exits) or :class:`UnknownCameraError`.
    """
    field = _KIND_FIELD[kind]
    cams = cfg.cameras
    if camera_id is not None:
        cams = [_camera(cfg, camera_id)]
    for cam in cams:
        shapes: dict[str, list[Point]] = getattr(cam, field)
        if name in shapes:
            return cam, list(shapes[name])
    err = UnknownExitError if kind == "exit" else UnknownZoneError
    scope = f" on camera {camera_id!r}" if camera_id else ""
    raise err(f"unknown {kind} {name!r}{scope}", ref=name)


def privacy_polygons(
    cfg: Config, camera_id: str, privacy_dir: Path | str | None = None
) -> list[Polygon]:
    """All privacy polygons for a camera, in that camera's pixel frame (width x height).

    Merges ``CameraCfg.privacy`` with ``<privacy_dir>/<camera_id>.json`` when that file
    exists (default directory: ``config/privacy`` next to the configured cameras.yaml).
    """
    cam = _camera(cfg, camera_id)
    polys: list[Polygon] = [list(p) for p in cam.privacy]
    if privacy_dir is None:
        from vigil.settings import get_settings

        privacy_dir = get_settings().config_path.parent / "privacy"
    jpath = Path(privacy_dir) / f"{camera_id}.json"
    if jpath.exists():
        polys.extend(_load_privacy_json(jpath, cam))
    return polys


def _load_privacy_json(path: Path, cam: CameraCfg) -> list[Polygon]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigFileError(f"cannot read privacy file: {exc}", file=path) from exc
    if not isinstance(data, dict) or not isinstance(data.get("polygons"), list):
        raise ConfigFileError("privacy file needs a 'polygons' list", file=path)
    if data.get("camera_id", cam.id) != cam.id:
        raise ConfigFileError(
            f"privacy file names camera {data['camera_id']!r}, expected {cam.id!r}",
            ref=str(data["camera_id"]),
            file=path,
        )
    sx = cam.width / float(data.get("width", cam.width))
    sy = cam.height / float(data.get("height", cam.height))
    out: list[Polygon] = []
    for i, poly in enumerate(data["polygons"]):
        try:
            pts = [(float(x) * sx, float(y) * sy) for x, y in poly]
        except (TypeError, ValueError) as exc:
            raise GeometryError(
                f"privacy polygon {i} is not a list of [x, y] points", loc=("polygons", i)
            ).locate(None, path) from exc
        try:
            _check_polygon(pts, ("polygons", i), f"privacy polygon {i}", cam)
        except ConfigError as err:
            raise err.locate(None, path) from None
        out.append(pts)
    return out


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _camera(cfg: Config, camera_id: str) -> CameraCfg:
    try:
        return cfg.camera(camera_id)
    except KeyError:
        raise UnknownCameraError(f"unknown camera {camera_id!r}", ref=camera_id) from None


def _check(cfg: Config) -> None:
    _check_timezone(cfg.timezone)

    cam_ids: dict[str, int] = {}
    for i, cam in enumerate(cfg.cameras):
        if cam.id in cam_ids:
            raise DuplicateIdError(
                f"duplicate camera id {cam.id!r}", ref=cam.id, loc=("cameras", i, "id")
            )
        cam_ids[cam.id] = i
    if not cam_ids:
        raise ConfigSchemaError("at least one camera is required", loc=("cameras",))

    region_ids: dict[str, int] = {}
    for i, reg in enumerate(cfg.blind_regions):
        loc: Loc = ("blind_regions", i, "id")
        if reg.id in cam_ids:
            raise DuplicateIdError(
                f"blind region id {reg.id!r} is already a camera id", ref=reg.id, loc=loc
            )
        if reg.id in region_ids:
            raise DuplicateIdError(f"duplicate blind region id {reg.id!r}", ref=reg.id, loc=loc)
        region_ids[reg.id] = i
        _check_polygon(reg.polygon_m, ("blind_regions", i, "polygon_m"), reg.id, None)

    named: dict[str, str] = {}
    for i, cam in enumerate(cfg.cameras):
        base: Loc = ("cameras", i)
        for name, poly in cam.zones.items():
            _check_polygon(poly, (*base, "zones", name), f"zone {name!r}", cam)
        for name, line in cam.lines.items():
            _check_line(line, (*base, "lines", name), f"line {name!r}", cam)
        for name, poly in cam.exits.items():
            _check_polygon(poly, (*base, "exits", name), f"exit {name!r}", cam)
        for j, poly in enumerate(cam.privacy):
            _check_polygon(poly, (*base, "privacy", j), f"privacy polygon {j}", cam)
        for kind, names in (("zones", cam.zones), ("lines", cam.lines)):
            for name in names:
                if name in named:
                    raise DuplicateIdError(
                        f"zone/line name {name!r} on camera {cam.id!r} is already used on "
                        f"camera {named[name]!r}; rule targets need unique names",
                        ref=name,
                        loc=(*base, kind, name),
                    )
                named[name] = cam.id
        if cam.motion_threshold is not None and not 0.0 <= cam.motion_threshold <= 1.0:
            raise ConfigSchemaError(
                f"motion_threshold for {cam.id!r} must be a fraction in [0, 1]",
                ref=cam.id,
                loc=(*base, "motion_threshold"),
            )

    seen_edges: dict[tuple[str, str, str | None], int] = {}
    for i, edge in enumerate(cfg.topology):
        base = ("topology", i)
        for end, field in ((edge.from_, "from"), (edge.to, "to")):
            if end not in cam_ids and end not in region_ids:
                raise UnknownCameraError(
                    f"topology edge {i} names unknown camera or blind region {end!r}",
                    ref=end,
                    loc=(*base, field),
                )
        if edge.from_ == edge.to:
            raise TopologyError(
                f"topology edge {i} goes from {edge.from_!r} to itself",
                ref=edge.from_,
                loc=(*base, "to"),
            )
        if edge.exit is not None:
            if edge.from_ not in cam_ids:
                raise UnknownExitError(
                    f"topology edge {i}: exit {edge.exit!r} on blind region {edge.from_!r} "
                    "(only cameras have exits)",
                    ref=edge.exit,
                    loc=(*base, "exit"),
                )
            if edge.exit not in cfg.cameras[cam_ids[edge.from_]].exits:
                raise UnknownExitError(
                    f"topology edge {i}: camera {edge.from_!r} has no exit {edge.exit!r}",
                    ref=edge.exit,
                    loc=(*base, "exit"),
                )
        for val, field in ((edge.min_s, "min_s"), (edge.max_s, "max_s")):
            if val is not None and val < 0:
                raise TopologyError(
                    f"topology edge {i}: {field} must be >= 0", ref=field, loc=(*base, field)
                )
        if edge.min_s is not None and edge.max_s is not None and edge.min_s > edge.max_s:
            raise TopologyError(
                f"topology edge {i}: min_s {edge.min_s} is above max_s {edge.max_s}",
                ref="min_s",
                loc=(*base, "min_s"),
            )
        touches_blind = edge.from_ in region_ids or edge.to in region_ids
        if touches_blind and not edge.blind:
            raise TopologyError(
                f"topology edge {i} touches a blind region and must set blind: true",
                ref=edge.to if edge.to in region_ids else edge.from_,
                loc=(*base, "blind"),
            )
        key = (edge.from_, edge.to, edge.exit)
        if key in seen_edges:
            raise DuplicateIdError(
                f"topology edge {i} repeats edge {seen_edges[key]} ({edge.from_} -> {edge.to})",
                ref=f"{edge.from_}->{edge.to}",
                loc=base,
            )
        seen_edges[key] = i


def _check_timezone(tz: str) -> None:
    try:
        zoneinfo.ZoneInfo(tz)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        # Windows without the tzdata package has no zone database: skip rather than fail.
        if zoneinfo.available_timezones():
            raise ConfigSchemaError(f"unknown timezone {tz!r}", ref=tz, loc=("timezone",)) from exc


def _area(points: Sequence[Point]) -> float:
    s = 0.0
    n = len(points)
    for k in range(n):
        x1, y1 = points[k]
        x2, y2 = points[(k + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _check_bounds(points: Sequence[Point], loc: Loc, what: str, cam: CameraCfg | None) -> None:
    if cam is None:
        return
    for x, y in points:
        if not (0 <= x <= cam.width and 0 <= y <= cam.height):
            raise GeometryError(
                f"{what} on camera {cam.id!r}: point ({x}, {y}) is outside the "
                f"{cam.width}x{cam.height} frame",
                ref=what,
                loc=loc,
            )


def _check_polygon(points: Sequence[Point], loc: Loc, what: str, cam: CameraCfg | None) -> None:
    if len(points) < 3:
        raise GeometryError(f"{what} needs at least 3 points, got {len(points)}", ref=what, loc=loc)
    if _area(points) <= 0:
        raise GeometryError(f"{what} has zero area (collinear points)", ref=what, loc=loc)
    _check_bounds(points, loc, what, cam)


def _check_line(points: Sequence[Point], loc: Loc, what: str, cam: CameraCfg) -> None:
    if len(points) != 2:
        raise GeometryError(f"{what} needs exactly 2 points, got {len(points)}", ref=what, loc=loc)
    if tuple(points[0]) == tuple(points[1]):
        raise GeometryError(f"{what} has two identical points", ref=what, loc=loc)
    _check_bounds(points, loc, what, cam)


# ---------------------------------------------------------------------------
# YAML line index
# ---------------------------------------------------------------------------


def _index_lines(node: yaml.Node, path: Loc, out: dict[Loc, int], file: Path) -> None:
    out[path] = node.start_mark.line + 1
    if isinstance(node, yaml.MappingNode):
        keys: dict[Any, int] = {}
        for key_node, value_node in node.value:
            key = key_node.value
            line = key_node.start_mark.line + 1
            if key in keys:
                raise DuplicateIdError(
                    f"duplicate key {key!r} (first at line {keys[key]})",
                    ref=str(key),
                    loc=(*path, key),
                    line=line,
                    file=file,
                )
            keys[key] = line
            _index_lines(value_node, (*path, key), out, file)
    elif isinstance(node, yaml.SequenceNode):
        for i, item in enumerate(node.value):
            _index_lines(item, (*path, i), out, file)


def _line_for(lines: dict[Loc, int], loc: Loc) -> int | None:
    for k in range(len(loc), -1, -1):
        hit = lines.get(tuple(loc[:k]))
        if hit is not None:
            return hit
    return None
