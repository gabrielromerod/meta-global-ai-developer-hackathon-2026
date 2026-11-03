"""Offline handover diagnostics. Never authenticates, probes cameras, or changes paid flags."""

import ipaddress
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from dotenv import dotenv_values

from vigil.ingest.config import load_config, privacy_polygons
from vigil.ingest.review import require_privacy_review
from vigil.meta.client import CallLedger
from vigil.settings import Settings, ffmpeg_bin, ffprobe_bin


@dataclass(frozen=True)
class Check:
    name: str
    ready: bool
    detail: str


def check_readiness(
    settings: Settings, env_file: Path, *, now: datetime | None = None
) -> list[Check]:
    now = now or datetime.now(UTC)
    values = dotenv_values(env_file) if env_file.exists() else {}
    checks = []
    key = settings.model_api_key.get_secret_value().strip() if settings.model_api_key else ""
    key_present = bool(key) and not key.lower().startswith(("invalid", "changeme", "your_"))
    checks.append(
        Check(
            "MODEL_API_KEY",
            key_present,
            "present; not authenticated"
            if key_present
            else "provide the owner's key; QA placeholders do not count",
        )
    )
    end = settings.credit_window_end
    window_valid = end is not None and end.utcoffset() is not None
    if window_valid and end <= now and not settings.allow_paid:
        window_valid = False
    checks.append(
        Check(
            "VIGIL_CREDIT_WINDOW_END",
            window_valid,
            "configured with timezone; billing guard remains authoritative"
            if window_valid
            else "set the confirmed credit end with timezone; expired credit is not live-ready",
        )
    )
    judging = settings.judging_end
    checks.append(
        Check(
            "VIGIL_JUDGING_END",
            judging is not None and judging.utcoffset() is not None and judging > now,
            "configured deadline (default is permitted)",
        )
    )
    ledger_ok = False
    if settings.ledger_path is not None:
        ledger = CallLedger(settings.ledger_path)
        ledger_ok = ledger.durable
        ledger.close()
    checks.append(
        Check(
            "VIGIL_LEDGER_PATH",
            ledger_ok,
            "durable SQLite ledger" if ledger_ok else "configure a writable durable ledger path",
        )
    )
    try:
        installed = version("reolink-aio")
    except PackageNotFoundError:
        installed = None
    checks.append(
        Check(
            "reolink-aio",
            installed == "0.22.0",
            f"installed {installed}" if installed else "install the pinned reolink extra",
        )
    )
    for name, resolver in (("ffmpeg", ffmpeg_bin), ("ffprobe", ffprobe_bin)):
        try:
            binary = resolver(settings)
            result = subprocess.run([binary, "-version"], capture_output=True, timeout=10)
            ready = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ready = False
        checks.append(
            Check(
                name, ready, "executable found" if ready else "install ffmpeg or set its override"
            )
        )
    exiftool = os.environ.get("EXIFTOOL") or shutil.which("exiftool")
    try:
        ready = (
            bool(exiftool)
            and subprocess.run(
                [exiftool, "-ver"], capture_output=True, timeout=10, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        ready = False
    checks.append(
        Check(
            "exiftool",
            ready,
            "executable found; metadata scans are mandatory"
            if ready
            else "install exiftool; metadata scan fails closed",
        )
    )
    try:
        cfg = load_config(settings.config_path)
    except ValueError:
        checks.append(Check("camera_config", False, "missing or invalid cameras.yaml"))
    else:
        for camera in cfg.cameras:
            try:
                polygons = privacy_polygons(cfg, camera.id, settings.config_path.parent / "privacy")
                private = bool(polygons) or camera.privacy_none_needed
                require_privacy_review(camera, polygons)
            except (ValueError, OSError, ZeroDivisionError, TypeError):
                private = False
            checks.append(
                Check(
                    f"privacy:{camera.id}",
                    private,
                    (
                        "exact still and polygons reviewed"
                        if camera.evidence_kind == "real"
                        else "FIXTURE declaration"
                    )
                    if private
                    else "owner privacy review of a real still and exact masks is required",
                )
            )
            checks.append(Check(f"power:{camera.id}", True, camera.power_profile))
            if camera.power_profile in {"battery_wifi", "import"}:
                checks.append(
                    Check(
                        f"hub:{camera.id}",
                        camera.hub_present is not None,
                        "Home Hub event access; no continuous stream"
                        if camera.hub_present
                        else "Imported clips; no camera stream"
                        if camera.hub_present is False
                        else "Hub presence unconfirmed; use import mode",
                    )
                )
            offset = camera.clock_offset_s
            clock_ready = camera.evidence_kind == "fixture" or (
                offset is not None and math.isfinite(offset) and abs(offset) <= 2
            )
            checks.append(
                Check(
                    f"clock:{camera.id}",
                    clock_ready,
                    "FIXTURE; not a hardware clock measurement"
                    if camera.evidence_kind == "fixture"
                    else "unmeasured; cross-camera links are not accepted"
                    if offset is None
                    else "drift above 2 seconds; resync before linking"
                    if not clock_ready
                    else "measured drift within 2 seconds",
                )
            )
            host_env = camera.source.host_env if camera.source else None
            imported = camera.power_profile == "import" or (
                camera.power_profile == "battery_wifi" and camera.hub_present is not True
            )
            host = values.get(host_env, "") if host_env else ""
            try:
                ipaddress.ip_address(host or "")
                host_valid = True
            except ValueError:
                host_valid = False
            checks.append(
                Check(
                    host_env or f"host:{camera.id}",
                    host_valid or imported,
                    "Imported clips; camera host is not required"
                    if imported
                    else "IP present in .env (not probed)"
                    if host_valid
                    else f"set this camera IP in {env_file.name}; values are never printed",
                )
            )
    for name in ("REOLINK_USER", "REOLINK_PASSWORD"):
        present = bool(values.get(name) or os.environ.get(name))
        checks.append(
            Check(
                name,
                present,
                "configured (not authenticated)"
                if present
                else "set this credential; values are never printed",
            )
        )
    checks.append(
        Check(
            "VIGIL_MODE",
            settings.mode == "edge" and not settings.meta_cache_only,
            "edge mode for home sessions; QA sandbox/cache-only is intentionally not live-ready",
        )
    )
    checks.append(
        Check(
            "VIGIL_OWNER_TOKEN",
            bool(settings.owner_token and settings.owner_token.get_secret_value()),
            "required for the home owner controls; value is never printed",
        )
    )
    return checks
