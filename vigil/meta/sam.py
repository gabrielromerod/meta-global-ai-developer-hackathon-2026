"""SAM 3.1 concept tracking and point prompts via the Responses API (FR-006, FR-019).

Request shapes follow https://dev.meta.ai/docs/sam/segmenting:

* one concept request = one noun phrase in an ``input_text`` part plus the uploaded window
  as ``{"type": "input_video", "file_id": ...}``; comma lists return zero matches, so they
  are refused here (spec 5.14);
* ``metadata.include_confidence`` is the STRING ``"true"``, never a JSON boolean;
* a point prompt is object-prompt text ``<0f>1<|point;x=..;y=..;w=..;h=..|>`` whose
  ``w``/``h`` equal the media size, built with meta-sam-parser's ``build_object_prompt``.

Output is parsed with meta-sam-parser only (``video_segmentation_format`` /
``image_segmentation_format`` and ``parse_responses_stream`` for event lists); the wire
grammar is never hand-rolled. Masks are box-local rasters on the wire; they are placed into
the full frame and stored as COCO RLE (`vigil.perception.rle`).

Every call goes through an injected client with ``upload()`` and ``responses()`` (the
MetaClient protocol, spec 9.5), which owns retries, cache, budget and ledger. This module
never retries: a 400 is surfaced as ``SamHTTPError`` with its body (spec 3).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from meta_sam_parser import (
    CompletedOutcome,
    FramePrompt,
    ObjectPromptError,
    PromptObject,
    PromptPoint,
    ResponsesStreamError,
    ResponsesStreamLaneError,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    SegmentationTextRecord,
    build_object_prompt,
    decode_mask_to_raster,
    image_segmentation_format,
    parse_responses_stream,
    video_segmentation_format,
)
from pydantic import BaseModel, ConfigDict

from vigil.models import Box, Polygon, SamFrame, SamObject, Window
from vigil.perception.rle import encode_rle, place_box_mask

log = logging.getLogger(__name__)

SAM_MODEL = "sam-3.1"
MAX_OBJECTS = 16
"""SAM 3.1 video tracks up to 16 objects; a window that uses 16 ids is split (spec 3)."""
MAX_PHRASE_CHARS = 64
MIN_SPLIT_S = 2.0
"""Windows shorter than this are not split further."""
SPLIT_OVERLAP_S = 1.0
"""Overlap between the two halves of a split window, so the stitcher can join ids."""

TRACK_PURPOSE = "sam_track"
POINT_PURPOSE = "segment_point"


# ---------------------------------------------------------------------------
# Errors and module-private result types
# ---------------------------------------------------------------------------


class SamRequestError(ValueError):
    """The request cannot be built (not one noun phrase, point outside the media, ...)."""


class SamHTTPError(RuntimeError):
    """SAM answered with an HTTP error. A 400 is never retried: the same request fails again."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"SAM 3.1 returned HTTP {status}: {body[:500]}")


class SamParseError(ValueError):
    """SAM output could not be parsed cleanly; ``diagnostics`` lists what was wrong."""

    def __init__(self, message: str, diagnostics: Sequence[str] = ()) -> None:
        self.diagnostics = list(diagnostics)
        detail = "; ".join(self.diagnostics[:5])
        super().__init__(f"{message}: {detail}" if detail else message)


class PointMask(BaseModel):
    """Mask from a point prompt on a still (FR-019). Module-private until models.py has one."""

    model_config = ConfigDict(extra="forbid")

    obj_id: int
    box: Box
    mask_rle: str
    """COCO RLE counts of the full-frame mask (width x height)."""
    confidence: float | None = None
    width: int
    height: int


class SamClient(Protocol):
    """The subset of MetaClient (spec 9.5) this module uses."""

    def upload(self, path: Path) -> str: ...

    def responses(
        self,
        model: str,
        body: dict,
        purpose: str,
        visit_id: str | None = None,
        stream: bool = False,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------


def validate_phrase(phrase: str) -> str:
    """Return the trimmed noun phrase or raise: exactly one short phrase per request."""
    if not isinstance(phrase, str):
        raise SamRequestError("phrase must be a string")
    p = " ".join(phrase.split())
    if not p:
        raise SamRequestError("empty concept phrase")
    if any(ch in phrase for ch in ",;\n\r|<>"):
        raise SamRequestError(
            f"{phrase!r} is not a single noun phrase: send one request per concept "
            "(comma lists return zero matches)"
        )
    if len(p) > MAX_PHRASE_CHARS:
        raise SamRequestError(f"phrase longer than {MAX_PHRASE_CHARS} characters")
    return p


def _message(text: str, media: dict) -> list[dict]:
    return [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}, media],
        }
    ]


