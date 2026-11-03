"""Create labelled QA indexes; original Playwright PNGs remain unchanged."""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

root = Path(sys.argv[1])
out = root.parent / "inspection"
out.mkdir(parents=True, exist_ok=True)
font_path = Path("C:/Windows/Fonts/segoeui.ttf")
font = ImageFont.truetype(str(font_path), 14) if font_path.exists() else ImageFont.load_default()
for directory in sorted(p for p in root.iterdir() if p.is_dir()):
    for theme in ("dark", "light"):
        files = sorted(directory.glob(f"controls-{theme}-*.png"))
        for offset in range(0, len(files), 15):
            batch = files[offset : offset + 15]
            sheet = Image.new("RGB", (1920, math.ceil(len(batch) / 3) * 400), "#e6e9ee")
            draw = ImageDraw.Draw(sheet)
            for index, path in enumerate(batch):
                with Image.open(path) as original:
                    frame = original.convert("RGB")
                    frame.thumbnail((630, 360))
                    x, y = (index % 3) * 640, (index // 3) * 400
                    sheet.paste(frame, (x, y))
                    draw.text((x + 4, y + 363), path.stem, font=font, fill="#162234")
            sheet.save(out / f"{directory.name}-{theme}-{offset // 15:02d}.png")
print(f"QA contact indexes: {len(list(out.glob('*.png')))}")
