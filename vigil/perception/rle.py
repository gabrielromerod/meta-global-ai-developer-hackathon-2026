"""COCO compressed RLE for full-frame masks (the `mask_rle` field of SamFrame/TrackFrame).

Counts strings follow the COCO API (`maskApi.c` rleToString/rleFrString): runs over the
column-major (Fortran-order) raster, starting with a run of zeros, delta-coded and packed
into printable characters. The same strings are produced by meta-sam-parser's
`decode_mask_to_rle`, and are readable by pycocotools in the browser or Python.
"""

from __future__ import annotations

import numpy as np


def _runs(mask: np.ndarray) -> list[int]:
    flat = np.asarray(mask, dtype=bool).ravel(order="F")
    if flat.size == 0:
        return []
    change = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    bounds = np.concatenate(([0], change, [flat.size]))
    runs = np.diff(bounds).tolist()
    if flat[0]:
        runs.insert(0, 0)
    return runs


def encode_rle(mask: np.ndarray) -> str:
    """Encode a 2-D boolean mask (height, width) as a COCO compressed counts string."""
    counts = _runs(mask)
    out: list[str] = []
    for i, cnt in enumerate(counts):
        x = cnt - counts[i - 2] if i > 2 else cnt
        more = True
        while more:
            c = x & 0x1F
            x >>= 5
            more = (x != -1) if (c & 0x10) else (x != 0)
            if more:
                c |= 0x20
            out.append(chr(c + 48))
    return "".join(out)


def rle_counts(counts: str) -> list[int]:
    """Decode a COCO counts string into run lengths."""
    cnts: list[int] = []
    p = 0
    n = len(counts)
    while p < n:
        x = 0
        k = 0
        more = True
        while more:
            if p >= n:
                raise ValueError("truncated RLE counts string")
            c = ord(counts[p]) - 48
            x |= (c & 0x1F) << (5 * k)
            more = bool(c & 0x20)
            p += 1
            k += 1
            if not more and (c & 0x10):
                x |= -1 << (5 * k)
        if len(cnts) > 2:
            x += cnts[-2]
        cnts.append(x)
    return cnts


def decode_rle(counts: str, height: int, width: int) -> np.ndarray:
    """Decode a COCO counts string into a boolean mask of shape (height, width)."""
    flat = np.zeros(height * width, dtype=bool)
    pos = 0
    value = False
    for run in rle_counts(counts):
        if run < 0 or pos + run > flat.size:
            raise ValueError("RLE counts do not fit the mask size")
        if value:
            flat[pos : pos + run] = True
        pos += run
        value = not value
    if pos != flat.size:
        raise ValueError("RLE counts do not cover the mask size")
    return flat.reshape((width, height)).T.copy()


def place_box_mask(
    raster: np.ndarray,
    left: int,
    top: int,
    right: int,
    bottom: int,
    width: int,
    height: int,
) -> np.ndarray:
    """Place a box-local mask raster into a full frame at half-open bounds.

    SAM returns a mask raster whose bounds equal its paired box; when the raster's own size
    differs from the box it is resized with nearest-neighbour sampling. Parts outside the
    frame are dropped.
    """
    frame = np.zeros((height, width), dtype=bool)
    bw, bh = right - left, bottom - top
    if bw <= 0 or bh <= 0:
        return frame
    local = np.asarray(raster, dtype=bool)
    if local.shape != (bh, bw):
        rows = (np.arange(bh) * local.shape[0] // bh).clip(0, local.shape[0] - 1)
        cols = (np.arange(bw) * local.shape[1] // bw).clip(0, local.shape[1] - 1)
        local = local[rows][:, cols]
    x0, y0 = max(left, 0), max(top, 0)
    x1, y1 = min(right, width), min(bottom, height)
    if x1 <= x0 or y1 <= y0:
        return frame
    frame[y0:y1, x0:x1] = local[y0 - top : y1 - top, x0 - left : x1 - left]
    return frame


def rle_area(counts: str) -> int:
    """Number of foreground pixels, without materialising the mask."""
    return sum(rle_counts(counts)[1::2])
