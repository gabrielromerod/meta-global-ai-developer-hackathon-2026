"""Zoomed person crops for carried objects (field result, Nov 4).

On a real clip SAM 3.1 found no knife on the full frame, and found it at 0.82 on a 2.75x crop of
the same footage. Code picks the crops from SAM's own person boxes; SAM still does the detecting.
"""

from __future__ import annotations

import itertools

import pytest

from vigil.models import Box, SamFrame, SamObject
from vigil.perception.zoom import CropPlan, map_back, plan_crops, shift_polygons

W, H = 1920, 720


def _person(boxes: list[tuple[float, Box]], obj_id: int = 0) -> SamObject:
    return SamObject(
        window_id="w1",
        camera_id="front",
        phrase="person",
        obj_id=obj_id,
        frames=[SamFrame(frame=i, t=t, box=b) for i, (t, b) in enumerate(boxes)],
    )


def _standing(x: float = 900.0, n: int = 30) -> SamObject:
    return _person([(i / 10, Box(x1=x, y1=300, x2=x + 80, y2=520)) for i in range(n)])


def test_no_person_means_no_crop():
    assert plan_crops([], W, H, t0=0.0, t1=10.0) == []


def test_crop_holds_the_person_and_their_reach_at_a_real_zoom():
    (plan,) = plan_crops([_standing()], W, H, t0=0.0, t1=10.0)
    assert plan.x0 < 900 - 40
    assert plan.x0 + plan.w > 980 + 40
    assert plan.y0 < 300
    assert plan.y0 + plan.h > 520
    assert plan.scale >= 2.0
    assert plan.w % 2 == 0
    assert plan.h % 2 == 0
    assert plan.out_w % 2 == 0
    assert plan.out_h % 2 == 0


def test_a_walker_gets_several_crops_so_the_zoom_stays_high():
    walker = _person(
        [(i / 10, Box(x1=100 + 15 * i, y1=300, x2=180 + 15 * i, y2=520)) for i in range(100)]
    )
    plans = plan_crops([walker], W, H, t0=0.0, t1=10.0)
    assert len(plans) >= 2
    assert len(plans) <= 3
    assert all(p.scale >= 1.5 for p in plans)  # 1500 px in 10 s: full coverage beats zoom
    assert plans[0].t0 == pytest.approx(0.0)
    assert all(a.t1 >= b.t0 for a, b in itertools.pairwise(plans))  # no time left out


def test_crops_per_window_are_capped():
    walker = _person([(i / 10, Box(x1=20 * i, y1=300, x2=20 * i + 80, y2=520)) for i in range(95)])
    assert len(plan_crops([walker], W, H, t0=0.0, t1=10.0)) <= 3


def test_crop_stays_inside_the_frame():
    (plan,) = plan_crops([_standing(x=1830.0)], W, H, t0=0.0, t1=10.0)
    assert plan.x0 >= 0
    assert plan.x0 + plan.w <= W
    assert plan.y0 >= 0
    assert plan.y0 + plan.h <= H


def test_boxes_map_back_to_the_full_frame():
    plan = CropPlan(
        t0=2.0, t1=5.0, x0=1335, y0=438, w=466, h=282, scale=2.75, out_w=1280, out_h=774
    )
    found = SamObject(
        window_id="w1_zoom0",
        camera_id="front",
        phrase="knife",
        obj_id=0,
        width=1280,
        height=774,
        frames=[SamFrame(frame=3, t=2.3, box=Box(x1=275, y1=55, x2=550, y2=110), mask_rle="x")],
    )
    out = map_back(found, plan, window_id="w1", index=1, frame_size=(W, H), fps=10.0, window_t0=0.0)
    assert out.window_id == "w1"
    assert (out.width, out.height) == (W, H)
    assert out.obj_id != found.obj_id  # two crops never share an id
    frame = out.frames[0]
    assert frame.box.x1 == pytest.approx(1435)
    assert frame.box.y1 == pytest.approx(458)
    assert frame.box.x2 == pytest.approx(1535)
    assert frame.box.y2 == pytest.approx(478)
    assert frame.frame == 23
    assert frame.mask_rle is None  # a crop's mask does not fit the full frame


def test_privacy_polygons_follow_the_crop():
    plan = CropPlan(t0=0.0, t1=1.0, x0=100, y0=50, w=200, h=100, scale=2.0, out_w=400, out_h=200)
    # polygons are in the camera's 1280x480 reference; the source file here is 1920x720
    (poly,) = shift_polygons([[(100, 100), (200, 100), (200, 200)]], plan, (1280, 480), (W, H))
    assert poly[0] == pytest.approx((100.0, 200.0))
    assert poly[1] == pytest.approx((400.0, 200.0))
