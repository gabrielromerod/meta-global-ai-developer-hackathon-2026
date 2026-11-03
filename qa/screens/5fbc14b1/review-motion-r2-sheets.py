from pathlib import Path

from PIL import Image, ImageDraw

root = Path("qa/screens/5fbc14b1")
for folder in sorted(p for p in root.iterdir() if p.is_dir()):
    paths = sorted(folder.glob("*.png"))
    for offset in range(0, len(paths), 16):
        sheet = Image.new("RGB", (1600, 1240), "#e8edf4")
        draw = ImageDraw.Draw(sheet)
        for i, p in enumerate(paths[offset : offset + 16]):
            im = Image.open(p).convert("RGB")
            im.thumbnail((400, 280))
            x, y = i % 4 * 400, i // 4 * 310
            sheet.paste(im, (x, y))
            draw.text((x + 2, y + 283), p.name[:62], fill="#162234")
        target = root / f"review-motion-r2-inspection-{folder.name}-{offset // 16}.png"
        sheet.save(target)
        print(target)