def build_concept_request(
    file_id: str,
    phrase: str,
    *,
    include_confidence: bool = True,
    mask_encoding: str | None = None,
    stream: bool = True,
) -> dict:
    """Body for POST /v1/responses: one noun phrase on one uploaded video."""
    if not file_id:
        raise SamRequestError("file_id is required (upload the window first)")
    return _concept_body(
        phrase,
        {"type": "input_video", "file_id": file_id},
        include_confidence=include_confidence,
        mask_encoding=mask_encoding,
        stream=stream,
    )


def build_image_concept_request(
    image_ref: str,
    phrase: str,
    *,
    include_confidence: bool = True,
    mask_encoding: str | None = None,
    stream: bool = True,
) -> dict:
    """Body for one noun phrase on one still (landmark proposals, FR-037).

    Same rules as :func:`build_concept_request` (one phrase, ``include_confidence`` as the
    string ``"true"``), with the still as ``{"type": "input_image", "image_url": image_ref}``
    (a base64 data URL or an https URL). Parse the answer with :func:`parse_image_output`.
    """
    if not image_ref:
        raise SamRequestError("image_ref is required (a data URL or an image URL)")
    return _concept_body(
        phrase,
        {"type": "input_image", "image_url": image_ref},
        include_confidence=include_confidence,
        mask_encoding=mask_encoding,
        stream=stream,
    )


def _concept_body(
    phrase: str,
    media: dict,
    *,
    include_confidence: bool,
    mask_encoding: str | None,
    stream: bool,
) -> dict:
    body: dict[str, Any] = {
        "model": SAM_MODEL,
        "input": _message(validate_phrase(phrase), media),
        "stream": stream,
    }
    metadata: dict[str, str] = {}
    if include_confidence:
        metadata["include_confidence"] = "true"  # a string, per the docs
    if mask_encoding is not None:
        if mask_encoding not in ("one_bit", "lossless"):
            raise SamRequestError(f"unknown mask_encoding {mask_encoding!r}")
        metadata["mask_encoding"] = mask_encoding
    if metadata:
        body["metadata"] = metadata
    return body


def build_point_request(
    image_ref: str,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    obj_id: int = 1,
    include_confidence: bool = True,
    stream: bool = True,
) -> dict:
    """Body for a single positive point prompt; ``w``/``h`` must be the still's exact size."""
    try:
        text = build_object_prompt(
            size=(int(w), int(h)),
            objects=[PromptObject(id=obj_id, prompts=[FramePrompt(points=[PromptPoint(x, y)])])],
        )
    except ObjectPromptError as err:
        raise SamRequestError(str(err)) from err
    body: dict[str, Any] = {
        "model": SAM_MODEL,
        "input": _message(text, {"type": "input_image", "image_url": image_ref}),
        "stream": stream,
    }
    if include_confidence:
        body["metadata"] = {"include_confidence": "true"}
    return body


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------


