"""FastAPI application factory (spec 5.2, 5.11, 9.6).

`uvicorn vigil.api.app:create_app --factory` serves the API and the static web app over a
demo bundle. In the hosted sandbox (VIGIL_MODE=sandbox) everything is cached by default,
LAN-only routes and the calibration page are off, and live calls need a server-side key and
pass the guards. The key is never sent to the browser (NFR-014). Every request's Host header
must be in VIGIL_TRUSTED_HOSTS (DNS rebinding, F2); the hosted sandbox adds its public host
there. Owner endpoints also need VIGIL_OWNER_TOKEN (`vigil.api.owner.require_owner`).
"""

from __future__ import annotations

import ipaddress
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from vigil import __version__
from vigil.api.backend import MetaLiveBackend
from vigil.api.guards import Guards
from vigil.api.live import LiveHub, live_router
from vigil.api.owner import load_owner_state, owner_router
from vigil.api.routes import Runtime, router
from vigil.api.voice import voice_router
from vigil.models import Config
from vigil.settings import REPO_ROOT, Settings, get_settings
from vigil.store.export import MANIFEST, load_bundle

WEB_DIR = REPO_ROOT / "web"
NEXT_WEB_DIR = REPO_ROOT / "web-next" / "dist"
VOICE_DIR = REPO_ROOT / "demo" / "voice"
AUDIO_FIXTURES = REPO_ROOT / "config" / "audio_fixtures.json"
LAN_ONLY_PAGES = ("/calibrate",)


def resolve_bundle_dir(settings: Settings) -> Path:
    """An exported bundle in demo/ wins; otherwise the committed synthetic bundle."""
    if settings.bundle_dir is not None:
        return Path(settings.bundle_dir)
    demo = Path(settings.demo_dir)
    if (demo / MANIFEST).exists():
        return demo
    return demo / "synthetic"


def _load_config(path: Path) -> Config | None:
    try:
        return Config.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def host_allowed(host_header: str, trusted: set[str]) -> bool:
    """Host is in VIGIL_TRUSTED_HOSTS, or a private or loopback IP literal (a phone opening the
    edge box by LAN IP, FR-034). Rebinding needs a hostname, so IP literals are safe to allow."""
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host[1 : host.find("]")] if "]" in host else host
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    if not host:
        return False
    if host in trusted:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def create_app(
    settings: Settings | None = None,
    *,
    bundle_dir: Path | None = None,
    live_backend: Any = None,
    clock: Callable[[], float] = time.time,
    voice_dir: Path | None = None,
    audio_fixtures_path: Path | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    bundle_root = Path(bundle_dir) if bundle_dir is not None else resolve_bundle_dir(settings)
    bundle = load_bundle(bundle_root)
    hub = LiveHub()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        hub.close()

    app = FastAPI(
        title="Vigil",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.mode == "sandbox" else "/docs",
        redoc_url=None,
    )
    stills = bundle_root / "media" / "stills"
    app.state.settings = settings
    app.state.bundle = bundle
    app.state.config = _load_config(settings.config_path)
    app.state.guards = Guards(settings, clock=clock)
    app.state.runtime = Runtime(bundle)
    load_owner_state(settings, app.state.runtime)
    app.state.voice_dir = Path(voice_dir) if voice_dir is not None else VOICE_DIR
    app.state.audio_fixtures_path = (
        Path(audio_fixtures_path) if audio_fixtures_path is not None else AUDIO_FIXTURES
    )
    app.state.live_hub = hub
    app.state.live_backend = live_backend or MetaLiveBackend(
        settings, stills if stills.exists() else None, ledger=app.state.guards.ledger
    )
    app.state.eval_path = REPO_ROOT / "eval" / "results.json"

    @app.middleware("http")
    async def headers_and_lan_pages(request: Request, call_next: Any) -> Response:
        path = request.url.path
        if settings.mode == "sandbox" and path.startswith(LAN_ONLY_PAGES):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # Refuse a foreign Host before any route runs (DNS rebinding to the LAN box). The public
    # sandbox serves no owner or LAN route, so it answers on any hostname it is deployed under.
    if settings.mode != "sandbox":
        trusted = {h.lower() for h in settings.trusted_hosts}

        @app.middleware("http")
        async def trusted_host(request: Request, call_next: Any) -> Response:
            if not host_allowed(request.headers.get("host", ""), trusted):
                return JSONResponse({"detail": "Invalid host header"}, status_code=400)
            return await call_next(request)

    app.include_router(router())
    app.include_router(voice_router())
    app.include_router(owner_router())
    app.include_router(live_router())
    media = bundle_root / "media"
    if media.exists():
        app.mount("/media", StaticFiles(directory=media), name="media")
    if NEXT_WEB_DIR.is_dir():
        app.mount("/next", StaticFiles(directory=NEXT_WEB_DIR, html=True), name="web-next")
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
