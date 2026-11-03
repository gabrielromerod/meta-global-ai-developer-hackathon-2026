"""FR-004/039: full panoramic perception, section-only ground geometry, night transitions."""

from pathlib import Path

import pytest

from tests.fixtures.video.synth import texture_clip
from vigil.ingest.config import load_config
from vigil.models import Appearance, Box, TrackFrame

ROOT = Path(__file__).resolve().parents[2]


def test_duo_detection_full_frame_1920_generated_mp4(tmp_path):
    from vigil.ingest.panorama import cut_camera_windows

    cfg = load_config(ROOT / "config/cameras.yaml")
    camera = cfg.camera("front_left_duo")
    source = texture_clip(tmp_path / "panorama.mp4", 0.4, size=(1920, 720), audio=False)
    windows = cut_camera_windows(source, tmp_path / "windows", camera)
    assert len(windows) == 1
    assert (windows[0].width, windows[0].height) == (1920, 720)
    assert windows[0].illumination == "colour"


def test_duo_half_homography_widens_seam_and_edge_uncertainty():
    from vigil.spatial.panorama import locate_panorama, section_for_pixel

    camera = load_config(ROOT / "config/cameras.yaml").camera("front_left_duo")
    assert section_for_pixel(1200, camera.width) == ("right", 240)
    camera.panorama_homographies = {
        "left": [[0.01, 0, 0], [0, 0.01, 0], [0, 0, 1]],
        "right": [[0.01, 0, 5], [0, 0.01, 0], [0, 0, 1]],
    }
    camera.panorama_r95_m = 0.5

    def locate(x):
        return locate_panorama(
            TrackFrame(t=1, box=Box(x1=x - 5, y1=350, x2=x + 5, y2=500)), camera, "t"
        )

    center, seam, edge = locate(1440), locate(962), locate(1918)
    assert center.x == pytest.approx(9.8)
    assert center.z == 5
    assert center.y == 0
    assert seam.r95 > center.r95
    assert edge.r95 > center.r95
    assert "panoramic_section:right" in seam.flags


def test_floodlight_colour_change_tolerated_without_identifying():
    from vigil.reasoning.visits import appearance_agrees

    a = Appearance(tag="T1", **{"class": "person"}, upper_color="black", illumination="mixed")
    b = Appearance(tag="T2", **{"class": "person"}, upper_color="blue", illumination="colour")
    assert appearance_agrees(a, b)
    assert not appearance_agrees(a.model_copy(update={"illumination": "colour"}), b)


def test_window_illumination_is_persisted_not_dropped(tmp_path):
    from vigil.models import Window
    from vigil.store import db

    conn = db.open_db(tmp_path / "window.db")
    try:
        db.insert_window(
            conn, Window(id="w", camera_id="front_left_duo", t0=0, t1=1, illumination="mixed")
        )
        assert db.rows(conn, "windows")[0]["illumination"] == "mixed"
    finally:
        conn.close()


def test_duo_nominal_half_fov_rectifies_curved_section_before_homography():
    from vigil.spatial.panorama import rectify_section

    x90, y90 = rectify_section(240, 500, 960, 90)
    x120, y120 = rectify_section(240, 500, 960, 120)
    assert 240 < x90 < 480
    assert x120 > x90
    assert y90 == 500
    assert y120 == 500
