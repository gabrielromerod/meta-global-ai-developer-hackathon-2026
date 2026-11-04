"""Tag labels burned for Spark must stay readable after the privacy mask (FR-009).

Live run, Nov 3: the label sat just above each box, inside the street mask, so the masked
clip showed boxes with no "T4"/"T5" text and Spark swapped the car and the person.
"""

from __future__ import annotations

from vigil.models import Box
from vigil.perception.tagged import label_anchor, label_style

STREET = [[0, 0], [1920, 0], [1920, 350], [0, 350]]


def _rect(anchor, size):
    (x, y), (w, h) = anchor, size
    return x, y - h, x + w, y


def test_tag_label_moves_out_of_a_privacy_mask_above_the_box():
    box = Box(x1=100, y1=352, x2=400, y2=480)
    size = (60, 24)
    anchor = label_anchor(box, size, (1920, 720), [STREET], ref_size=(1920, 720))
    x1, y1, x2, y2 = _rect(anchor, size)
    assert y1 > 350, "label must be below the masked street band"
    assert x1 >= 0
    assert x2 <= 1920
    assert y2 <= 720


def test_tag_label_sits_above_the_box_when_nothing_is_masked():
    box = Box(x1=100, y1=400, x2=400, y2=600)
    anchor = label_anchor(box, (60, 24), (1920, 720), [], ref_size=(1920, 720))
    assert _rect(anchor, (60, 24))[3] <= 400


def test_tag_label_scales_privacy_polygons_to_the_frame():
    # Config polygons are in 1920x720; the clip was scaled to 960x360.
    box = Box(x1=50, y1=176, x2=200, y2=240)
    size = (30, 12)
    anchor = label_anchor(box, size, (960, 360), [STREET], ref_size=(1920, 720))
    assert _rect(anchor, size)[1] > 175


def test_tag_label_is_large_enough_to_read_on_a_wide_frame():
    scale, thickness = label_style(1920)
    assert scale >= 1.2
    assert thickness >= 3
    assert label_style(640)[0] >= 0.6
