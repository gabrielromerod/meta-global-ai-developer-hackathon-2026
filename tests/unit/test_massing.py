"""FR-035 fallback level 2: simplified house massing from LiDAR segments (synthetic only)."""

import json

import numpy as np
import pytest

from tests.unit.test_glb_import import generated_glb
from vigil.spatial import massing


def _ring(rng, box, height, step=0.05):
    """Wall points along a rectangle's perimeter, uniformly up to ``height``."""
    (x0, z0), (x1, z1) = box
    edges = []
    for a, b in (
        ((x0, z0), (x1, z0)),
        ((x1, z0), (x1, z1)),
        ((x1, z1), (x0, z1)),
        ((x0, z1), (x0, z0)),
    ):
        n = int(np.hypot(b[0] - a[0], b[1] - a[1]) / step)
        t = rng.random(n * 20)
        y = rng.random(n * 20) * height
        edges.append(np.c_[a[0] + (b[0] - a[0]) * t, y, a[1] + (b[1] - a[1]) * t])
    return np.concatenate(edges)


def _ground(rng, x0, x1, z0, z1, n=4000):
    return np.c_[rng.uniform(x0, x1, n), rng.normal(0, 0.01, n), rng.uniform(z0, z1, n)]


def test_massing_sample_glb_points_untextured(tmp_path):
    path = generated_glb(tmp_path / "floor.glb")
    points, colors = massing.sample_glb_points(path, per_m2=200, seed=1)
    assert points.shape[1] == 3
    assert len(points) == len(colors) > 100
    assert points[:, 0].min() >= 10 - 1e-6
    assert points[:, 0].max() <= 14 + 1e-6
    assert set(np.unique(points[:, 1]).round(3)) <= set(np.linspace(0, 2, 2001).round(3))
    assert (colors == massing.UNTEXTURED).all()


def test_massing_wall_peaks_finds_walls():
    rng = np.random.default_rng(0)
    values = np.r_[rng.normal(2.0, 0.01, 500), rng.normal(5.5, 0.01, 300), rng.uniform(0, 8, 50)]
    peaks = massing.wall_peaks(values, 0, 8, top=2)
    assert [round(p, 1) for p, _ in peaks] == [2.0, 5.5]


def test_massing_axis_angle_of_a_rotated_wall():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 10, 500)
    z = np.tan(np.radians(1.5)) * x + rng.normal(0, 0.005, 500)
    assert massing.axis_angle(np.c_[x, z]) == pytest.approx(1.5, abs=0.05)


def test_massing_house_frame_is_a_rotation_with_the_door_at_origin():
    to_house = massing.house_frame(door=(2.0, 3.0), front_angle_deg=0.0, base_y=-1.0)
    door, street, side = to_house(np.array([[2.0, -1.0, 3.0], [2.0, -1.0, 9.0], [5.0, -1.0, 3.0]]))
    assert np.allclose(door, 0)
    assert street[2] < 0  # the street side (+z in the scan) becomes -Z: the house lies at +Z
    assert side[0] == pytest.approx(-3.0)  # 180 degrees about Y, never a mirror
    rot = massing.house_rotation(0.0)
    assert np.linalg.det(rot) == pytest.approx(1.0)


def test_massing_segment_alignment_rotates_then_translates():
    seg = {"rotate_deg": 90.0, "translate": [1.0, 2.0], "base_y": 0.5, "reference_base_y": 0.0}
    out = massing.align_segment(np.array([[1.0, 0.5, 0.0]]), seg)
    assert np.allclose(out, [[1.0, 0.0, 3.0]], atol=1e-9)


