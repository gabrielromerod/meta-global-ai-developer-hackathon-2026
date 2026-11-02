"""Spatial: coverage (spec 12.1) — FR-038."""

from __future__ import annotations

import numpy as np
import pytest
import yaml
from shapely.geometry import Point, Polygon, box

from vigil.models import BlindRegion, Calibration, Config
from vigil.spatial.coverage import (
    blind_regions_to_config,
    coverage,
    privacy_from_config,
    write_blind_regions,
)
from vigil.spatial.geometry import (
    Occluder,
    RaycastScene,
    box_mesh,
    look_at_extrinsics,
    pinhole_intrinsics,
    plane_ground,
)

W, H = 1280, 720


def cam(cid: str, pos, target, f: float = 600.0) -> Calibration:
    return Calibration(
        camera_id=cid,
        intrinsics=pinhole_intrinsics(W, H, f=f),
        extrinsics=look_at_extrinsics(pos, target),
    )


WALL_CAM = cam("front", (5.0, 3.0, -1.0), (5.0, 0.0, 6.0))


def wall_scene(with_wall: bool) -> RaycastScene:
    occ = [Occluder("wall", box_mesh((2.0, 0.0, 5.0), (8.0, 2.5, 5.3)))] if with_wall else []
    return RaycastScene(ground=plane_ground(0.0, 0.0, 10.0, 12.0), occluders=occ)


def test_synthetic_wall_blocks_line_of_sight():
    open_cov = coverage(wall_scene(False), [WALL_CAM])
    wall_cov = coverage(wall_scene(True), [WALL_CAM])
    assert open_cov.visible_at("front", 5.0, 4.0)
    assert wall_cov.visible_at("front", 5.0, 4.0)
    for z in (5.6, 6.5, 7.5):
        assert open_cov.visible_at("front", 5.0, z)
        assert not wall_cov.visible_at("front", 5.0, z), z
    # The whole far strip is shadowed (the sight line to z=11.8 is 1.6 m high at the wall)...
    assert not wall_cov.visible_at("front", 5.0, 11.8)
    # ...but a sight line passing beside the wall's end (x = 8.4 m at the wall) stays clear.
    assert wall_cov.visible_at("front", 9.5, 7.0)
    assert wall_cov.visible["front"].sum() < open_cov.visible["front"].sum()
    # Cells under the wall itself are not ground and never count as blind.
    assert not wall_cov.is_blind(5.0, 5.15)


def test_cells_outside_the_image_are_not_visible():
    cov = coverage(wall_scene(False), [WALL_CAM])
    assert not cov.visible_at("front", 5.0, 0.1)  # below the bottom of the image, at the feet
    assert cov.is_blind(5.0, 0.1)


def test_privacy_polygons_remove_cells():
    privacy = {"front": [[(640.0, 0.0), (1280.0, 0.0), (1280.0, 720.0), (640.0, 720.0)]]}
    plain = coverage(wall_scene(False), [WALL_CAM])
    masked = coverage(wall_scene(False), [WALL_CAM], privacy=privacy)
    # Image right half = world -X side for a camera looking along +Z with +Y up.
    assert plain.visible_at("front", 3.0, 6.0)
    assert not masked.visible_at("front", 3.0, 6.0)
    assert masked.visible_at("front", 7.0, 6.0)
    removed = plain.visible["front"] & ~masked.visible["front"]
    assert removed.sum() > 50
    assert not (masked.visible["front"] & ~plain.visible["front"]).any()


def test_privacy_from_config(sample_config: Config):
    priv = privacy_from_config(sample_config)
    assert set(priv) == {"front", "side_left", "side_right"}
    assert priv["front"][0][2] == (1280.0, 140.0)


def two_room_scene() -> tuple[RaycastScene, list[Calibration]]:
    occ = [
        Occluder("shed", box_mesh((2.0, 0.0, 6.0), (4.0, 2.4, 7.0))),
        Occluder("bins", box_mesh((7.0, 0.0, 6.0), (8.5, 1.8, 6.6))),
    ]
    scene = RaycastScene(ground=plane_ground(0.0, 0.0, 10.0, 12.0), occluders=occ)
    return scene, [cam("front", (5.0, 3.0, -2.0), (5.0, 0.0, 6.0))]


