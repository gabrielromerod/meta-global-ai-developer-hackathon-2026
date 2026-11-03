"""Index the exact independently clicked navigation/notification states."""

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

root = Path("qa/screens/c965bedf")
font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 14)
for size in ["1470x870", "390x844"]:
    for theme in ["dark", "light"]:
        files = sorted(
            p
            for p in (root / size).glob(f"final-b-r2-*-{theme}-*.png")
            if re.search(r"-(nav|notification)-", p.name)
        )
        assert len(files) == 13, (size, theme, len(files))
        sheet = Image.new("RGB", (1500, 1150), "#26303c")
        draw = ImageDraw.Draw(sheet)
        for i, p in enumerate(files):
            im = Image.open(p)
            im.thumbnail((370, 245))
            x, y = (i % 4) * 375, (i // 4) * 285
            sheet.paste(im, (x, y + 25))
            draw.text((x + 3, y + 3), p.stem.replace("final-b-r2-", ""), font=font, fill="white")
        sheet.save(root / size / f"final-b-r2-actions-index-{theme}.png")
print("4 exact action indexes created")