def _get(obj: object, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _status_of(err: BaseException) -> int | None:
    for cand in (_get(err, "status_code"), _get(err, "status")):
        if isinstance(cand, int):
            return cand
    resp = _get(err, "response")
    status = _get(resp, "status_code") if resp is not None else None
    return status if isinstance(status, int) else None


def _body_text(obj: object) -> str:
    for key in ("body", "text", "content", "message"):
        val = _get(obj, key)
        if callable(val):
            continue
        if isinstance(val, bytes):
            return val.decode("utf-8", "replace")
        if isinstance(val, str):
            return val
        if isinstance(val, (dict, list)):
            return json.dumps(val)
    resp = _get(obj, "response")
    if resp is not None and resp is not obj:
        text = _get(resp, "text")
        if isinstance(text, str):
            return text
    return str(obj)


def _raise_http(status: int, body: str, purpose: str) -> None:
    log.warning("SAM 3.1 %s returned HTTP %s (not retried): %s", purpose, status, body[:2000])
    raise SamHTTPError(status, body)


def response_payload(raw: object, purpose: str = TRACK_PURPOSE) -> str | list:
    """Output text, or a list of Responses stream events, from whatever the client returned.

    Accepted shapes: a string; a list of stream events; a mapping or object with
    ``output_text``/``text``, ``events``, a Responses ``output`` array, or ``body``. A
    ``status_code``/``status`` of 400 or more raises ``SamHTTPError`` with the body.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    if isinstance(raw, list):
        return raw
    status = _get(raw, "status_code")
    if not isinstance(status, int):
        status = _get(raw, "status") if isinstance(_get(raw, "status"), int) else None
    if isinstance(status, int) and status >= 400:
        _raise_http(status, _body_text(raw), purpose)
    for key in ("output_text", "text"):
        val = _get(raw, key)
        if isinstance(val, str):
            return val
    events = _get(raw, "events")
    if isinstance(events, list):
        return events
    output = _get(raw, "output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            for part in _get(item, "content") or []:
                if _get(part, "type") == "output_text" and isinstance(_get(part, "text"), str):
                    parts.append(_get(part, "text"))
                if _get(part, "type") == "refusal":
                    raise SamParseError("SAM 3.1 refused the request", [str(_get(part, "refusal"))])
        return "".join(parts)
    body = _get(raw, "body")
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    if isinstance(body, str):
        stripped = body.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                return response_payload(json.loads(body), purpose)
            except json.JSONDecodeError:
                pass
        return body
    if isinstance(body, (Mapping, list)):
        return response_payload(body, purpose)
    raise SamParseError(f"unrecognised SAM response shape: {type(raw).__name__}")


def _run(coro_factory: Callable[[], Any]) -> Any:
    """Run a coroutine to completion from sync code, even inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


def _parse_events(events: Iterable[Any], fmt: Any) -> Any:
    events = list(events)

    async def source() -> AsyncIterator[Any]:
        for ev in events:
            yield ev

    async def drain() -> Any:
        stream = parse_responses_stream(source(), fmt)
        return await stream.final_result()

    try:
        return _run(drain)
    except ResponsesStreamLaneError as err:
        types = [_get(e, "type") for e in events]
        has_text = any(isinstance(t, str) and t.startswith("response.output_text") for t in types)
        if not has_text and "response.completed" in types:
            return None  # zero matches: the response completed with no output text
        raise SamParseError("malformed SAM 3.1 event stream", [str(err)]) from err
    except ResponsesStreamError as err:
        raise SamParseError("SAM 3.1 stream failed", [str(err)]) from err


def _parse_text(text: str, fmt: Any) -> Any:
    parser = fmt.create_parser()
    parser.push(text, emit=False)
    return parser.finish(CompletedOutcome()).result


def _parse(output: str | Sequence[Any], fmt: Any) -> Any:
    if isinstance(output, (list, tuple)):
        result = _parse_events(output, fmt)
    else:
        result = _parse_text(output, fmt)
    if result is None:
        return None
    errors = [
        f"line {d.line}: {d.code}: {d.message}" for d in result.diagnostics if d.severity == "error"
    ]
    for d in result.diagnostics:
        if d.severity == "warning":
            log.warning("SAM output line %s: %s (%s)", d.line, d.message, d.code)
    errors += [
        f"unexpected text line: {r.text[:120]!r}"
        for r in result.records
        if isinstance(r, SegmentationTextRecord) and r.text.strip()
    ]
    if result.outcome.status != "completed":
        errors.append(f"incomplete response ({getattr(result.outcome, 'detail', None)})")
    if errors:
        raise SamParseError("SAM 3.1 output did not parse cleanly", errors)
    return result


def _mask_rle(rec: SegmentationMaskRecord, width: int, height: int) -> str:
    raster = np.frombuffer(decode_mask_to_raster(rec.mask), dtype=np.uint8)
    raster = raster.reshape((rec.mask.height, rec.mask.width)).astype(bool)
    b = rec.bounds
    full = place_box_mask(
        raster, int(b.left), int(b.top), int(b.right), int(b.bottom), width, height
    )
    return encode_rle(full)


def _collect(
    result: Any, width: int, height: int, decode_masks: bool
) -> dict[tuple[int, int], dict[str, Any]]:
    """(object id, frame index) -> box, mask RLE and confidence (later revisions win)."""
    out: dict[tuple[int, int], dict[str, Any]] = {}
    if result is None:
        return out
    for rec in result.records:
        if isinstance(rec, SegmentationTextRecord):
            continue
        frame = rec.frame.frame_index if rec.frame is not None else 0
        key = (int(rec.object_id), frame)
        slot = out.setdefault(key, {"box": None, "mask_rle": None, "confidence": None})
        if isinstance(rec, SegmentationBoxRecord):
            slot["box"] = Box(x1=rec.left, y1=rec.top, x2=rec.right, y2=rec.bottom)
            if rec.confidence is not None:
                slot["confidence"] = rec.confidence
        elif isinstance(rec, SegmentationMaskRecord):
            if decode_masks:
                slot["mask_rle"] = _mask_rle(rec, width, height)
            if slot["confidence"] is None and rec.confidence is not None:
                slot["confidence"] = rec.confidence
    return out


def parse_video_output(
    output: str | Sequence[Any],
    window: Window,
    phrase: str,
    *,
    decode_masks: bool = True,
) -> list[SamObject]:
    """Parse SAM 3.1 video output (text or Responses events) into one SamObject per id.

    Frame index -> session time: ``t = window.t0 + frame / window.fps``. Zero matches give
    ``[]``. Error diagnostics, stray text lines, failed or incomplete streams raise
    ``SamParseError``.
    """
    result = _parse(output, video_segmentation_format())
    slots = _collect(result, window.width, window.height, decode_masks)
    by_obj: dict[int, list[SamFrame]] = {}
    for (obj_id, frame), slot in sorted(slots.items()):
        if slot["box"] is None:
            continue
        t = frame_time(window, frame)
        by_obj.setdefault(obj_id, []).append(
            SamFrame(
                frame=frame,
                t=t,
                box=slot["box"],
                mask_rle=slot["mask_rle"],
                confidence=slot["confidence"],
            )
        )
    return [
        SamObject(
            window_id=window.id,
            camera_id=window.camera_id,
            phrase=phrase,
            obj_id=obj_id,
            frames=frames,
            width=window.width,
            height=window.height,
        )
        for obj_id, frames in sorted(by_obj.items())
    ]


def parse_image_output(output: str | Sequence[Any], width: int, height: int) -> list[PointMask]:
    """Parse SAM 3.1 image output (point, box or concept prompt on a still)."""
    result = _parse(output, image_segmentation_format())
    slots = _collect(result, width, height, True)
    return [
        PointMask(
            obj_id=obj_id,
            box=slot["box"],
            mask_rle=slot["mask_rle"],
            confidence=slot["confidence"],
            width=width,
            height=height,
        )
        for (obj_id, _), slot in sorted(slots.items())
        if slot["box"] is not None and slot["mask_rle"] is not None
    ]


# ---------------------------------------------------------------------------
# Window split (spec 3: more than 16 objects in a window)
# ---------------------------------------------------------------------------


def needs_split(objs: Sequence[SamObject], limit: int = MAX_OBJECTS) -> bool:
    """True when the response used ``limit`` distinct object ids (SAM may have dropped more)."""
    return len({(o.window_id, o.obj_id) for o in objs}) >= limit


def split_window(
    w: Window, overlap_s: float = SPLIT_OVERLAP_S, min_s: float = MIN_SPLIT_S
) -> tuple[Window, Window]:
    """Split a window into two halves that overlap by ``overlap_s`` (for stitching).

    The halves keep camera, fps and size, and have no file yet (they must be cut and
    uploaded). Raises ``SamRequestError`` when the window is too short to split.
    """
    dur = w.t1 - w.t0
    if dur < max(min_s, 2 * overlap_s):
        raise SamRequestError(f"window {w.id} ({dur:.1f} s) is too short to split")
    mid = w.t0 + dur / 2
    half = overlap_s / 2
    common = {
        "camera_id": w.camera_id,
        "fps": w.fps,
        "width": w.width,
        "height": w.height,
        "motion": w.motion,
        "trigger": w.trigger,
        "status": "pending",
    }
    first = Window(id=f"{w.id}.a", t0=w.t0, t1=round(mid + half, 6), **common)
    second = Window(id=f"{w.id}.b", t0=round(mid - half, 6), t1=w.t1, **common)
    return first, second


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


def _call(c: SamClient, body: dict, purpose: str, visit_id: str | None = None) -> Any:
    try:
        return c.responses(SAM_MODEL, body, purpose, visit_id=visit_id, stream=True)
    except SamHTTPError:
        raise
    except Exception as err:
        status = _status_of(err)
        if status == 400:
            _raise_http(400, _body_text(err), purpose)
        raise


def ensure_uploaded(
    c: SamClient,
    w: Window,
    *,
    polygons: Sequence[Polygon] | None = None,
    ref_size: tuple[int, int] | None = None,
) -> str:
    """Upload the window once and remember its file id on the window (spec 5.4)."""
    if w.file_id:
        return w.file_id
    if not w.path:
        raise SamRequestError(f"window {w.id} has neither a file_id nor a path")
    from vigil.ingest.privacy import assert_uploadable

    assert_uploadable(w.path, polygons, ref_size=ref_size or (w.width, w.height))
    w.file_id = c.upload(Path(w.path))
    return w.file_id


Cutter = Callable[[Window, float, float], Path]
"""Cuts [t0, t1] of a window's clip to a new file (owned by ingest; injected here)."""


def track_concept(
    c: SamClient,
    w: Window,
    phrase: str,
    *,
    cut: Cutter | None = None,
    max_depth: int = 2,
    include_confidence: bool = True,
    decode_masks: bool = True,
    visit_id: str | None = None,
    polygons: Sequence[Polygon] | None = None,
    ref_size: tuple[int, int] | None = None,
    _depth: int = 0,
) -> list[SamObject]:
    """Track one noun phrase in one window (FR-006).

    Uploads the window once (its ``file_id`` is stored on ``w``), sends one concept request,
    and parses the output. When 16 ids are used and a ``cut`` function is given, the window
    is split into two overlapping halves which are cut, uploaded and re-run (up to
    ``max_depth`` levels); without ``cut`` the saturated result is returned with a warning.
    """
    body = build_concept_request(
        ensure_uploaded(c, w, polygons=polygons, ref_size=ref_size),
        phrase,
        include_confidence=include_confidence,
    )
    raw = _call(c, body, TRACK_PURPOSE, visit_id)
    objs = parse_video_output(
        response_payload(raw, TRACK_PURPOSE), w, phrase, decode_masks=decode_masks
    )
    if not needs_split(objs):
        return objs
    if cut is None or _depth >= max_depth or (w.t1 - w.t0) < 2 * MIN_SPLIT_S:
        log.warning(
            "window %s used %d SAM ids for %r; not split (cut=%s, depth=%d)",
            w.id,
            MAX_OBJECTS,
            phrase,
            cut is not None,
            _depth,
        )
        return objs
    out: list[SamObject] = []
    for half in split_window(w):
        half.path = str(cut(w, half.t0, half.t1))
        out += track_concept(
            c,
            half,
            phrase,
            cut=cut,
            max_depth=max_depth,
            include_confidence=include_confidence,
            decode_masks=decode_masks,
            visit_id=visit_id,
            polygons=polygons,
            ref_size=ref_size,
            _depth=_depth + 1,
        )
    return out


_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _image_size(data: bytes) -> tuple[int, int]:
    import cv2  # opencv-python-headless is a core dependency

    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SamRequestError("could not decode the still image")
    return int(img.shape[1]), int(img.shape[0])


def segment_point(
    c: SamClient, still: Path, x: int, y: int, *, visit_id: str | None = None
) -> PointMask:
    """Tap-to-protect (FR-019): one positive point on a still; returns the object's mask.

    The prompt's ``w``/``h`` are the still's exact pixel size, and the still is sent as a
    base64 data URL. Raises ``SamParseError`` when SAM returns no mask.
    """
    path = Path(still)
    data = path.read_bytes()
    width, height = _image_size(data)
    mime = _MIME.get(path.suffix.lower(), "image/jpeg")
    ref = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    body = build_point_request(ref, int(x), int(y), width, height)
    raw = _call(c, body, POINT_PURPOSE, visit_id)
    masks = parse_image_output(response_payload(raw, POINT_PURPOSE), width, height)
    if not masks:
        raise SamParseError("SAM 3.1 returned no mask for the point prompt")
    return masks[0]


def frame_time(window: Window, frame: int) -> float:
    """Session time of a window frame index (``t0 + frame / fps``)."""
    if window.fps <= 0 or not math.isfinite(window.fps):
        raise ValueError("window fps must be positive")
    return round(window.t0 + frame / window.fps, 6)