def test_blind_regions_form_connected_polygons():
    scene, cams = two_room_scene()
    cov = coverage(scene, cams)
    assert len(cov.regions) >= 2
    total = 0.0
    polys = []
    for r in cov.regions:
        BlindRegion.model_validate(r.model_dump())
        poly = Polygon(r.polygon_m)
        assert poly.is_valid
        assert poly.area > 0
        polys.append(poly)
        total += poly.area
    for i, a in enumerate(polys):
        for b in polys[i + 1 :]:
            assert a.intersection(b).area < 1e-9
    # Every blind cell belongs to exactly one region (regions are at least min cells big).
    cell_area = cov.cell_m**2
    labelled = sum(int(m.sum()) for m in cov.region_masks)
    assert total == pytest.approx(labelled * cell_area)
    assert labelled <= int(cov.blind.sum())
    ids = [r.id for r in cov.regions]
    assert len(set(ids)) == len(ids)
    assert "shed_back" in ids
    assert "bins_back" in ids


def test_yard_with_shed_finds_behind_the_shed_region():
    occ = [
        Occluder("house", box_mesh((-1.0, 0.0, -6.0), (13.0, 5.0, -0.2))),
        Occluder("shed", box_mesh((4.0, 0.0, 9.0), (8.0, 2.4, 11.0))),
    ]
    scene = RaycastScene(ground=plane_ground(0.0, 0.0, 12.0, 14.0), occluders=occ)
    cams = [
        cam("side_left", (0.5, 3.0, 0.3), (6.0, 0.0, 8.0)),
        cam("backyard", (11.5, 3.0, 0.3), (6.0, 0.0, 8.0)),
    ]
    cov = coverage(scene, cams)
    behind = [r for r in cov.regions if r.name == "behind the shed"]
    assert len(behind) == 1
    region = behind[0]
    assert region.id == "shed_back"
    poly = Polygon(region.polygon_m)
    assert poly.contains(Point(6.0, 12.0))
    assert poly.intersection(box(4.0, 9.0, 8.0, 11.0)).area < 1e-9  # not the shed itself
    assert cov.visible_at("side_left", 6.0, 5.0)
    assert cov.visible_at("backyard", 6.0, 5.0)
    assert not cov.is_blind(6.0, 5.0)


def test_blind_regions_written_into_cameras_yaml_dict(tmp_path, repo_root):
    raw = yaml.safe_load((repo_root / "config" / "cameras.yaml").read_text(encoding="utf-8"))
    new = [
        BlindRegion(
            id="shed_back", name="behind the shed", polygon_m=[(4, 11), (8, 11), (8, 14), (4, 14)]
        ),
        BlindRegion(id="blind_1", name="blind region 1", polygon_m=[(0, 0), (1, 0), (1, 1)]),
    ]
    out = blind_regions_to_config(raw, new)
    assert raw["blind_regions"][0]["polygon_m"][0] == [4.1, 9.0]  # input untouched
    ids = [r["id"] for r in out["blind_regions"]]
    assert ids == ["shed_back", "blind_1"]
    assert out["blind_regions"][0]["polygon_m"][0] == [4.0, 11.0]
    Config.model_validate(out)  # topology still resolves shed_back

    src = tmp_path / "cameras.yaml"
    src.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    write_blind_regions(src, new[:1])
    reloaded = Config.model_validate(yaml.safe_load(src.read_text(encoding="utf-8")))
    assert [r.id for r in reloaded.blind_regions] == ["shed_back"]
    assert reloaded.blind_regions[0].polygon_m[2] == (8.0, 14.0)


def test_coverage_to_dict_is_json_ready():
    import json

    scene, cams = two_room_scene()
    d = coverage(scene, cams, cell_m=0.5).to_dict()
    json.dumps(d)
    assert d["cell_m"] == 0.5
    assert len(d["visible"]["front"]) == d["rows"]
    assert len(d["visible"]["front"][0]) == d["cols"]
    assert np.isclose(d["x0"], 0.0)
