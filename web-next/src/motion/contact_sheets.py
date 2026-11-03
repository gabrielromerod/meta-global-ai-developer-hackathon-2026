"""Index generated UI screenshots for manual layout review; originals remain unchanged."""

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--rows", type=int, default=4)
    parser.add_argument("--key-states", action="store_true")
    args = parser.parse_args()
    paths = sorted(p for p in args.root.rglob("*.png") if "inspection" not in p.name)
    if args.key_states:
        pattern = re.compile(
            r"(?:-000-home|-house-view-(?:0|7|13)|-visit-panel|-observations-open|"
            r"-route-attention|-route-messages|-popup-shared-draft|-actual-local-send|"
            r"-ask-unavailable|-keyboard-focus|-notifications|-reduced-actual-style|"
            r"-Top-down)\.png$"
        )
        paths = [p for p in paths if pattern.search(p.name) or "motion-adaptive" in p.name]
    columns, rows = args.columns, args.rows
    width, height, caption = 560, 420, 28
    for offset in range(0, len(paths), columns * rows):
        batch = paths[offset : offset + columns * rows]
        sheet = Image.new("RGB", (width * columns, (height + caption) * rows), "#e8edf4")
        draw = ImageDraw.Draw(sheet)
        for index, path in enumerate(batch):
            image = Image.open(path).convert("RGB")
            image.thumbnail((width, height))
            x, y = index % columns * width, index // columns * (height + caption)
            sheet.paste(image, (x, y))
            draw.text((x + 4, y + height + 4), path.name[:78], fill="#162234")
        kind = "key-" if args.key_states else ""
        target = args.root / f"motion-inspection-{kind}{offset // (columns * rows):03d}.png"
        sheet.save(target)
        print(target)


if __name__ == "__main__":
    main()
