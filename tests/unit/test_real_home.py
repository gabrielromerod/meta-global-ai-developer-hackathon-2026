"""FR-001/010/032: the real inventory and property noise boundary, offline inputs."""

from pathlib import Path

from vigil.ingest.config import load_config
from vigil.models import Box, Track, TrackFrame
from vigil.reasoning.topology import routes

ROOT = Path(__file__).resolve().parents[2]
IDS = {
    "front_left_duo",
    "front_right_duo",
    "doorbell",
    "porch",
    "side_left",
    "backyard_1",
    "backyard_2",
}


def test_real_home_seven_wifi_cameras_and_no_right_route():
    cfg = load_config(ROOT / "config/cameras.yaml")
    assert {c.id for c in cfg.cameras} == IDS
    assert all(c.source.channel is None for c in cfg.cameras)
    assert {c.id for c in cfg.cameras if c.power_profile == "battery_wifi"} == {
        "side_left",
        "backyard_1",
        "backyard_2",
    }
    assert all(not c.privacy_reviewed for c in cfg.cameras)
    assert all(not edge.transit_measured for edge in cfg.topology)
    assert all(not r.fits(5) for r in routes(cfg) if r.from_camera != r.to_camera)
    assert not any("right" in region.id for region in cfg.blind_regions)
    assert {c.id for c in cfg.cameras if any(c.zone_kind(z) == "egress" for z in c.zones)} == {
        "doorbell"
    }
    assert all(
        "side_left" in (e.from_, e.to)
        for e in cfg.topology
        if any(x.startswith("backyard") for x in (e.from_, e.to))
    )


def test_outer_ring_never_becomes_a_visit_or_rule_event():
    from vigil.perception.noise import property_evidence

    cfg = load_config(ROOT / "config/cameras.yaml")
    camera = cfg.camera("front_left_duo")
    outer = camera.zones["left_street"]
    inner = camera.zones["left_garden"]

    def point(poly):
        return sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)

    def frame(t, poly):
        x, y = point(poly)
        return TrackFrame(t=t, box=Box(x1=x - 10, y1=y - 40, x2=x + 10, y2=y))

    street = Track(
        id="passing",
        camera_id=camera.id,
        cls="person",
        t_first=0,
        t_last=1,
        frames=[frame(0, outer), frame(1, outer)],
    )
    entering = street.model_copy(
        update={"id": "arriving", "t_last": 2, "frames": [frame(0, outer), frame(2, inner)]}
    )
    kept, events, counts = property_evidence([street, entering], [], cfg)
    assert [t.id for t in kept] == ["arriving"]
    assert kept[0].t_first == 2
    assert len(kept[0].frames) == 1
    assert not events
    assert counts["street_tracks"] == 1


def test_outer_ring_pipeline_counts_sensor_event_never_escalates():
    from datetime import UTC, datetime

    from vigil.models import CameraAiEvent, Rule, RuleTarget, SamFrame, SamObject, Window
    from vigil.pipeline import run_scenario

    cfg = load_config(ROOT / "config/cameras.yaml")
    camera = cfg.camera("front_left_duo")
    frames = [
        SamFrame(frame=i, t=2 + i / 10, box=Box(x1=950, y1=280, x2=970, y2=320)) for i in range(4)
    ]
    obj = SamObject(
        window_id="w",
        camera_id=camera.id,
        phrase="person",
        obj_id=1,
        frames=frames,
        width=1920,
        height=720,
    )
    result = run_scenario(
        {
            "windows": [Window(id="w", camera_id=camera.id, t0=0, t1=4)],
            "camera_ai_events": [
                CameraAiEvent(id="sensor", camera_id=camera.id, kind="person", t0=2, t1=2.3)
            ],
            "camera_ai_events_measured": True,
        },
        cfg=cfg,
        rules=[
            Rule(
                id="outer",
                name="Test rule cannot override boundary",
                target=RuleTarget(kind="zone", id="left_street"),
                trigger="enter",
                severity="needs_attention",
            )
        ],
        protected=[],
        watches=[],
        session_start=datetime(2026, 11, 3, tzinfo=UTC),
        sam=lambda w, p: [obj] if p == "person" else [],
    )
    assert result["visits"] == []
    assert result["events"] == []
    assert result["prefilter_counts"]["camera_events"] == 1
    assert result["prefilter_counts"]["street_events"] == 1
    assert result["prefilter_counts"]["on_property"] == 0


def test_default_backyard_rule_covers_both_real_camera_lawns():
    from vigil.reasoning.rules import load_rules, rules_for_config

    cfg = load_config(ROOT / "config/cameras.yaml")
    rules = rules_for_config(load_rules(), cfg)
    targets = {r.target.id for r in rules if r.id.startswith("r_backyard_night")}
    assert targets == {"backyard_1_lawn", "backyard_2_lawn"}
