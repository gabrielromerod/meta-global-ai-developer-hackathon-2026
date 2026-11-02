"""Runtime settings from environment variables (and .env on the edge machine).

Secrets (MODEL_API_KEY, Reolink credentials) are read here and never logged (NFR-014, NFR-031).
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from vigil.models import SamBackend, TriageBackend

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VIGIL_", extra="ignore")

    mode: str = Field(default="dev", description="dev | sandbox | edge")
    model_api_key: SecretStr | None = Field(default=None, validation_alias="MODEL_API_KEY")
    meta_base_url: str = "https://api.meta.ai/v1"

    sam_backend: SamBackend = "api"
    sam_url: str | None = None
    """Remote sam-worker URL when sam_backend == "remote" (DGX Spark phase D-1)."""
    triage_backend: TriageBackend = "spark"
    glimmer_url: str = "http://127.0.0.1:8080"

    # Budget guard (spec 11.6, FR-043)
    total_cap_usd: float = 140.0
    daily_cap_usd: float = 10.0
    credit_window_end: datetime | None = None
    allow_paid: bool = False

    # Sandbox guards (NFR-015)
    live_rate_per_min: int = 10
    max_audio_s: int = 30
    max_audio_bytes: int = 2 * 1024 * 1024
    max_json_bytes: int = 64 * 1024

    config_path: Path = REPO_ROOT / "config" / "cameras.yaml"
    data_dir: Path = REPO_ROOT / "data"
    demo_dir: Path = REPO_ROOT / "demo"
    bundle_dir: Path | None = None
    """Bundle served by the sandbox; None: demo/ if it has a manifest, else demo/synthetic/."""
    meta_cache_only: bool = False
    """Sandbox cached-by-default: the client answers from cache and never sends (FR-026)."""
    cache_dir: Path = REPO_ROOT / ".vigil-cache"
    db_path: Path = REPO_ROOT / "vigil.db"
    ffmpeg: str | None = None
    ffprobe: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _winget_link(name: str) -> str | None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    candidate = Path(local) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
    return str(candidate) if candidate.exists() else None


def find_binary(name: str, override: str | None = None) -> str:
    """Resolve ffmpeg/ffprobe: explicit override, then PATH, then the WinGet Links folder."""
    for candidate in (override, shutil.which(name), _winget_link(name)):
        if candidate:
            return candidate
    raise FileNotFoundError(f"{name} not found; install ffmpeg or set VIGIL_{name.upper()}")


def ffmpeg_bin() -> str:
    return find_binary("ffmpeg", get_settings().ffmpeg)


def ffprobe_bin() -> str:
    return find_binary("ffprobe", get_settings().ffprobe)
