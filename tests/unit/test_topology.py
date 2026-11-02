"""Topology: edges, transit windows, routes through blind regions (FR-010, spec 9.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from vigil.models import Config, TopologyEdge
from vigil.reasoning import clock
from vigil.reasoning.topology import (
    DEFAULT_TRANSIT_MAX_S,
    REACQUIRE_MAX_S,
    blind_edges,
    candidate_routes,
    edges,
    exit_leads_to_blind,
    routes,
    transit_ok,
)


def test_edges_load_from_sample_config(sample_config: Config) -> None:
    es = edges(sample_config)
    assert len(es) == 10
    assert any(e.from_ == "side_left" and e.to == "shed_back" and e.blind for e in es)


def test_transit_ok_inclusive_bounds() -> None:
    e = TopologyEdge.model_validate({"from": "front", "to": "side_left", "min_s": 2, "max_s": 20})
    assert not transit_ok(e, 1.99)
    assert transit_ok(e, 2.0)
    assert transit_ok(e, 20.0)
    assert not transit_ok(e, 20.01)
    assert not transit_ok(e, -1.0)


def test_transit_ok_defaults_when_bounds_missing() -> None:
    e = TopologyEdge.model_validate({"from": "a", "to": "b"})
    assert transit_ok(e, 0.0)
    assert transit_ok(e, DEFAULT_TRANSIT_MAX_S)
    assert not transit_ok(e, DEFAULT_TRANSIT_MAX_S + 0.1)


def test_route_through_blind_region_composes_edges(sample_config: Config) -> None:
    rs = candidate_routes(sample_config, "side_left", exit_region="to_shed_back")
    via = [r for r in rs if r.kind == "via_region"]
    assert len(via) == 1
    r = via[0]
    assert (r.from_camera, r.to_camera, r.via_region, r.blind) == (
        "side_left",
        "side_left",
        "shed_back",
        True,
    )
    assert (r.min_s, r.max_s) == (5.0, 180.0)
    assert r.fits(41.0)
    assert not r.fits(4.0)
    assert not r.fits(181.0)
    # A named exit restricts routes to the ones that use it (plus same-camera re-acquire).
    assert {x.kind for x in rs} == {"via_region", "reacquire"}


def test_candidate_routes_without_exit_include_all_directions(sample_config: Config) -> None:
    rs = candidate_routes(sample_config, "front")
    direct = {(r.to_camera, r.min_s, r.max_s) for r in rs if r.kind == "direct"}
    assert direct == {("side_left", 2.0, 20.0), ("side_right", 2.0, 20.0)}
    reacq = [r for r in rs if r.kind == "reacquire"]
    assert len(reacq) == 1
    assert reacq[0].to_camera == "front"
    assert reacq[0].max_s == REACQUIRE_MAX_S


def test_candidate_routes_toward_region(sample_config: Config) -> None:
    rs = candidate_routes(sample_config, "side_left", toward_region="shed_back")
    assert {r.kind for r in rs} == {"via_region", "reacquire"}


def test_unknown_exit_falls_back_to_unnamed_edges(sample_config: Config) -> None:
    rs = candidate_routes(sample_config, "side_left", exit_region="nowhere")
    assert {r.to_camera for r in rs if r.kind == "direct"} == {"front", "backyard"}
    assert not any(r.kind == "via_region" for r in rs)


def test_unknown_camera_has_no_routes_but_reacquire(sample_config: Config) -> None:
    rs = candidate_routes(sample_config, "garage")
    assert [r.kind for r in rs] == ["reacquire"]


def test_blind_edges_and_exit_lookup(sample_config: Config) -> None:
    be = blind_edges(sample_config)
    assert len(be) == 2
    assert all(e.blind for e in be)
    assert exit_leads_to_blind(sample_config, "side_left", "to_shed_back") == "shed_back"
    assert exit_leads_to_blind(sample_config, "front", "to_side_left") is None


def test_routes_are_deterministic(sample_config: Config) -> None:
    assert routes(sample_config) == routes(sample_config)


def test_clock_falls_back_to_session_offset_without_tzdata() -> None:
    pst = timezone(timedelta(hours=-8))
    start = datetime(2026, 11, 3, 0, 0, tzinfo=pst)
    local = clock.to_local(start, 22 * 3600 + 14 * 60, "America/Los_Angeles")
    assert (local.hour, local.minute) == (22, 14)
    assert clock.resolve_tz("UTC") is UTC


def test_clock_rejects_naive_session_start() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.to_local(datetime(2026, 11, 3), 0.0, "America/Los_Angeles")
