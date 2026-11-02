"""Regenerate the authored SAM 3.1 wire-format fixtures in this folder (FR-006).

These are synthetic, authored fixtures (no real footage): they follow the documented SAM
API output grammar (https://dev.meta.ai/docs/sam/reading-segmentation) and are encoded
with meta-sam-parser's own one-bit mask encoder, so the installed parser accepts them.

Run:  uv run python tests/fixtures/meta/sam_make_fixtures.py

Scene (camera side_left, 1280x720, 10 fps, windows of 10 s with 2 s overlap):
  - one person walks left to right along y = 500..599 between t = 0 s and t = 26 s,
    crossing windows w0 [0, 10], w1 [8, 18] and w2 [16, 26]; SAM gives it a different
    object id in each window (0, 3, 1);
  - in w1 a second, static person (id 0) stands at the top left from t = 8 s to 12 s.
Records are emitted every 2nd frame to keep the fixtures small; the API may skip frames.
"""

from __future__ import annotations

import json
from pathlib import Path

from meta_sam_parser._mask_codec import _encode_raster  # fixture authoring only

HERE = Path(__file__).resolve().parent
W, H, FPS = 1280, 720, 10.0
BOX_W, BOX_H = 40, 100
STEP = 2


def ellipse_raster(width: int, height: int) -> list[int]:
    cx, cy = (width - 1) / 2, (height - 1) / 2
    rx, ry = width / 2, height / 2
    return [
        1 if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0 else 0
        for y in range(height)
        for x in range(width)
    ]


_MASK_CACHE: dict[tuple[int, int], str] = {}


def mask_payload(width: int, height: int) -> str:
    key = (width, height)
    if key not in _MASK_CACHE:
        _MASK_CACHE[key] = _encode_raster(ellipse_raster(width, height), width, height)
    return _MASK_CACHE[key]


def record(obj_id: int, x1: int, y1: int, bw: int, bh: int, c: float | None) -> str:
    """One object record; box x2/y2 are inclusive on the wire, the mask is box-sized."""
    conf = "" if c is None else f";c={c:.2f}"
    payload = mask_payload(bw, bh)
    return (
        f"{obj_id}<|box;x1={x1};y1={y1};x2={x1 + bw - 1};y2={y1 + bh - 1};w={W};h={H}{conf}|>"
        f"<|mask;x=0;y=0{conf};data={bh},{bw},{payload}|>"
    )


def person_x(t: float) -> int:
    return round(100 + 1000 * t / 26.0) - BOX_W // 2


def window_lines(t0: float, walker_id: int, extra: bool) -> list[str]:
    lines: list[str] = []
    for frame in range(0, 100, STEP):
        t = t0 + frame / FPS
        recs = []
        conf = round(0.80 + 0.15 * ((frame // STEP) % 3) / 2, 2)
        if extra and t < 12.0:
            recs.append(record(0, 300, 200, BOX_W, BOX_H, 0.66))
        recs.append(record(walker_id, person_x(t), 500, BOX_W, BOX_H, conf))
        lines.append(f"<{frame}f>" + ",".join(recs))
    return lines


def stream_events(text: str, chunk: int = 97) -> list[dict]:
    lane = {"item_id": "msg_fixture_0", "output_index": 0, "content_index": 0}
    events: list[dict] = [{"type": "response.created", "response": {"id": "resp_fixture"}}]
    for i in range(0, len(text), chunk):
        events.append({"type": "response.output_text.delta", **lane, "delta": text[i : i + chunk]})
    events.append({"type": "response.output_text.done", **lane, "text": text})
    events.append({"type": "response.completed", "response": {"id": "resp_fixture"}})
    return events


def main() -> None:
    windows = [("w0", 0.0, 0, False), ("w1", 8.0, 3, True), ("w2", 16.0, 1, False)]
    for name, t0, walker, extra in windows:
        text = "\n".join(window_lines(t0, walker, extra)) + "\n"
        (HERE / f"sam_person_{name}.txt").write_text(text, encoding="utf-8", newline="\n")
        if name == "w0":
            events = stream_events(text)
            (HERE / "sam_person_w0_events.json").write_text(
                json.dumps(events, indent=1) + "\n", encoding="utf-8", newline="\n"
            )

    lane = {"item_id": "msg_fixture_0", "output_index": 0, "content_index": 0}
    empty = [
        {"type": "response.created", "response": {"id": "resp_empty"}},
        {"type": "response.output_text.done", **lane, "text": ""},
        {"type": "response.completed", "response": {"id": "resp_empty"}},
    ]
    (HERE / "sam_empty_events.json").write_text(
        json.dumps(empty, indent=1) + "\n", encoding="utf-8", newline="\n"
    )

    # 16 distinct ids on one frame: the window must be split (spec 3, test_sam_window_split).
    recs = [record(i, 20 + i * 70, 40, 8, 8, None) for i in range(16)]
    (HERE / "sam_16ids.txt").write_text(
        "<0f>" + ",".join(recs) + "\n" + "<1f>" + ",".join(recs[:4]) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Image output for a point prompt (tap-to-protect, FR-019): frame 0, one-bit mask.
    (HERE / "sam_point_image.txt").write_text(
        "<0f>" + record(1, 800, 400, 81, 261, 0.97) + "\n", encoding="utf-8", newline="\n"
    )

    body = {
        "error": {
            "message": "17 objects exceed this model's limit of 16.",
            "type": "invalid_request_error",
            "code": "invalid_prompt",
        }
    }
    (HERE / "sam_400_body.json").write_text(
        json.dumps(body, indent=1) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
