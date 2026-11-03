"""Build inspection indexes over the exact independently captured state PNGs."""

import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path("qa/screens/c965bedf")


def main():
    rows = json.loads((ROOT / "final-b-matrix.json").read_text(encoding="utf-8"))["results"]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["case"], row["theme"])].append(row)
    out = ROOT / "inspection-final-b"
    out.mkdir(exist_ok=True)
    font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 13)
    count = 0
    for (case, theme), group in groups.items():
        expected = (len(group) + 59) // 60
        if (out / f"final-b-summary-{case}-{theme}.png").exists() and all(
            (out / f"final-b-index-{case}-{theme}-{i:02d}.png").exists()
            for i in range(1, expected + 1)
        ):
            continue
        for part in range(0, len(group), 60):
            chunk = group[part : part + 60]
            sheet = Image.new("RGB", (1500, 1140), "#26303c")
            draw = ImageDraw.Draw(sheet)
            for index, row in enumerate(chunk):
                picture = Image.open(ROOT / row["file"]).convert("RGB")
                picture.thumbnail((294, 165))
                x, y = (index % 5) * 300, (index // 5) * 95
                # Tall phone full-page captures have a separate readable summary below.
                picture.thumbnail((294, 74))
                sheet.paste(picture, (x, y + 19))
                draw.text((x + 3, y + 2), row["state"][:40], font=font, fill="white")
            sheet.save(out / f"final-b-index-{case}-{theme}-{part // 60 + 1:02d}.png")
            count += 1
        names = {
            "home",
            "attention",
            "clips",
            "media",
            "messages",
            "rules",
            "benchmark",
            "settings",
            "settings-Privacy",
            "settings-Owner-controls",
            "visit-c",
            "explicit-gap",
            "floating-messages-draft",
            "notifications",
            "time-range",
            "voice-dialog-not-recording",
            "voice-draft-2",
            "share-clip-dialog",
        }
        selected = [row for row in group if row["state"] in names]
        sheet = Image.new("RGB", (1500, 1400), "#26303c")
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(selected):
            picture = Image.open(ROOT / row["file"]).convert("RGB")
            if picture.height > picture.width * 3:
                picture = picture.crop((0, 0, picture.width, min(picture.height, 1000)))
            picture.thumbnail((490, 205))
            x, y = (index % 3) * 500, (index // 3) * 230
            sheet.paste(picture, (x, y + 22))
            draw.text((x + 3, y + 3), row["state"], font=font, fill="white")
        sheet.save(out / f"final-b-summary-{case}-{theme}.png")
    print(f"{len(groups)} case/theme groups, {count} complete state indexes")


if __name__ == "__main__":
    main()
