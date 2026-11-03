#!/usr/bin/env python
"""Privacy scan over every video and image under a directory (NFR-001, NFR-002, FR-003).

Usage::

    uv run python scripts/privacy_scan.py [ROOT=demo] [--config config/cameras.yaml]
        [--privacy-dir config/privacy] [--allow-unmapped] [--quiet]

For every media file it decodes every frame and requires 0 in all channels for every pixel
inside the camera's privacy polygons (``cameras.yaml`` ``privacy`` plus
``config/privacy/<camera_id>.json``), rescaled from the camera frame (``width`` x ``height``)
to the file's resolution, and ffprobe to find no audio stream.

Mapping a file to a camera (path convention):

1. the deepest directory under ROOT whose name is a camera id, e.g.
   ``demo/<scenario>/<camera_id>/w000.mp4``; otherwise
2. a file name equal to a camera id or starting with ``<camera_id>_``, ``<camera_id>-`` or
   ``<camera_id>.``, e.g. ``demo/<scenario>/side_left_w000.mp4`` (longest id wins).

A media file that maps to no camera cannot be verified and fails the scan unless
``--allow-unmapped`` is given (then only its audio is checked).

Exit codes: 0 clean (including a missing or media-free ROOT), 1 any violation,
2 configuration error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from vigil.ingest.config import ConfigError, camera_for, load_config, privacy_polygons  # noqa: E402
from vigil.ingest.media import IMAGE_EXTS, VIDEO_EXTS  # noqa: E402
from vigil.ingest.privacy import PrivacyReport, scan_media  # noqa: E402
from vigil.models import Config  # noqa: E402

MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS


def scan_tree(
    root: Path,
    cfg: Config,
    privacy_dir: Path | None,
    allow_unmapped: bool = False,
    out=print,
) -> tuple[int, int, int]:
    """Scan ``root``; returns (files, frames, failures)."""
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_EXTS)
    ids = [c.id for c in cfg.cameras]
    n_frames = 0
    failures = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        cam_id = camera_for(path, root, ids)
        if cam_id is None:
            rep = scan_media(path, [])
            n_frames += rep.frames
            reasons = list(rep.reasons)
            if not allow_unmapped:
                reasons.insert(0, "no camera for this path (see the path convention)")
            if reasons:
                failures += 1
                out(f"FAIL {rel}: {'; '.join(reasons)}")
            else:
                out(f"WARN {rel}: no camera for this path; audio checked only")
            continue
        cam = cfg.camera(cam_id)
        polys = privacy_polygons(cfg, cam_id, privacy_dir)
        rep: PrivacyReport = scan_media(path, polys, ref_size=(cam.width, cam.height))
        n_frames += rep.frames
        if rep.ok:
            out(f"ok   {rel} [{cam_id}] {rep.frames} frame(s), {len(polys)} polygon(s)")
        else:
            failures += 1
            out(f"FAIL {rel} [{cam_id}]: {'; '.join(rep.reasons)}")
    return len(files), n_frames, failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", nargs="?", default=str(REPO_ROOT / "demo"), type=Path)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "cameras.yaml")
    ap.add_argument("--privacy-dir", type=Path, default=None)
    ap.add_argument("--allow-unmapped", action="store_true")
    ap.add_argument(
        "--ui-manifest", type=Path, help="scan only named reviewed static UI PNGs; never footage"
    )
    ap.add_argument("--quiet", action="store_true", help="print failures and the summary only")
    args = ap.parse_args(argv)

    root: Path = args.root
    if args.ui_manifest:
        from scripts.ui_evidence import validate_manifest

        count, failures = validate_manifest(root, args.ui_manifest)
        for failure in failures:
            print(f"FAIL {failure}")
        print(
            f"UI provenance + decode/audio + metadata: {count} named PNGs; {len(failures)} failed"
        )
        return int(bool(failures))
    if not root.exists():
        print(f"privacy scan: {root} does not exist; 0 media files scanned. PASS")
        return 0
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"privacy scan: config error: {exc}", file=sys.stderr)
        return 2
    privacy_dir = args.privacy_dir or args.config.parent / "privacy"

    def out(line: str) -> None:
        if not args.quiet or not line.startswith("ok"):
            print(line)

    try:
        files, frames, failures = scan_tree(root, cfg, privacy_dir, args.allow_unmapped, out)
    except ConfigError as exc:
        print(f"privacy scan: config error: {exc}", file=sys.stderr)
        return 2
    verdict = "PASS" if failures == 0 else "FAIL"
    print(
        f"privacy scan: {files} media files, {frames} frames under {root}: "
        f"{failures} failed. {verdict}"
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
