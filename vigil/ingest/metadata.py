"""Fail-closed NFR-032 scanner shared by Windows, shell and CI. Never prints tag values."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

EXTENSIONS = [
    "jpg",
    "jpeg",
    "png",
    "heic",
    "heif",
    "tif",
    "tiff",
    "webp",
    "gif",
    "dng",
    "mp4",
    "mov",
    "m4v",
    "mkv",
    "avi",
    "webm",
    "3gp",
    "wav",
    "m4a",
    "mp3",
    "aac",
    "glb",
    "gltf",
    "ply",
    "usdz",
    "obj",
    "las",
    "e57",
]
DEVICE_TAGS = {
    "Make",
    "Model",
    "SerialNumber",
    "InternalSerialNumber",
    "BodySerialNumber",
    "LensSerialNumber",
    "HostComputer",
    "OwnerName",
    "CameraSerialNumber",
}


def _glb_metadata(path: Path) -> list[str]:
    """Public massing GLBs have checked JSON and no image payload or external resources."""
    try:
        data = path.read_bytes()
        magic, version, total, size, kind = struct.unpack_from("<4sIIII", data)
        if (magic, version, total, kind) != (b"glTF", 2, len(data), 0x4E4F534A):
            return [f"{path.name}: invalid GLB"]
        doc = json.loads(data[20 : 20 + size])
        bad = []

        def walk(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if (
                        "GPS" in key.upper()
                        or key in DEVICE_TAGS
                        or key.lower()
                        in {
                            "latitude",
                            "longitude",
                            "location",
                            "geolocation",
                        }
                    ):
                        bad.append(key)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(doc)
        if doc.get("images") or any("uri" in b for b in doc.get("buffers", [])):
            bad.append("image or external resource requires separate review")
        return [f"{path.name}: {', '.join(sorted(set(bad)))}"] if bad else []
    except (OSError, ValueError, struct.error, TypeError):
        return [f"{path.name}: invalid GLB"]


def scan(root: Path, exiftool: str | None = None, *, files: list[Path] | None = None) -> list[str]:
    """Return violations; missing tool, unreadable media and malformed output are violations."""
    if not root.exists():
        return ["scan root does not exist"]
    binary = exiftool or os.environ.get("EXIFTOOL", "exiftool")
    args = [binary, "-json", "-G1", "-a", "-ee", "-api", "LargeFileSupport=1"]
    try:
        version = subprocess.run([binary, "-ver"], capture_output=True, timeout=15, check=False)
        if version.returncode:
            return ["exiftool version check failed"]
        media = [
            p for p in root.rglob("*") if p.is_file() and p.suffix.lower().lstrip(".") in EXTENSIONS
        ]
        if root.is_file():
            media = [root] if root.suffix.lower().lstrip(".") in EXTENSIONS else []
        if files is not None:
            if any(not p.is_file() for p in files):
                return ["named metadata scan file is missing"]
            media = list(files)
        glbs = [p for p in media if p.suffix.lower() == ".glb"]
        violations = [issue for p in glbs for issue in _glb_metadata(p)]
        media = [p for p in media if p not in glbs]
        if not media:
            return violations
        rows = []
        # Stay below Windows' command-line limit while checking every named asset.
        for offset in range(0, len(media), 64):
            batch = media[offset : offset + 64]
            result = subprocess.run(
                [*args, *(str(p) for p in batch)],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if result.returncode:
                return ["exiftool could not read every media file"]
            decoded = json.loads(result.stdout)
            if not isinstance(decoded, list) or len(decoded) < len(batch):
                return ["exiftool returned incomplete metadata"]
            rows.extend(decoded)
    except (OSError, subprocess.SubprocessError):
        return ["exiftool unavailable or scan failed"]
    except (ValueError, TypeError):
        return ["exiftool returned invalid metadata"]
    try:
        for row in rows:
            mime = row.get("File:MIMEType", "")
            if not mime.startswith(("image/", "video/", "audio/", "model/")):
                violations.append(
                    f"{Path(row.get('SourceFile', 'media')).name}: unsupported media type"
                )
            bad = sorted(
                key
                for key, value in row.items()
                if value not in (None, "")
                and (
                    "GPS" in key.upper()
                    or "LOCATION" in key.upper()
                    or key.partition(":")[0]
                    in {"IFD0", "IFD1", "ExifIFD", "InteropIFD", "MakerNotes"}
                    or key.partition(":")[0].startswith("XMP")
                    or key.rsplit(":", 1)[-1] in DEVICE_TAGS
                    or key.rsplit(":", 1)[-1] == "Error"
                )
            )
            if bad:
                violations.append(f"{Path(row.get('SourceFile', 'media')).name}: {', '.join(bad)}")
        return violations
    except (ValueError, TypeError, AttributeError):
        return ["exiftool returned invalid metadata"]


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "demo")
    violations = scan(root)
    if violations:
        print("metadata scan: FAIL")
        for violation in violations:
            print(f"  {violation}")
        return 1
    print(f"metadata scan: no GPS or device metadata under {root}. PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
