"""Build task-only visual QA indexes without changing original screenshots."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

root = Path(sys.argv[1])
for viewport in sorted(path for path in root.iterdir() if path.is_dir()):
    for theme in ("dark", "light"):
        images = sorted(
            path
            for path in viewport.glob(f"home-{theme}-*.png")
            if not path.stem.endswith("-contact")
        )
        if not images:
            continue
        thumb_width, thumb_height, label_height, columns = 360, 240, 24, 4
        sheet = Image.new(
            "RGB",
            (
                columns * thumb_width,
                ((len(images) + columns - 1) // columns) * (thumb_height + label_height),
            ),
            "#f2f5f9",
        )
        draw = ImageDraw.Draw(sheet)
        for index, image_path in enumerate(images):
            image = Image.open(image_path).convert("RGB")
            image.thumbnail((thumb_width, thumb_height))
            x = (index % columns) * thumb_width
            y = (index // columns) * (thumb_height + label_height)
            sheet.paste(image, (x, y + label_height))
            draw.text(
                (x + 4, y + 4), image_path.stem.removeprefix(f"home-{theme}-"), fill="#162234"
            )
        sheet.save(viewport / f"home-{theme}-contact.png")
