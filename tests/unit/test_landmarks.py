"""SAM 3.1 landmark proposals for calibration (FR-037, UC-10) with a fake client.

The SAM output here is authored in the documented wire grammar (as in
tests/fixtures/meta/sam_make_fixtures.py), with rectangular one-bit masks so the expected
corners and centroids are known exactly. No network, no real stills.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from meta_sam_parser._mask_codec import _encode_raster  # fixture authoring only

from vigil.meta.sam import SAM_MODEL, SamHTTPError, SamRequestError
from vigil.models import CameraCfg
from vigil.spatial.calibrate import MarkerPair
from vigil.spatial.geometry import rle_decode
from vigil.spatial.landmarks import (
    LANDMARK_CONCEPTS,
    LANDMARK_PURPOSE,
    build_landmark_request,
    candidate_points,
    mask_points,
    propose_landmarks,
    to_pair,
)

W, H = 1280, 720


class FakeClient:
    """MetaClient stand-in: records calls and replays canned responses in order."""

    def __init__(self, responses: list[object] | None = None) -> None:
        self.calls: list[dict] = []
        self.uploads: list[Path] = []
        self._responses = list(responses or [])

    def upload(self, path: Path) -> str:
        self.uploads.append(Path(path))
        return f"file-{len(self.uploads)}"

    def responses(self, model, body, purpose, visit_id=None, stream=False):
        self.calls.append({"model": model, "body": body, "purpose": purpose, "stream": stream})
        item = self._responses.pop(0) if self._responses else {"output_text": ""}
        if isinstance(item, BaseException):
            raise item
        return item


def _rect(obj_id: int, x1: int, y1: int, bw: int, bh: int, c: float | None) -> str:
    conf = "" if c is None else f";c={c:.2f}"
    data = _encode_raster([1] * (bw * bh), bw, bh)
    return (
        f"{obj_id}<|box;x1={x1};y1={y1};x2={x1 + bw - 1};y2={y1 + bh - 1};w={W};h={H}{conf}|>"
        f"<|mask;x=0;y=0{conf};data={bh},{bw},{data}|>"
    )


def _image_output(*records: str) -> dict:
    return {"output_text": "<0f>" + ",".join(records) + "\n"}


@pytest.fixture
def still(tmp_path: Path) -> Path:
    p = tmp_path / "still.jpg"
    ok, buf = cv2.imencode(".jpg", np.zeros((H, W, 3), np.uint8))
    assert ok
    p.write_bytes(buf.tobytes())
    return p


CAMERA = CameraCfg(id="side_left", name="Side", width=W, height=H, hfov_deg=100.0)


def test_build_landmark_request_is_one_concept_on_one_image():
    body = build_landmark_request("data:image/jpeg;base64,AAAA", "fence post")
    assert body["model"] == SAM_MODEL
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "fence post"}
    assert content[1] == {"type": "input_image", "image_url": "data:image/jpeg;base64,AAAA"}
    assert body["metadata"]["include_confidence"] == "true"
    with pytest.raises(SamRequestError):
        build_landmark_request("data:image/jpeg;base64,AAAA", "door, gate")


def test_mask_points_corners_base_and_centroid_of_a_rectangle():
    mask = np.zeros((H, W), bool)
    mask[100:300, 400:480] = True  # x 400..479, y 100..299
    pts = {kind: (u, v) for kind, u, v in mask_points(mask)}
    assert pts["corner_tl"] == (400.0, 100.0)
    assert pts["corner_tr"] == (479.0, 100.0)
    assert pts["corner_br"] == (479.0, 299.0)
    assert pts["corner_bl"] == (400.0, 299.0)
    assert pts["base"] == (pytest.approx(439.5), 299.0)
    assert pts["centroid"] == (pytest.approx(439.5), pytest.approx(199.5))
    assert mask_points(np.zeros((H, W), bool)) == []


def test_propose_landmarks_one_request_per_concept(still):
    client = FakeClient(
        [
            _image_output(_rect(1, 400, 100, 80, 200, 0.93)),  # door
            _image_output(),  # gate: zero matches
            _image_output(_rect(1, 900, 300, 12, 150, 0.81), _rect(2, 1000, 310, 12, 140, 0.2)),
            _image_output(_rect(1, 150, 120, 60, 40, 0.77)),  # window
        ]
    )
    props = propose_landmarks(client, still, CAMERA)
    assert [c["body"]["input"][0]["content"][0]["text"] for c in client.calls] == list(
        LANDMARK_CONCEPTS
    )
    assert LANDMARK_CONCEPTS == ("door", "gate", "fence post", "window")
    for call in client.calls:
        assert call["model"] == SAM_MODEL
        assert call["purpose"] == LANDMARK_PURPOSE
        assert call["stream"] is True
        image = call["body"]["input"][0]["content"][1]
        assert image["type"] == "input_image"
        assert image["image_url"].startswith("data:image/jpeg;base64,")
    assert client.uploads == []
    # The low-confidence fence post (0.2) is filtered out.
    assert [(p.concept, p.obj_id) for p in props] == [("door", 1), ("fence post", 1), ("window", 1)]
    door = props[0]
    assert door.camera_id == "side_left"
    assert door.id == "side_left:door:1"
    assert door.confidence == pytest.approx(0.93)
    assert (door.width, door.height) == (W, H)
    assert rle_decode(door.mask_rle, H, W).sum() == 80 * 200
    kinds = {p.kind: (p.u, p.v) for p in door.points}
    assert kinds["corner_tl"] == (400.0, 100.0)
    assert kinds["corner_br"] == (479.0, 299.0)
    assert kinds["base"][1] == 299.0
    assert door.points[0].id == "side_left:door:1:corner_tl"


def test_candidate_points_flatten_and_pair_with_mesh_clicks(still):
    client = FakeClient([_image_output(_rect(1, 400, 100, 80, 200, 0.9))])
    props = propose_landmarks(client, still, CAMERA, concepts=("door",))
    pts = candidate_points(props)
    assert len(pts) == 6
    assert len({p.id for p in pts}) == 6
    pair = to_pair(pts[0], (1.0, 2.1, 4.0))
    assert isinstance(pair, MarkerPair)
    assert (pair.u, pair.v, pair.x, pair.y, pair.z) == (400.0, 100.0, 1.0, 2.1, 4.0)
    assert pair.id == pts[0].id


def test_propose_landmarks_caps_per_concept_and_sorts_by_confidence(still):
    recs = [_rect(i, 100 + 60 * i, 200, 20, 60, 0.5 + 0.04 * i) for i in range(8)]
    client = FakeClient([_image_output(*recs)])
    props = propose_landmarks(
        client, still, "side_left", concepts=("fence post",), max_per_concept=3
    )
    assert [p.obj_id for p in props] == [7, 6, 5]
    assert all(p.camera_id == "side_left" for p in props)


def test_propose_landmarks_skips_tiny_masks(still):
    client = FakeClient([_image_output(_rect(1, 10, 10, 4, 4, 0.99))])
    assert propose_landmarks(client, still, CAMERA, concepts=("window",)) == []


def test_propose_landmarks_still_must_match_processed_frame(tmp_path):
    small = tmp_path / "small.png"
    _ok, buf = cv2.imencode(".png", np.zeros((90, 160, 3), np.uint8))
    small.write_bytes(buf.tobytes())
    with pytest.raises(ValueError, match="1280x720"):
        propose_landmarks(FakeClient(), small, CAMERA)


def test_propose_landmarks_surfaces_http_400(still):
    client = FakeClient([{"status_code": 400, "body": '{"error": "bad"}'}])
    with pytest.raises(SamHTTPError):
        propose_landmarks(client, still, CAMERA, concepts=("door",))


def test_propose_landmarks_skips_a_concept_whose_output_does_not_parse(still):
    client = FakeClient(
        [
            {"output_text": "<0f>garbage that is not sam output\n"},
            _image_output(_rect(1, 1, 1, 30, 30, 0.9)),
        ]
    )
    props = propose_landmarks(client, still, CAMERA, concepts=("door", "gate"))
    assert [p.concept for p in props] == ["gate"]
