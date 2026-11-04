"""Owner privacy review per camera (FR-003, NFR-001): show the masks on a real still, then approve.

    uv run python scripts/privacy_review.py                      # grab stills, draw masks, report
    uv run python scripts/privacy_review.py --camera porch       # one camera
    uv run python scripts/privacy_review.py --approve porch      # owner approval, after looking

Step 1 grabs one still per always-on camera into ``data/privacy/`` (gitignored) and writes
``<camera>_review.jpg``: the full frame with the privacy polygons tinted red (what will be
masked before frames leave the machine), the zone outlines on top (green egress, amber
perimeter, blue interior yard) and the required
anti-doxxing regions outlined in red. Nothing is approved in this step.

Step 2, ``--approve``, is the owner's attestation that the review image hides neighbours,
plates, house numbers and the street. It writes ``privacy_reviewed: true``, the still's
SHA-256 and the polygon digest into config/cameras.yaml for that camera only. Editing any
polygon or zone afterwards invalidates the approval (``require_privacy_review``).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import io
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vigil.ingest.config import load_config
from vigil.ingest.review import privacy_digest, require_privacy_review
from vigil.reolink.live_alerts import alert_cameras, load_reolink_env
from vigil.settings import REPO_ROOT

OUT = REPO_ROOT / "data" / "privacy"
KIND_COLOR = {
    "egress": (60, 220, 120),
    "perimeter": (255, 190, 40),
    "interior_yard": (80, 160, 255),
}


async def grab(camera) -> bytes:
    from reolink_aio.api import Host

    from vigil.reolink.ai_events import connect_host
    from vigil.reolink.probe import PASSWORD_ENV, USER_ENV, channel_index

    host = await connect_host(
        Host,
        os.environ[camera.source.host_env],
        os.environ[USER_ENV],
        os.environ[PASSWORD_ENV],
    )
    try:
        return await asyncio.wait_for(host.get_snapshot(channel_index(camera)), 20)
    finally:
        with contextlib.suppress(Exception):  # best-effort logout
            await host.logout()


def review_image(camera, still: bytes, out: Path) -> tuple[int, int]:
    from PIL import Image, ImageDraw

    img = Image.open(io.BytesIO(still)).convert("RGB")
    native = img.size
    img = img.resize((camera.width, camera.height))
    # Show what lies under each mask: a light red tint, not a black fill, so the owner can judge.
    tint = Image.new("RGBA", img.size, (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tint)
    for poly in camera.privacy:
        tdraw.polygon([tuple(p) for p in poly], fill=(255, 40, 40, 70))
    img = Image.alpha_composite(img.convert("RGBA"), tint).convert("RGB")
    draw = ImageDraw.Draw(img)
    for name, poly in camera.zones.items():
        color = KIND_COLOR.get(camera.zone_kinds.get(name, "interior_yard"), (255, 255, 255))
        draw.polygon([tuple(p) for p in poly], outline=color, width=3)
        draw.text(tuple(poly[0]), f" {name}", fill=color)
    for name, poly in camera.privacy_regions.items():
        draw.polygon([tuple(p) for p in poly], outline=(255, 60, 60), width=2)
        draw.text((poly[0][0] + 4, poly[0][1] + 4), name, fill=(255, 60, 60))
    img.save(out, quality=85)
    return native


def set_review_fields(yaml_text: str, camera_id: str, fields: dict[str, str]) -> str:
    """Set top-level scalar fields inside one camera's block, keeping the rest of the file."""
    lines = yaml_text.splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == f"- id: {camera_id}")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("- id: ")), len(lines)
    )
    block = lines[start:end]
    for key, value in fields.items():
        pattern = re.compile(rf"^  {key}:.*$")
        hit = next((i for i, ln in enumerate(block) if pattern.match(ln)), None)
        if hit is not None:
            block[hit] = f"  {key}: {value}\n"
        else:
            anchor = next(i for i, ln in enumerate(block) if ln.startswith("  privacy_reviewed:"))
            block.insert(anchor + 1, f"  {key}: {value}\n")
    return "".join(lines[:start] + block + lines[end:])


def approve(config_path: Path, camera_id: str) -> None:
    cfg = load_config(config_path)
    camera = cfg.camera(camera_id)
    still = OUT / f"{camera_id}.jpg"
    if not still.exists():
        sys.exit(f"no still for {camera_id}: run the review step first and look at the image")
    fields = {
        "privacy_reviewed": "true",
        "privacy_still_sha256": hashlib.sha256(still.read_bytes()).hexdigest(),
        "privacy_polygons_sha256": privacy_digest(camera, camera.privacy),
    }
    config_path.write_text(
        set_review_fields(config_path.read_text(encoding="utf-8"), camera_id, fields),
        encoding="utf-8",
    )
    require_privacy_review(load_config(config_path).camera(camera_id))
    print(f"{camera_id}: approved by the owner; config/cameras.yaml updated")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "cameras.yaml")
    parser.add_argument("--camera", action="append", default=[])
    parser.add_argument("--approve", metavar="CAMERA")
    args = parser.parse_args()
    if args.approve:
        approve(args.config, args.approve)
        return

    load_reolink_env(REPO_ROOT / ".env")
    cams = alert_cameras(load_config(args.config).cameras)
    if args.camera:
        cams = [c for c in cams if c.id in args.camera]
    OUT.mkdir(parents=True, exist_ok=True)
    for camera in cams:
        try:
            still = asyncio.run(grab(camera))
        except Exception as err:
            from vigil.reolink.probe import redact

            print(f"{camera.id}: no still ({redact(err)[:100]})")
            continue
        (OUT / f"{camera.id}.jpg").write_bytes(still)
        native = review_image(camera, still, OUT / f"{camera.id}_review.jpg")
        ratio_cfg, ratio_cam = camera.width / camera.height, native[0] / native[1]
        note = (
            ""
            if abs(ratio_cfg - ratio_cam) < 0.02
            else (
                f"  WARNING: camera frame is {native[0]}x{native[1]}, config says "
                f"{camera.width}x{camera.height}; fix width/height before approving"
            )
        )
        try:
            require_privacy_review(camera)
            state = "approved"
        except ValueError as err:
            state = f"not approved ({err})"
        print(f"{camera.id}: {OUT / (camera.id + '_review.jpg')} · {state}{note}")


if __name__ == "__main__":
    main()
