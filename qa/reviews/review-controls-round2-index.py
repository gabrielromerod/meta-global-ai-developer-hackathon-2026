from pathlib import Path

from PIL import Image, ImageDraw

root = Path("qa/screens/5f6f8893")
indexes = root / "inspection"
indexes.mkdir(exist_ok=True)
for viewport in root.iterdir():
    if not viewport.is_dir() or viewport == indexes:
        continue
    files = sorted(viewport.glob("*.png"))
    main = [p for p in files if "-hover-" not in p.name and "-tab-hover-" not in p.name]
    hover = [p for p in files if p not in main]
    for label, group in [("main", main), ("hover", hover)]:
        for offset in range(0, len(group), 24):
            batch = group[offset : offset + 24]
            target = indexes / f"review-controls-{viewport.name}-{label}-{offset // 24 + 1:02}.png"
            tile_w, tile_h = 450, 315
            sheet = Image.new("RGB", (tile_w * 4, tile_h * ((len(batch) + 3) // 4)), "#d7d7d7")
            draw = ImageDraw.Draw(sheet)
            for i, p in enumerate(batch):
                image = Image.open(p).convert("RGB")
                image.thumbnail((tile_w - 8, tile_h - 42))
                x = (i % 4) * tile_w
                y = (i // 4) * tile_h
                sheet.paste(image, (x, y + 40))
                text = p.name.replace("review-controls-", "")
                draw.text((x + 3, y + 3), text[:54], fill="black")
                if len(text) > 54:
                    draw.text((x + 3, y + 17), text[54:], fill="black")
            sheet.save(target, compress_level=1)
print(len(list(indexes.glob("*.png"))))