def test_massing_build_measures_heights_and_classes():
    rng = np.random.default_rng(3)
    walls = _ring(rng, ((-4, 0), (4, 10)), 2.8)
    fence = np.c_[rng.uniform(-6, 6, 3000), rng.uniform(0, 1.7, 3000), np.full(3000, 14.0)]
    lawn = _ground(rng, -6, 6, 10.5, 13.5)
    paving = _ground(rng, -6, 6, -6, -0.5)
    points = np.r_[walls, fence, lawn, paving]
    colors = np.r_[
        np.full((len(walls), 3), 200),
        np.full((len(fence), 3), 120),
        np.tile([90, 150, 70], (len(lawn), 1)),
        np.tile([185, 185, 180], (len(paving), 1)),
    ].astype(np.uint8)
    recipe = {
        "pitch": 4 / 12,
        "buildings": [
            {"id": "main", "min": [-4, 0], "max": [4, 10], "roof": "hip"},
            {"id": "wing", "min": [-4, -3], "max": [-1, 0], "roof": "gable_z", "eave_from": "main"},
        ],
        "fences": [{"id": "back", "from": [-6, 14], "to": [6, 14]}],
        "surfaces": [
            {"id": "yard", "min": [-6, 10.5], "max": [6, 13.5]},
            {"id": "drive", "min": [-6, -6], "max": [6, -0.5]},
        ],
        "cameras": {"cam": {"position": [4, 2.6, 0], "look_at": [0, 0, -6]}},
    }
    doc = massing.build_massing(recipe, points, colors)
    main = doc["site_plan"]["boxes"][0]
    assert main["kind"] == "building"
    assert main["h"] == pytest.approx(2.8, abs=0.1)
    assert doc["site_plan"]["boxes"][1]["h"] == main["h"]
    assert doc["detail"]["roofs"][1]["rise"] == pytest.approx(1.5 * 4 / 12, abs=0.01)
    roof = doc["detail"]["roofs"][0]
    assert roof["type"] == "hip"
    assert roof["rise"] == pytest.approx(4 * 4 / 12, abs=0.01)
    assert doc["detail"]["fences"][0]["h"] == pytest.approx(1.7, abs=0.1)
    kinds = {s["id"]: s["kind"] for s in doc["detail"]["surfaces"]}
    assert kinds == {"yard": "lawn", "drive": "paving"}
    assert doc["camera_layout"]["cam"]["placement_measured"] is False
    json.dumps(doc)  # JSON-serialisable for the API


@pytest.mark.parametrize("key", ["address", "lat", "lon", "glb_url", "texture", "gps", "street"])
def test_massing_validate_rejects_identifying_fields(key):
    doc = massing.build_massing({"buildings": [{"id": "b", "min": [0, 0], "max": [1, 1], "h": 3}]})
    doc["detail"][key] = "x"
    with pytest.raises(ValueError, match="identifying"):
        massing.validate_massing(doc)


def test_massing_validate_rejects_unknown_kinds_and_non_finite():
    doc = massing.build_massing({"buildings": [{"id": "b", "min": [0, 0], "max": [1, 1], "h": 3}]})
    doc["detail"]["surfaces"] = [{"id": "s", "kind": "pool", "min": [0, 0], "max": [1, 1]}]
    with pytest.raises(ValueError, match="kind"):
        massing.validate_massing(doc)
    doc = massing.build_massing({"buildings": [{"id": "b", "min": [0, 0], "max": [1, 1], "h": 3}]})
    doc["site_plan"]["boxes"][0]["h"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        massing.validate_massing(doc)


def test_massing_porch_roof_and_solar_arrays_come_from_the_recipe():
    doc = massing.build_massing(
        {
            "buildings": [
                {"id": "main", "min": [0, 0], "max": [10, 12], "h": 2.8, "roof": "gable_z"}
            ],
            "porches": [
                {"id": "entry", "min": [3, -2], "max": [7, 0], "h": 2.6, "roof": "hip", "rise": 0.6}
            ],
            "solar": [{"id": "array", "min": [0.5, 2], "max": [3, 9]}],
            "pergolas": [
                {"id": "cover", "min": [0, 12], "max": [10, 15], "h": 2.7, "style": "solid"}
            ],
        }
    )
    roofs = {r["id"]: r for r in doc["detail"]["roofs"]}
    assert roofs["main"]["type"] == "gable_z"
    assert roofs["main"]["rise"] == pytest.approx(5 * 0.3333, abs=0.01)
    assert roofs["entry"]["type"] == "hip"
    assert roofs["entry"]["eave"] == pytest.approx(2.6)
    assert roofs["entry"]["rise"] == pytest.approx(0.6)
    assert doc["detail"]["solar"][0]["id"] == "array"
    assert doc["detail"]["pergolas"][0]["style"] == "solid"
