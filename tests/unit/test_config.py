"""FR-001: cameras.yaml loader rejects bad references with named errors (spec 9.4, UC-01).

Also the Nov 2 zone kinds (FR-008: egress, perimeter, interior_yard) and hfov_deg (FR-036).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from vigil.ingest.config import (
    ConfigError,
    ConfigFileError,
    ConfigSchemaError,
    DuplicateIdError,
    GeometryError,
    TopologyError,
    UnknownCameraError,
    UnknownExitError,
    UnknownZoneError,
    ZoneKindError,
    find_geometry,
    load_config,
    privacy_polygons,
    validate_config,
)
from vigil.models import Config

REPO_ROOT = Path(__file__).resolve().parents[2]

BASE = """\
timezone: America/Los_Angeles
cameras:
  - id: front
    name: Front entrance
    zones:
      porch: [[420, 380], [860, 380], [860, 720], [420, 720]]
    privacy:
      - [[0, 0], [1280, 0], [1280, 140], [0, 140]]
    exits:
      to_side_left: [[1180, 260], [1280, 260], [1280, 720], [1180, 720]]
  - id: side_left
    name: Left side
    lines:
      side_gate: [[812, 410], [870, 655]]
    exits:
      to_shed_back: [[1100, 380], [1280, 380], [1280, 720], [1100, 720]]
blind_regions:
  - {id: shed_back, name: behind the shed, polygon_m: [[4.1, 9.0], [7.3, 9.0], [7.3, 11.2]]}
topology:
  - {from: side_left, exit: to_shed_back, to: shed_back, blind: true}
  - {from: shed_back, to: side_left, min_s: 5, max_s: 180, blind: true}
  - {from: front, exit: to_side_left, to: side_left, min_s: 2, max_s: 20}
