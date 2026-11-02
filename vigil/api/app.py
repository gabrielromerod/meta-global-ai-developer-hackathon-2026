"""FastAPI application factory (spec 5.2, 5.11, 9.6).

`uvicorn vigil.api.app:create_app --factory` serves the API and the static web app over a
demo bundle. In the hosted sandbox (VIGIL_MODE=sandbox) everything is cached by default,
LAN-only routes and the calibration page are off, and live calls need a server-side key and
pass the guards. The key is never sent to the browser (NFR-014).
"""

from __future__ import annotations

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
from vigil.api.routes import Runtime, router
from vigil.models import Config
from vigil.settings import REPO_ROOT, Settings, get_settings
from vigil.store.export import MANIFEST, load_bundle

WEB_DIR = REPO_ROOT / "web"
LAN_ONLY_PAGES = ("/calibrate",)


def resolve_bundle_dir(settings: Settings) -> Path:
    """An exported bundle in demo/ wins; otherwise the committed synthetic bundle."""
    demo = Path(settings.demo_dir)
    if (demo / MANIFEST).exists():
        return demo
    return demo / "synthetic"


def _load_config(path: Path) -> Config | None:
    try:
        return Config.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def create_app(
    settings: Settings | None = None,
    *,
    bundle_dir: Path | None = None,
    live_backend: Any = None,
    clock: Callable[[], float] = time.time,
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
    app.state.live_hub = hub
    app.state.live_backend = live_backend or MetaLiveBackend(
        settings, stills if stills.exists() else None
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

    app.include_router(router())
    app.include_router(live_router())
    media = bundle_root / "media"
    if media.exists():
        app.mount("/media", StaticFiles(directory=media), name="media")
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
