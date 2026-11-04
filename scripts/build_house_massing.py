"""Build the private, simplified house massing from LiDAR segments and an operator recipe.

Usage (inputs and outputs stay under data/, which is gitignored):

    uv run python scripts/build_house_massing.py data/spatial/massing_recipe.json

The recipe lists the scan segments with their alignment to the reference segment, the front
door and front-wall angle that define the house frame, and the rectangles an operator traced on
the orthophoto (in house-frame metres). Heights and surface kinds left out of the recipe are
measured from the scan. Writes ``massing.json`` plus a QA plan image next to the recipe.
See docs/runbooks/house-massing.md for the method.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vigil.settings import REPO_ROOT
from vigil.spatial import massing


def load_points(recipe: dict, per_m2: float):
    segments = recipe["segments"]
    reference = None
    points, colors = [], []
    for i, seg in enumerate(segments):
        path = REPO_ROOT / seg["path"]
        p, c = massing.sample_glb_points(path, per_m2=per_m2, seed=i)
        base = massing.ground_level(p, seg["base_region"])
        if reference is None:
            reference = base
        aligned = massing.align_segment(p, {**seg, "base_y": base, "reference_base_y": reference})
        print(f"{seg['path']}: {len(p):,} samples, base {base:+.3f} m")
        points.append(aligned)
        colors.append(c)
    frame = recipe["frame"]
    to_house = massing.house_frame(frame["door"], frame["front_angle_deg"], reference)
    return to_house(np.concatenate(points)), np.concatenate(colors)


def plan_image(doc: dict, points, colors, out: Path, res: float = 0.05):
    """Top-down QA image: scan texels under the traced massing outlines (private)."""
    from PIL import Image, ImageDraw

    (x0, z0), (x1, z1) = doc["ground"]["min"], doc["ground"]["max"]
    w, h = int((x1 - x0) / res), int((z1 - z0) / res)
    img = np.zeros((h, w, 3), np.uint8)
    order = np.argsort(points[:, 1])
    ix = ((points[:, 0] - x0) / res).astype(int)
    iz = ((points[:, 2] - z0) / res).astype(int)
    ok = (ix >= 0) & (ix < w) & (iz >= 0) & (iz < h)
    order = order[ok[order]]
    img[iz[order], ix[order]] = colors[order]
    im = Image.fromarray(img)
    draw = ImageDraw.Draw(im)

    def px(x, z):
        return ((x - x0) / res, (z - z0) / res)

    for box in doc["site_plan"]["boxes"]:
        draw.rectangle([px(*box["min"]), px(*box["max"])], outline=(80, 160, 255), width=3)
    for s in doc["detail"]["surfaces"]:
        draw.rectangle([px(*s["min"]), px(*s["max"])], outline=(250, 200, 60), width=1)
    for f in doc["detail"]["fences"]:
        draw.line([px(*f["from"]), px(*f["to"])], fill=(255, 90, 90), width=3)
    for cam in doc["camera_layout"].values():
        x, _, z = cam["position"]
        cx, cz = px(x, z)
        draw.ellipse([cx - 6, cz - 6, cx + 6, cz + 6], fill=(255, 255, 255))
    im.save(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("recipe", type=Path)
    parser.add_argument("--per-m2", type=float, default=1500)
    parser.add_argument("--no-image", action="store_true")
    args = parser.parse_args()
    recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
    points, colors = load_points(recipe, args.per_m2)
    doc = massing.build_massing(recipe, points, colors)
    out = args.recipe.parent / "massing.json"
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    for b in doc["site_plan"]["boxes"]:
        print(f"  building {b['id']}: eave {b['h']} m")
    for f in doc["detail"]["fences"]:
        print(f"  fence {f['id']}: {f['h']} m ({'observed' if f['observed'] else 'assumed'})")
    print("  surfaces:", ", ".join(f"{s['id']}={s['kind']}" for s in doc["detail"]["surfaces"]))
    if not args.no_image:
        plan_image(doc, points, colors, args.recipe.parent / "massing_plan.png")
        print(f"wrote {args.recipe.parent / 'massing_plan.png'} (private QA image)")


if __name__ == "__main__":
    main()
