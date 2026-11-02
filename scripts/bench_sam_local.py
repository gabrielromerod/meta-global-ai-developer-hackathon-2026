"""H-02 local SAM 3.1 benchmark skeleton (spec 10.2; gate Mon 22:00 PT).

    uv run python scripts/bench_sam_local.py --plan     # print the grid, exit 0
    uv run python scripts/bench_sam_local.py            # run it (needs torch + sam3 + GPU)

Grid: video chunks of 2, 3, 5 and 10 s, at 640 and 960 px wide, 5 and 10 fps. For each
cell: peak VRAM, seconds per 10 s window, out-of-memory failures. Gate H-02 passes when a
10 s window, processed in chunks, finishes in 10 s or less with at most 1 extra ID switch
versus the API.

Without torch, the `sam3` package (facebookresearch/sam3) and an H-01 Ready report, the
script exits 2 with a "blocked" message; nothing here ever calls the paid API.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHUNKS_S = (2, 3, 5, 10)
WIDTHS = (640, 960)
FPS = (5, 10)
OUT = REPO / "eval" / "hardware" / "sam_local_bench.json"


def grid() -> list[dict]:
    return [
        {"chunk_s": c, "width": w, "fps": f, "overlap_s": 1 if c < 10 else 0}
        for c, w, f in itertools.product(CHUNKS_S, WIDTHS, FPS)
    ]


def missing_requirements() -> list[str]:
    missing = [m for m in ("torch", "sam3") if importlib.util.find_spec(m) is None]
    if "torch" not in missing:
        import torch

        if not torch.cuda.is_available():
            missing.append("CUDA device (torch.cuda.is_available() is False)")
    ready = sorted((REPO / "eval" / "hardware").glob("*.json"))
    if not any(_is_ready(p) for p in ready):
        missing.append("an H-01 report with ready: true in eval/hardware/ (run gpu_probe.py)")
    return missing


def _is_ready(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("ready") is True
    except (OSError, ValueError, AttributeError):
        return False


def run_cell(cell: dict, clip: Path) -> dict:  # pragma: no cover - GPU only
    """Process one 10 s clip in chunks with local SAM 3.1 and measure it.

    The sam3 video-predictor API must be wired here once the package is installed on the
    workstation (WSL2, spec 10.1); until then this refuses rather than guessing it.
    """
    raise NotImplementedError(
        "blocked: sam3 video predictor wiring pending; verify the predictor API in the "
        "facebookresearch/sam3 README on the workstation before filling run_cell()"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="print the grid and exit")
    ap.add_argument("--clip", type=Path, help="a masked 10 s window (never raw footage)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    cells = grid()
    if args.plan:
        print(f"H-02 grid: {len(cells)} cells")
        for c in cells:
            print(
                f"  chunk {c['chunk_s']:>2} s  {c['width']} px  {c['fps']:>2} fps  "
                f"overlap {c['overlap_s']} s"
            )
        return 0

    missing = missing_requirements()
    if missing:
        print("blocked: H-02 needs " + "; ".join(missing), file=sys.stderr)
        print("Fallback per spec 10.2: API SAM (costed in section 11).", file=sys.stderr)
        return 2
    if args.clip is None:
        print("blocked: pass --clip with a masked 10 s window", file=sys.stderr)
        return 2
    results = []
    for c in cells:  # pragma: no cover - GPU only
        try:
            results.append({**c, **run_cell(c, args.clip)})
        except NotImplementedError as err:
            print(str(err), file=sys.stderr)
            return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)  # pragma: no cover
    args.out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
