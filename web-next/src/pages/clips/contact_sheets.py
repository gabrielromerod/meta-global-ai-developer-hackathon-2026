"""Read-only indexes for inspecting every captured UI state. Original PNGs stay unchanged."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

parser = argparse.ArgumentParser()
parser.add_argument("root", type=Path)
args = parser.parse_args()
output = args.root / "inspection"
output.mkdir(exist_ok=True)
for viewport in sorted(path for path in args.root.iterdir() if path.is_dir() and path != output):
    for route in ("clips", "media"):
        for theme in ("dark", "light"):
            files = sorted(viewport.glob(f"{route}-{theme}-*.png"))
            if not files:
                continue
            columns, cell_w, cell_h = 8, 320, 220
            rows = (len(files) + columns - 1) // columns
            sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#e9edf4")
            draw = ImageDraw.Draw(sheet)
            for index, file in enumerate(files):
                with Image.open(file) as source:
                    thumb = source.convert("RGB")
                    thumb.thumbnail((cell_w, cell_h - 24))
                    x, y = (index % columns) * cell_w, (index // columns) * cell_h
                    sheet.paste(thumb, (x, y))
                    draw.text((x + 2, y + cell_h - 22), file.name, fill="#162234")
            sheet.save(output / f"{viewport.name}-{route}-{theme}.png")
