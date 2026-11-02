"""E2E fixtures: the sandbox app served by uvicorn on a free port in a background thread.

The server runs as the hosted sandbox does (VIGIL_MODE=sandbox) with MODEL_API_KEY=invalid
and a live backend that behaves like an unreachable Meta API, so every live button must fall
back to the recorded result with a notice (NFR-009). No network call is ever made.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from vigil.api.app import create_app
from vigil.settings import Settings


class UnreachableBackend:
    """Every live call fails the way a down API does (connection refused)."""

    def _fail(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("api.meta.ai unreachable (E2E offline run)")

    protect = compile_rule = transcribe = rerun_story = _fail


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def server_url() -> Iterator[str]:
    external = os.environ.get("VIGIL_E2E_BASE_URL")
    if external:
        # CI (spec 12.2 step 7): run against the Docker container started with an invalid key.
        yield external.rstrip("/")
        return
    settings = Settings(mode="sandbox", MODEL_API_KEY="invalid")
    app = create_app(settings, live_backend=UnreachableBackend())
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def wait_ready(page) -> None:
    page.wait_for_function("document.body.dataset.ready === '1'", timeout=20_000)
