"""Battery export ingest without a camera connection or persistent stream."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from vigil.ingest.media import VIDEO_EXTS
from vigil.ingest.panorama import cut_camera_windows
from vigil.ingest.review import require_privacy_review, require_silent_source
from vigil.models import CameraCfg


def clip_start(path: Path) -> datetime:
    sidecar = path.with_suffix(path.suffix + ".json")
    if sidecar.exists():
        at = datetime.fromisoformat(json.loads(sidecar.read_text(encoding="utf-8"))["start"])
        if at.utcoffset() is None:
            raise ValueError("import timestamp needs an explicit timezone")
        return at
    match = re.search(r"(\d{8}T\d{6}Z)", path.stem)
    if not match:
        raise ValueError(
            f"{path.name}: supply UTC timestamp in filename or .mp4.json start with timezone"
        )
    return datetime.strptime(match[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def import_clips(camera: CameraCfg, incoming: Path, destination: Path) -> dict:
    require_privacy_review(camera)
    if camera.power_profile not in {"battery_wifi", "import"}:
        raise ValueError("import mode is for exported battery-camera clips")
    if destination.exists():
        raise FileExistsError("import destination already exists; choose a new session")
    sources = sorted(
        p for p in incoming.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )
    if not sources:
        raise ValueError("No imported clips in this camera folder")
    dated = sorted((clip_start(p), p) for p in sources)
    for _, path in dated:
        require_silent_source(path)
    if len({at for at, _ in dated}) != len(dated):
        raise ValueError("imported clips have duplicate start timestamps")
    start = dated[0][0]
    windows = []
    for at, path in dated:
        windows.extend(
            cut_camera_windows(
                path, destination, camera, session_start_s=(at - start).total_seconds()
            )
        )
    payload = {
        "session_start": start.isoformat(),
        "source_label": "Imported clips",
        "source_mode": "import",
        "camera_id": camera.id,
        "source_hashes": [hashlib.sha256(p.read_bytes()).hexdigest() for _, p in dated],
        "windows": [w.model_dump(mode="json") for w in windows],
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "windows.json").write_text(
        json.dumps(payload["windows"], indent=2), encoding="utf-8"
    )
    (destination / "session.json").write_text(
        json.dumps({k: v for k, v in payload.items() if k != "windows"}, indent=2), encoding="utf-8"
    )
    return payload
