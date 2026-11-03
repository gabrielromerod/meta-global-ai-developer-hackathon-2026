"""Camera topology: transit windows and routes, including routes through blind regions (FR-010).

The config lists directed edges between nodes. A node is a camera id or a blind-region id.
An edge from a camera into a blind region usually names the exit polygon the subject leaves
through and carries no times; the edge out of the region carries the transit window. A
*route* is what visit assembly needs: from one camera to another (possibly the same one),
optionally via a blind region, with one combined min..max window.

Route kinds:
- ``direct``: camera -> camera edge. Missing bounds default to 0..DEFAULT_TRANSIT_MAX_S.
- ``via_region``: camera -> blind region -> camera. Windows add up; a missing bound on the
  entry edge counts as 0 and on the exit edge as 0..DEFAULT_TRANSIT_MAX_S.
- ``reacquire``: the same camera picking the subject up again after a short tracker loss
  (0..REACQUIRE_MAX_S). It is implicit for every camera.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from vigil.models import Config, TopologyEdge

DEFAULT_TRANSIT_MAX_S = 60.0
"""Upper transit bound when an edge has none: the visit-close timeout (spec 5.9)."""
REACQUIRE_MAX_S = 3.0
"""Same-camera re-acquisition after a short tracker loss (not a topology edge)."""

RouteKind = Literal["direct", "via_region", "reacquire"]


class Route(BaseModel):
    """A way a subject can get from one camera's view to another's (module-local model)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_camera: str
    to_camera: str
    exit: str | None = None
    """Exit polygon on `from_camera` this route requires, if any."""
    via_region: str | None = None
    min_s: float
    max_s: float
    blind: bool
    kind: RouteKind
    transit_measured: bool = True

    def fits(self, gap_s: float) -> bool:
        return self.transit_measured and self.min_s <= gap_s <= self.max_s


def edges(cfg: Config) -> list[TopologyEdge]:
    """Topology edges in config order."""
    return list(cfg.topology)


def transit_ok(edge: TopologyEdge, gap_s: float) -> bool:
    """True when a subject could cover this edge in `gap_s` seconds (bounds inclusive)."""
    lo = edge.min_s if edge.min_s is not None else 0.0
    hi = edge.max_s if edge.max_s is not None else DEFAULT_TRANSIT_MAX_S
    return lo <= gap_s <= hi


def _camera_ids(cfg: Config) -> list[str]:
    return [c.id for c in cfg.cameras]


def _region_ids(cfg: Config) -> set[str]:
    return {r.id for r in cfg.blind_regions}


def blind_edges(cfg: Config) -> list[TopologyEdge]:
    """Edges marked blind or touching a blind region."""
    regions = _region_ids(cfg)
    return [e for e in cfg.topology if e.blind or e.from_ in regions or e.to in regions]


def routes(cfg: Config) -> list[Route]:
    """Every camera-to-camera route the config allows, in a deterministic order."""
    cams = set(_camera_ids(cfg))
    regions = _region_ids(cfg)
    out: list[Route] = []
    for e in cfg.topology:
        if e.from_ in cams and e.to in cams:
            out.append(
                Route(
                    from_camera=e.from_,
                    to_camera=e.to,
                    exit=e.exit,
                    min_s=e.min_s if e.min_s is not None else 0.0,
                    max_s=e.max_s if e.max_s is not None else DEFAULT_TRANSIT_MAX_S,
                    blind=e.blind,
                    kind="direct",
                    transit_measured=e.transit_measured,
                )
            )
        elif e.from_ in cams and e.to in regions:
            for e2 in cfg.topology:
                if e2.from_ != e.to or e2.to not in cams:
                    continue
                out.append(
                    Route(
                        from_camera=e.from_,
                        to_camera=e2.to,
                        exit=e.exit,
                        via_region=e.to,
                        min_s=(e.min_s or 0.0) + (e2.min_s or 0.0),
                        max_s=(e.max_s or 0.0)
                        + (e2.max_s if e2.max_s is not None else DEFAULT_TRANSIT_MAX_S),
                        blind=True,
                        kind="via_region",
                        transit_measured=e.transit_measured and e2.transit_measured,
                    )
                )
    for cam in _camera_ids(cfg):
        out.append(_reacquire(cam))
    return out


def _reacquire(camera_id: str) -> Route:
    return Route(
        from_camera=camera_id,
        to_camera=camera_id,
        min_s=0.0,
        max_s=REACQUIRE_MAX_S,
        blind=False,
        kind="reacquire",
    )


def candidate_routes(
    cfg: Config,
    camera_id: str,
    exit_region: str | None = None,
    toward_region: str | None = None,
) -> list[Route]:
    """Routes a track ending on `camera_id` may continue along.

    - `toward_region` (from the last 3D position) keeps only routes through that region.
    - A named exit that some route uses keeps only those routes: leaving through the shed exit
      cannot put someone on the front camera.
    - A named exit no route uses keeps only routes that require no exit.
    - No evidence keeps every route from the camera.
    Same-camera re-acquisition is always possible.
    """
    mine = [r for r in routes(cfg) if r.from_camera == camera_id and r.kind != "reacquire"]
    if toward_region is not None:
        mine = [r for r in mine if r.via_region == toward_region]
    elif exit_region is not None:
        named = [r for r in mine if r.exit == exit_region]
        mine = named or [r for r in mine if r.exit is None]
    return [*mine, _reacquire(camera_id)]


def exit_leads_to_blind(cfg: Config, camera_id: str, exit_region: str | None) -> str | None:
    """The blind region an exit polygon leads into, if the topology says so."""
    if exit_region is None:
        return None
    regions = _region_ids(cfg)
    for e in cfg.topology:
        if e.from_ == camera_id and e.exit == exit_region and e.to in regions:
            return e.to
    return None
