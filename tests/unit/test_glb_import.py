"""FIXTURE: generated floor/wall GLB through world frame, locate and coverage."""

import numpy as np
import pytest

from vigil.models import Box, TrackFrame
from vigil.spatial import scan
from vigil.spatial.coverage import coverage
from vigil.spatial.geometry import CameraGeom
from vigil.spatial.locate import locate


def generated_glb(path, compression=None):
    vertices = np.array(
        [
            [10, 0, 20],
            [14, 0, 20],
            [14, 0, 24],
            [10, 0, 24],
            [12, 0, 21],
            [12, 2, 21],
            [12, 2, 23],
            [12, 0, 23],
        ],
        dtype="<f4",
    )
    indices = np.array([0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7], dtype="<u2")
    blob = vertices.tobytes() + indices.tobytes()
    doc = {
        "asset": {"version": "2.0", "extras": {"device": "synthetic"}},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": vertices.nbytes},
            {"buffer": 0, "byteOffset": vertices.nbytes, "byteLength": indices.nbytes},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(vertices),
                "type": "VEC3",
                "min": vertices.min(axis=0).tolist(),
                "max": vertices.max(axis=0).tolist(),
            },
            {"bufferView": 1, "componentType": 5123, "count": len(indices), "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0, "translation": [5, 0, 0]}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    if compression:
        doc["extensionsUsed"] = [compression]
    return scan.write_glb(path, doc, blob)


def test_glb_import_world_frame_locate_and_coverage(tmp_path):
    from vigil.spatial import glb

    loader = getattr(glb, "load_glb_scene", None)
    assert callable(loader), "GLB geometry must feed the raycast scene"
    path = generated_glb(tmp_path / "generated.glb")
    frame = scan.world_frame([15, 0, 20], [15, 0, 21], [15, 1, 20])
    scene = loader(path, frame=frame)
    assert scene.ground.xz_bounds() == pytest.approx((0, -4, 4, 0))
    assert scene.occluder_mesh.n_faces == 2
    from tests.unit.test_coverage import cam

    cal = cam("front", (2, 2, 1), (2, 0, -2))
    uv = CameraGeom.from_calibration(cal).project(np.array([[1, 0, -1]]))[0][0]
    point = locate(
        TrackFrame(t=0, box=Box(x1=uv[0] - 10, x2=uv[0] + 10, y1=uv[1] - 60, y2=uv[1])),
        cal,
        scene,
        np.random.default_rng(0),
        track_id="fixture",
    )
    assert point is not None
    assert [point.x, point.z] == pytest.approx([1, -1], abs=0.1)
    cov = coverage(scene, [cal], cell_m=0.25)
    assert cov.visible["front"].any()
    assert cov.blind.any()


@pytest.mark.parametrize("compression", ["KHR_draco_mesh_compression", "EXT_meshopt_compression"])
def test_glb_import_rejects_compression(tmp_path, compression):
    from vigil.spatial import glb

    path = generated_glb(tmp_path / "compressed.glb", compression)
    with pytest.raises(ValueError, match=r"Draco|meshopt"):
        glb.load_glb_scene(path)


def test_glb_import_fifteen_mb_limit(tmp_path):
    from vigil.spatial import glb

    path = tmp_path / "large.glb"
    with path.open("wb") as file:
        file.truncate(15_000_001)
    with pytest.raises(ValueError, match="15 MB"):
        glb.load_glb_scene(path)


def test_glb_import_writes_transformed_viewer_asset(tmp_path):
    import json

    from vigil.spatial import glb

    source = generated_glb(tmp_path / "generated.glb")
    frame = scan.world_frame([15, 0, 20], [15, 0, 21], [15, 1, 20])
    model = glb.import_glb(source, tmp_path / "spatial", frame=frame)
    assert glb.load_glb_scene(model).ground.xz_bounds() == pytest.approx((0, -4, 4, 0))
    doc, _ = scan.read_glb(model)
    assert "extras" not in doc["asset"]
    twin = json.loads((model.parent / "twin.json").read_text())
    assert twin["glb_url"] == "/media/model.glb"


def test_cli_glb_import_and_coverage(tmp_path):
    import json

    from typer.testing import CliRunner

    from tests.unit.test_coverage import cam
    from vigil.cli import app

    source = generated_glb(tmp_path / "generated.glb")
    frame = tmp_path / "frame.json"
    frame.write_text(
        json.dumps({"origin": [15, 0, 20], "x_point": [15, 0, 21], "up_point": [15, 1, 20]})
    )
    out = tmp_path / "spatial"
    result = CliRunner().invoke(
        app, ["spatial", "import-glb", str(source), "--frame", str(frame), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    config = tmp_path / "cameras.yaml"
    config.write_text("cameras:\n- id: front\n  name: Front\n  privacy: none_needed\n")
    calibration = tmp_path / "calibration.json"
    cal = cam("front", (2, 2, 1), (2, 0, -2))
    calibration.write_text(json.dumps([cal.model_dump(mode="json")]))
    grid = tmp_path / "coverage.json"
    result = CliRunner().invoke(
        app,
        [
            "spatial",
            "coverage",
            "--config",
            str(config),
            "--calibration",
            str(calibration),
            "--site-plan",
            str(out / "model.glb"),
            "--grid-out",
            str(grid),
        ],
    )
    assert result.exit_code == 0, result.output
    assert grid.exists()
