"""SAM 3.1 request building and output parsing (FR-006, FR-019 request side, spec 3 and 5.14).

All fixtures are authored in the documented wire format (tests/fixtures/meta/sam_*), and
every model call goes to a fake client: no network, no credentials.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from meta_sam_parser import SegmentationMask, decode_mask_to_rle

from vigil.meta import sam
from vigil.meta.sam import (
    MAX_OBJECTS,
    SamHTTPError,
    SamParseError,
    SamRequestError,
    build_concept_request,
    build_point_request,
    needs_split,
    parse_image_output,
    parse_video_output,
    split_window,
    track_concept,
)
from vigil.models import SamObject, Window
from vigil.perception.rle import decode_rle, encode_rle

META = Path(__file__).resolve().parents[1] / "fixtures" / "meta"


def _text(name: str) -> str:
    return (META / name).read_text(encoding="utf-8")


def _window(wid: str = "w0", t0: float = 0.0, **kw) -> Window:
    return Window(id=wid, camera_id="side_left", t0=t0, t1=t0 + 10.0, **kw)


class FakeClient:
    """MetaClient stand-in: records calls and replays canned responses."""

    def __init__(self, responses: list[object] | None = None) -> None:
        self.uploads: list[Path] = []
        self.calls: list[dict] = []
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


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------


def test_build_concept_request_shape() -> None:
    body = build_concept_request("file-abc", "person")
    assert body["model"] == "sam-3.1"
    assert body["stream"] is True
    msg = body["input"][0]
    assert msg["type"] == "message"
    assert msg["role"] == "user"
    assert msg["content"][0] == {"type": "input_text", "text": "person"}
    assert msg["content"][1] == {"type": "input_video", "file_id": "file-abc"}
    # Must be the STRING "true", never a JSON boolean (spec 5.14).
    assert body["metadata"]["include_confidence"] == "true"
    assert isinstance(body["metadata"]["include_confidence"], str)


def test_build_concept_request_trims_and_allows_multiword() -> None:
    body = build_concept_request("file-abc", "  red bicycle ")
    assert body["input"][0]["content"][0]["text"] == "red bicycle"
    no_conf = build_concept_request("file-abc", "car", include_confidence=False)
    assert "include_confidence" not in no_conf.get("metadata", {})


@pytest.mark.parametrize(
    "phrase", ["person, car", "bus,bicycle", "", "   ", "person; car", "a\nb", "<0f>1<|point|>"]
)
def test_build_concept_request_rejects_non_single_phrase(phrase: str) -> None:
    with pytest.raises(SamRequestError):
        build_concept_request("file-abc", phrase)


def test_build_point_request_uses_media_size() -> None:
    body = build_point_request("data:image/jpeg;base64,AAAA", 840, 520, 1280, 720)
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "<0f>1<|point;x=840;y=520;w=1280;h=720|>"}
    assert content[1] == {"type": "input_image", "image_url": "data:image/jpeg;base64,AAAA"}
    assert body["model"] == "sam-3.1"


def test_build_image_concept_request_shape() -> None:
    """Landmark proposals (FR-037): one noun phrase on one still, sent as input_image."""
    ref = "data:image/jpeg;base64,AAAA"
    body = sam.build_image_concept_request(ref, "  fence post ")
    assert body["model"] == "sam-3.1"
    assert body["stream"] is True
    msg = body["input"][0]
    assert (msg["type"], msg["role"]) == ("message", "user")
    assert msg["content"] == [
        {"type": "input_text", "text": "fence post"},
        {"type": "input_image", "image_url": ref},
    ]
    assert body["metadata"] == {"include_confidence": "true"}
    no_conf = sam.build_image_concept_request(ref, "door", include_confidence=False)
    assert "metadata" not in no_conf


@pytest.mark.parametrize("phrase", ["door, gate", "", "a\nb"])
def test_build_image_concept_request_rejects_non_single_phrase(phrase: str) -> None:
    with pytest.raises(SamRequestError):
        sam.build_image_concept_request("data:image/jpeg;base64,AAAA", phrase)


def test_build_image_concept_request_needs_an_image() -> None:
    with pytest.raises(SamRequestError):
        sam.build_image_concept_request("", "door")


@pytest.mark.parametrize("xy", [(1280, 10), (10, 720), (-1, 5)])
def test_build_point_request_rejects_point_outside_media(xy: tuple[int, int]) -> None:
    with pytest.raises(SamRequestError):
        build_point_request("https://example.invalid/still.jpg", xy[0], xy[1], 1280, 720)


# ---------------------------------------------------------------------------
# Parsing recorded output
# ---------------------------------------------------------------------------


def test_sam_parse_recorded_window() -> None:
    w = _window("w0", 0.0)
    objs = parse_video_output(_text("sam_person_w0.txt"), w, "person")
    assert len(objs) == 1
    obj = objs[0]
    assert isinstance(obj, SamObject)
    assert (obj.window_id, obj.camera_id, obj.phrase, obj.obj_id) == (
        "w0",
        "side_left",
        "person",
        0,
    )
    assert len(obj.frames) == 50
    f0, f1 = obj.frames[0], obj.frames[1]
    assert (f0.frame, f0.t) == (0, 0.0)
    assert f1.frame == 2
    assert f1.t == pytest.approx(0.2)
    # Wire boxes are inclusive; contract boxes are half-open pixel edges.
    assert (f0.box.x1, f0.box.y1, f0.box.x2, f0.box.y2) == (80, 500, 120, 600)
    assert f0.confidence == pytest.approx(0.80)
    assert obj.frames[1].confidence == pytest.approx(0.88)


def test_sam_parse_time_uses_window_t0_and_fps() -> None:
    w = _window("w1", 8.0, fps=10.0)
    objs = parse_video_output(_text("sam_person_w1.txt"), w, "person")
    assert [o.obj_id for o in objs] == [0, 3]
    walker = objs[1]
    assert walker.frames[0].t == pytest.approx(8.0)
    assert walker.frames[-1].frame == 98
    assert walker.frames[-1].t == pytest.approx(8.0 + 98 / 10.0)
    static = objs[0]
    assert max(f.t for f in static.frames) < 12.0


def test_sam_parse_mask_is_full_frame_rle_at_box() -> None:
    w = _window("w0", 0.0)
    obj = parse_video_output(_text("sam_person_w0.txt"), w, "person")[0]
    f0 = obj.frames[0]
    assert f0.mask_rle is not None
    mask = decode_rle(f0.mask_rle, 720, 1280)
    assert mask.shape == (720, 1280)
    ys, xs = np.nonzero(mask)
    assert xs.min() >= f0.box.x1
    assert xs.max() < f0.box.x2
    assert ys.min() >= f0.box.y1
    assert ys.max() < f0.box.y2
    assert 0.6 * f0.box.area < mask.sum() < f0.box.area


def test_sam_parse_without_mask_decoding_keeps_boxes() -> None:
    w = _window("w0", 0.0)
    obj = parse_video_output(_text("sam_person_w0.txt"), w, "person", decode_masks=False)[0]
    assert obj.frames[0].mask_rle is None
    assert obj.frames[0].box.x1 == 80


def test_sam_parse_stream_events_match_text() -> None:
    w = _window("w0", 0.0)
    events = json.loads(_text("sam_person_w0_events.json"))
    from_events = parse_video_output(events, w, "person")
    from_text = parse_video_output(_text("sam_person_w0.txt"), w, "person")
    assert from_events == from_text


def test_sam_parse_empty() -> None:
    """Zero matches is a normal result: an empty list, not an error (spec 3)."""
    w = _window()
    assert parse_video_output("", w, "package") == []
    assert parse_video_output("\n", w, "package") == []
    assert parse_video_output(json.loads(_text("sam_empty_events.json")), w, "package") == []
    # A stream that completes with no output_text events at all is also empty.
    bare = [{"type": "response.created"}, {"type": "response.completed"}]
    assert parse_video_output(bare, w, "package") == []
    client = FakeClient([{"output_text": ""}])
    assert track_concept(client, _window(file_id="file-1"), "package") == []


def test_sam_parse_errors_are_surfaced() -> None:
    w = _window()
    bad = "<0f>0<|box;x1=10;y1=10;x2=5;y2=20;w=1280;h=720|><|mask;x=0;y=0;data=1,1,!!!!!!|>\n"
    with pytest.raises(SamParseError) as err:
        parse_video_output(bad, w, "person")
    assert err.value.diagnostics
    with pytest.raises(SamParseError):
        parse_video_output("I could not find anything.\n", w, "person")


def test_sam_parse_stream_failure_is_surfaced() -> None:
    events = [
        {"type": "response.created"},
        {"type": "response.failed", "response": {"error": {"message": "boom"}}},
    ]
    with pytest.raises(SamParseError, match="boom"):
        parse_video_output(events, _window(), "person")


def test_sam_parse_missing_confidence_is_none() -> None:
    w = _window()
    objs = parse_video_output(_text("sam_16ids.txt"), w, "person")
    assert all(f.confidence is None for o in objs for f in o.frames)


def test_sam_parse_image_output() -> None:
    masks = parse_image_output(_text("sam_point_image.txt"), 1280, 720)
    assert len(masks) == 1
    m = masks[0]
    assert (m.box.x1, m.box.y1, m.box.x2, m.box.y2) == (800, 400, 881, 661)
    assert m.confidence == pytest.approx(0.97)
    assert decode_rle(m.mask_rle, 720, 1280).sum() > 0


# ---------------------------------------------------------------------------
# Client interaction: 400, uploads, window split
# ---------------------------------------------------------------------------


class _HTTPError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.body = body


def test_sam_400() -> None:
    """A 400 is surfaced with its body and never retried (spec 3)."""
    body = _text("sam_400_body.json")
    client = FakeClient([_HTTPError(400, body)])
    with pytest.raises(SamHTTPError) as err:
        track_concept(client, _window(file_id="file-1"), "person")
    assert err.value.status == 400
    assert "17 objects exceed" in err.value.body
    assert len(client.calls) == 1

    # Same when the client returns an error response object instead of raising.
    client = FakeClient([{"status_code": 400, "body": body}])
    with pytest.raises(SamHTTPError) as err:
        track_concept(client, _window(file_id="file-1"), "person")
    assert "limit of 16" in err.value.body
    assert len(client.calls) == 1


def test_sam_non_400_errors_propagate_unchanged() -> None:
    client = FakeClient([_HTTPError(503, "unavailable")])
    with pytest.raises(_HTTPError):
        track_concept(client, _window(file_id="file-1"), "person")


def test_track_concept_uploads_window_once(tmp_path: Path) -> None:
    clip = tmp_path / "w0.mp4"
    from tests.fixtures.video.synth import blob_clip

    blob_clip(clip, 0.2, size=(160, 90))
    w = _window("w0", 0.0, path=str(clip))
    client = FakeClient([{"output_text": _text("sam_person_w0.txt")}, {"output_text": ""}])
    people = track_concept(client, w, "person", polygons=[])
    cars = track_concept(client, w, "car", polygons=[])
    assert len(client.uploads) == 1
    assert w.file_id == "file-1"
    assert [c["body"]["input"][0]["content"][1]["file_id"] for c in client.calls] == [
        "file-1",
        "file-1",
    ]
    assert all(c["model"] == "sam-3.1" and c["stream"] is True for c in client.calls)
    assert len(people) == 1
    assert cars == []


def test_track_concept_accepts_event_list_response() -> None:
    events = json.loads(_text("sam_person_w0_events.json"))
    client = FakeClient([{"events": events}])
    objs = track_concept(client, _window(file_id="file-1"), "person")
    assert len(objs) == 1
    assert len(objs[0].frames) == 50


def test_sam_window_split(tmp_path: Path) -> None:
    """16 object ids in a window means split it in half and re-run (spec 3)."""
    w = _window("w5", 40.0, path=str(tmp_path / "w5.mp4"), file_id="file-w5")
    full = parse_video_output(_text("sam_16ids.txt"), w, "person")
    assert len({o.obj_id for o in full}) == MAX_OBJECTS == 16
    assert needs_split(full)
    assert not needs_split(full[:15])
    assert not needs_split([])

    a, b = split_window(w)
    assert (a.t0, b.t1) == (40.0, 50.0)
    assert a.t1 > 45.0 > b.t0  # halves overlap a little so tracks can be stitched
    assert a.t1 - a.t0 == pytest.approx(b.t1 - b.t0)
    assert a.id != b.id != w.id
    assert a.camera_id == b.camera_id == "side_left"
    assert a.file_id is None
    assert b.file_id is None
    assert (a.fps, a.width, a.height) == (w.fps, w.width, w.height)

    cuts: list[tuple[float, float]] = []

    def cut(win: Window, t0: float, t1: float) -> Path:
        cuts.append((t0, t1))
        out = tmp_path / f"{win.id}_{t0:.1f}_{t1:.1f}.mp4"
        from tests.fixtures.video.synth import blob_clip

        blob_clip(out, 0.2, size=(160, 90))
        return out

    client = FakeClient(
        [
            {"output_text": _text("sam_16ids.txt")},
            {"output_text": _text("sam_person_w0.txt")},
            {"output_text": ""},
        ]
    )
    objs = track_concept(client, w, "person", cut=cut, polygons=[])
    assert cuts == [(a.t0, a.t1), (b.t0, b.t1)]
    assert len(client.calls) == 3
    assert len(client.uploads) == 2
    assert {o.window_id for o in objs} == {a.id}
    assert objs[0].frames[0].t == pytest.approx(a.t0)


def test_sam_window_split_without_cutter_keeps_result() -> None:
    w = _window("w5", 40.0, file_id="file-w5")
    client = FakeClient([{"output_text": _text("sam_16ids.txt")}])
    objs = track_concept(client, w, "person")
    assert len(objs) == 16
    assert len(client.calls) == 1


def test_segment_point_with_fake_client(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    still = tmp_path / "still.jpg"
    ok, buf = cv2.imencode(".jpg", np.zeros((720, 1280, 3), dtype=np.uint8))
    assert ok
    still.write_bytes(buf.tobytes())
    client = FakeClient([{"output_text": _text("sam_point_image.txt")}])
    m = sam.segment_point(client, still, 840, 520, polygons=[])
    text = client.calls[0]["body"]["input"][0]["content"][0]["text"]
    assert text == "<0f>1<|point;x=840;y=520;w=1280;h=720|>"
    image_url = client.calls[0]["body"]["input"][0]["content"][1]["image_url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert (m.width, m.height) == (1280, 720)
    assert m.box.x1 == 800


def test_segment_point_no_mask_raises(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    still = tmp_path / "still.png"
    _ok, buf = cv2.imencode(".png", np.zeros((90, 160, 3), dtype=np.uint8))
    still.write_bytes(buf.tobytes())
    client = FakeClient([{"output_text": ""}])
    with pytest.raises(SamParseError):
        sam.segment_point(client, still, 10, 10, polygons=[])


# ---------------------------------------------------------------------------
# COCO RLE helpers
# ---------------------------------------------------------------------------


def test_rle_roundtrip_and_matches_parser_encoding() -> None:
    rng = np.random.default_rng(7)
    m = rng.random((37, 53)) > 0.6
    counts = encode_rle(m)
    assert np.array_equal(decode_rle(counts, 37, 53), m)
    assert not decode_rle(encode_rle(np.zeros((4, 5), bool)), 4, 5).any()
    assert decode_rle(encode_rle(np.ones((4, 5), bool)), 4, 5).all()

    # Cross-check with meta-sam-parser's own COCO encoder on a box-local mask.
    line = _text("sam_point_image.txt")
    payload = line.split("data=")[1].split("|>")[0]
    h, wd, enc = payload.split(",", 2)
    seg = SegmentationMask(encoding="one_bit", payload=enc, width=int(wd), height=int(h))
    ref = decode_mask_to_rle(seg)
    assert ref.size == (int(h), int(wd))
    raster = decode_rle(ref.counts, int(h), int(wd))
    assert encode_rle(raster) == ref.counts