"""


def write(tmp_path: Path, text: str, name: str = "cameras.yaml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_sample_config_loads(sample_config: Config) -> None:
    cfg = load_config(REPO_ROOT / "tests" / "fixtures" / "config" / "synthetic-cameras.yaml")
    assert cfg == sample_config
    assert [c.id for c in cfg.cameras] == ["front", "side_left", "side_right", "backyard"]
    assert cfg.blind_regions[0].id == "shed_back"


def test_base_fixture_loads(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, BASE))
    assert cfg.camera("side_left").lines["side_gate"] == [(812, 410), (870, 655)]
    assert cfg.topology[0].from_ == "side_left"


def test_unknown_camera_in_topology_names_the_reference_and_line(tmp_path: Path) -> None:
    text = BASE.replace("{from: front, exit: to_side_left", "{from: frnt, exit: to_side_left")
    with pytest.raises(UnknownCameraError) as ei:
        load_config(write(tmp_path, text))
    err = ei.value
    assert err.ref == "frnt"
    assert err.line == 22  # the offending topology line (1-based)
    assert "frnt" in str(err)
    assert "cameras.yaml:22" in str(err)
    assert isinstance(err, ConfigError)
    assert isinstance(err, ValueError)


def test_unknown_topology_target(tmp_path: Path) -> None:
    text = BASE.replace("to: shed_back, blind: true}", "to: shed_front, blind: true}")
    with pytest.raises(UnknownCameraError, match="shed_front"):
        load_config(write(tmp_path, text))


def test_unknown_exit(tmp_path: Path) -> None:
    text = BASE.replace("exit: to_shed_back, to: shed_back", "exit: to_garden, to: shed_back")
    with pytest.raises(UnknownExitError) as ei:
        load_config(write(tmp_path, text))
    assert ei.value.ref == "to_garden"
    assert isinstance(ei.value, UnknownZoneError)


def test_exit_on_a_blind_region_is_unknown(tmp_path: Path) -> None:
    text = BASE.replace(
        "{from: shed_back, to: side_left,", "{from: shed_back, exit: x, to: side_left,"
    )
    with pytest.raises(UnknownExitError):
        load_config(write(tmp_path, text))


def test_duplicate_camera_id(tmp_path: Path) -> None:
    text = BASE.replace("id: side_left\n    name: Left side", "id: front\n    name: Left side")
    with pytest.raises(DuplicateIdError, match="front"):
        load_config(write(tmp_path, text))


def test_blind_region_id_cannot_shadow_camera(tmp_path: Path) -> None:
    text = BASE.replace("{id: shed_back, name", "{id: front, name")
    with pytest.raises(DuplicateIdError):
        load_config(write(tmp_path, text))


def test_zone_and_line_names_are_unique_across_cameras(tmp_path: Path) -> None:
    text = BASE.replace("side_gate: [[812", "porch: [[812")
    with pytest.raises(DuplicateIdError, match="porch"):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "porch: [[420, 380], [860, 380], [860, 720], [420, 720]]",
            "porch: [[420, 380], [860, 380]]",
        ),
        ("- [[0, 0], [1280, 0], [1280, 140], [0, 140]]", "- [[0, 0], [1280, 0]]"),
        ("polygon_m: [[4.1, 9.0], [7.3, 9.0], [7.3, 11.2]]", "polygon_m: [[4.1, 9.0], [7.3, 9.0]]"),
        (
            "to_side_left: [[1180, 260], [1280, 260], [1280, 720], [1180, 720]]",
            "to_side_left: [[1180, 260]]",
        ),
    ],
)
def test_polygons_need_three_points(tmp_path: Path, old: str, new: str) -> None:
    assert old in BASE
    with pytest.raises(GeometryError, match="at least 3"):
        load_config(write(tmp_path, BASE.replace(old, new)))


@pytest.mark.parametrize("line", ["[[812, 410]]", "[[812, 410], [870, 655], [900, 700]]"])
def test_lines_need_exactly_two_points(tmp_path: Path, line: str) -> None:
    text = BASE.replace("side_gate: [[812, 410], [870, 655]]", f"side_gate: {line}")
    with pytest.raises(GeometryError, match="exactly 2"):
        load_config(write(tmp_path, text))


def test_degenerate_polygon_rejected(tmp_path: Path) -> None:
    text = BASE.replace(
        "porch: [[420, 380], [860, 380], [860, 720], [420, 720]]",
        "porch: [[0, 0], [10, 10], [20, 20]]",
    )
    with pytest.raises(GeometryError, match="zero area"):
        load_config(write(tmp_path, text))


def test_pixel_outside_frame_rejected(tmp_path: Path) -> None:
    text = BASE.replace(
        "[[0, 0], [1280, 0], [1280, 140], [0, 140]]", "[[0, 0], [1500, 0], [1280, 140]]"
    )
    with pytest.raises(GeometryError, match="outside"):
        load_config(write(tmp_path, text))


def test_transit_min_above_max_rejected(tmp_path: Path) -> None:
    text = BASE.replace("min_s: 2, max_s: 20", "min_s: 30, max_s: 20")
    with pytest.raises(TopologyError, match="min_s"):
        load_config(write(tmp_path, text))


def test_negative_min_marks_overlapping_camera_views(tmp_path: Path) -> None:
    text = BASE.replace("min_s: 2, max_s: 20", "min_s: -60, max_s: 10")
    cfg = load_config(write(tmp_path, text))
    assert cfg.topology[-1].min_s == -60


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("min_s: 5, max_s: 180, blind: true", "min_s: -5, max_s: 180, blind: true"),
        ("min_s: 2, max_s: 20", "min_s: -60, max_s: -1"),
    ],
)
def test_overlap_only_on_open_camera_edges(tmp_path: Path, old: str, new: str) -> None:
    with pytest.raises(TopologyError, match=">= 0"):
        load_config(write(tmp_path, BASE.replace(old, new)))


def test_edge_touching_blind_region_must_be_blind(tmp_path: Path) -> None:
    text = BASE.replace("to: shed_back, blind: true}", "to: shed_back, blind: false}")
    with pytest.raises(TopologyError, match="blind"):
        load_config(write(tmp_path, text))


def test_self_loop_rejected(tmp_path: Path) -> None:
    text = BASE.replace(
        "{from: front, exit: to_side_left, to: side_left", "{from: front, to: front"
    )
    with pytest.raises(TopologyError):
        load_config(write(tmp_path, text))


def test_unknown_field_is_a_schema_error_with_line(tmp_path: Path) -> None:
    text = BASE.replace("    name: Left side\n", "    name: Left side\n    colour: red\n")
    with pytest.raises(ConfigSchemaError) as ei:
        load_config(write(tmp_path, text))
    assert ei.value.line == 13
    assert "colour" in str(ei.value)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_yaml_syntax_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileError) as ei:
        load_config(write(tmp_path, "cameras: [\n  - {id: a\n"))
    assert ei.value.line is not None


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileError, match="mapping"):
        load_config(write(tmp_path, "- 1\n- 2\n"))


def test_validate_config_works_on_models(sample_config: Config) -> None:
    assert validate_config(sample_config) is sample_config
    raw = sample_config.model_dump(by_alias=True)
    raw["topology"].append({"from": "garage", "to": "front"})
    with pytest.raises(UnknownCameraError, match="garage"):
        validate_config(Config.model_validate(raw))


def test_find_geometry(sample_config: Config) -> None:
    cam, poly = find_geometry(sample_config, "zone", "porch")
    assert cam.id == "front"
    assert len(poly) == 4
    cam, line = find_geometry(sample_config, "line", "side_gate")
    assert cam.id == "side_left"
    assert len(line) == 2
    with pytest.raises(UnknownZoneError, match="garden"):
        find_geometry(sample_config, "zone", "garden")


def test_privacy_polygons_merge_yaml_and_json(tmp_path: Path, sample_config: Config) -> None:
    pdir = tmp_path / "privacy"
    pdir.mkdir()
    extra = [[10, 10], [50, 10], [50, 50]]
    (pdir / "front.json").write_text(
        json.dumps({"camera_id": "front", "width": 1280, "height": 720, "polygons": [extra]}),
        encoding="utf-8",
    )
    polys = privacy_polygons(sample_config, "front", pdir)
    assert len(polys) == 2
    assert [tuple(p) for p in polys[1]] == [tuple(p) for p in extra]
    assert privacy_polygons(sample_config, "backyard", pdir) == []
    with pytest.raises(UnknownCameraError):
        privacy_polygons(sample_config, "garage", pdir)


def test_privacy_json_rescaled_to_camera_frame(tmp_path: Path, sample_config: Config) -> None:
    pdir = tmp_path / "privacy"
    pdir.mkdir()
    (pdir / "backyard.json").write_text(
        json.dumps({"width": 640, "height": 360, "polygons": [[[0, 0], [64, 0], [64, 36]]]}),
        encoding="utf-8",
    )
    (poly,) = privacy_polygons(sample_config, "backyard", pdir)
    assert [tuple(p) for p in poly] == [(0, 0), (128, 0), (128, 72)]


def test_privacy_json_bad_polygon(tmp_path: Path, sample_config: Config) -> None:
    pdir = tmp_path / "privacy"
    pdir.mkdir()
    (pdir / "front.json").write_text(json.dumps({"polygons": [[[0, 0], [1, 1]]]}), encoding="utf-8")
    with pytest.raises(GeometryError):
        privacy_polygons(sample_config, "front", pdir)


def test_repo_cameras_yaml_is_valid_yaml() -> None:
    raw = yaml.safe_load((REPO_ROOT / "config" / "cameras.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)


# ---------------------------------------------------------------------------
# Zone kinds (spec 9.4, FR-008) and nominal field of view (FR-036)
# ---------------------------------------------------------------------------

PORCH = "porch: [[420, 380], [860, 380], [860, 720], [420, 720]]"
KINDED = (
    "front_door_egress: {kind: egress, polygon: [[560, 300], [700, 300], [700, 560], [560, 560]]}"
    "\n      porch: {kind: interior_yard,"
    " polygon: [[420, 380], [860, 380], [860, 720], [420, 720]]}"
)


def test_sample_config_zone_kinds_and_fov(sample_config: Config) -> None:
    kinds = {cam.id: {z: cam.zone_kind(z) for z in cam.zones} for cam in sample_config.cameras}
    assert kinds == {
        "front": {
            "front_door_egress": "egress",
            "porch": "interior_yard",
            "driveway": "interior_yard",
            "driveway_entry": "perimeter",
        },
        "side_left": {"side_alley": "perimeter", "side_yard": "interior_yard"},
        "side_right": {"side_path": "interior_yard"},
        "backyard": {"back_door_egress": "egress", "backyard": "interior_yard"},
    }
    assert sample_config.camera("front").zones["front_door_egress"] == [
        (560, 300),
        (700, 300),
        (700, 560),
        (560, 560),
    ]
    assert all(cam.hfov_deg is not None and 0 < cam.hfov_deg < 180 for cam in sample_config.cameras)


def test_zone_dict_form_loads_and_plain_list_is_interior_yard(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, BASE.replace(PORCH, KINDED)))
    front = cfg.camera("front")
    assert front.zone_kind("front_door_egress") == "egress"
    assert front.zone_kind("porch") == "interior_yard"
    plain = load_config(write(tmp_path, BASE, "plain.yaml")).camera("front")
    assert plain.zone_kinds.get("porch", "interior_yard") == "interior_yard"
    assert plain.zone_kind("porch") == "interior_yard"


@pytest.mark.parametrize("kind", ["door", "garage", "EGRESS", "household"])
def test_unknown_zone_kind_is_a_named_error_with_line(tmp_path: Path, kind: str) -> None:
    text = BASE.replace(PORCH, KINDED.replace("kind: egress", f"kind: {kind}"))
    with pytest.raises(ZoneKindError) as ei:
        load_config(write(tmp_path, text))
    err = ei.value
    assert isinstance(err, ConfigSchemaError)
    assert err.ref == "front_door_egress"
    assert err.line == 6
    assert kind in str(err)
    assert "egress, perimeter, interior_yard" in str(err)


def test_zone_dict_needs_polygon_and_no_extra_keys(tmp_path: Path) -> None:
    missing = BASE.replace(PORCH, "porch: {kind: interior_yard}")
    with pytest.raises(ConfigSchemaError, match="polygon"):
        load_config(write(tmp_path, missing))
    extra = BASE.replace(PORCH, KINDED.replace("{kind: egress,", "{kind: egress, colour: red,"))
    with pytest.raises(ConfigSchemaError, match="colour"):
        load_config(write(tmp_path, extra, "extra.yaml"))


def test_zone_dict_geometry_still_checked(tmp_path: Path) -> None:
    text = BASE.replace(PORCH, KINDED.replace("[700, 560], [560, 560]", "[700, 960], [560, 560]"))
    with pytest.raises(GeometryError, match="outside") as ei:
        load_config(write(tmp_path, text))
    assert ei.value.line == 6


def test_zone_kind_on_unknown_zone_rejected(tmp_path: Path) -> None:
    text = BASE.replace("    zones:\n", "    zone_kinds: {front_door: egress}\n    zones:\n", 1)
    with pytest.raises(UnknownZoneError, match="front_door") as ei:
        load_config(write(tmp_path, text))
    assert ei.value.ref == "front_door"
    assert ei.value.line == 5
    bad = BASE.replace("    zones:\n", "    zone_kinds: {porch: door}\n    zones:\n", 1)
    with pytest.raises(ZoneKindError, match="door"):
        load_config(write(tmp_path, bad, "bad.yaml"))


def test_validate_config_rejects_zone_kind_for_unknown_zone(sample_config: Config) -> None:
    raw = sample_config.model_dump(by_alias=True)
    raw["cameras"][0]["zone_kinds"]["kitchen_door"] = "egress"
    with pytest.raises(UnknownZoneError, match="kitchen_door"):
        validate_config(Config.model_validate(raw))


def test_kinded_zone_names_unique_across_cameras(tmp_path: Path) -> None:
    text = BASE.replace(PORCH, KINDED).replace("side_gate: [[812", "front_door_egress: [[812")
    with pytest.raises(DuplicateIdError, match="front_door_egress"):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize("hfov", ["0", "-10", "180", "400"])
def test_hfov_out_of_range_rejected(tmp_path: Path, hfov: str) -> None:
    text = BASE.replace("    name: Left side\n", f"    name: Left side\n    hfov_deg: {hfov}\n")
    with pytest.raises(ConfigSchemaError, match="hfov_deg") as ei:
        load_config(write(tmp_path, text))
    assert ei.value.line == 13
