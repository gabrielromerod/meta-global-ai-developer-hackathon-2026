"""Build contact indexes of current independent screenshot evidence."""

import json
from pathlib import Path

from PIL import Image, ImageDraw

root = Path("qa/screens/7c2ea321")
output = root / "inspection"
output.mkdir(exist_ok=True)
for viewport in root.iterdir():
    if not viewport.is_dir() or viewport == output:
        continue
    for route in ["clips", "media"]:
        for theme in ["dark", "light"]:
            files = sorted(viewport.glob(f"review-clips-{route}-{theme}-*.png"))
            if not files:
                continue
            cols, cw, ch = 6, 400, 290
            sheet = Image.new("RGB", (cols * cw, ((len(files) + cols - 1) // cols) * ch), "#ccd3df")
            draw = ImageDraw.Draw(sheet)
            for i, file in enumerate(files):
                with Image.open(file) as src:
                    img = src.convert("RGB")
                    img.thumbnail((cw - 8, ch - 32))
                    x, y = i % cols * cw, i // cols * ch
                    sheet.paste(img, (x, y))
                    draw.text(
                        (x + 2, y + ch - 30), file.name.replace("review-clips-", ""), fill="#091529"
                    )
            sheet.save(
                output / f"review-clips-{viewport.name}-{route}-{theme}.png", compress_level=1
            )
print(json.dumps({"sheets": len(list(output.glob("*.png")))}))
