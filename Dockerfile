# Vigil hosted sandbox (spec 5.11): FastAPI + static web + three.js over the demo bundle.
# Cached by default; live calls need MODEL_API_KEY passed as a runtime secret (never baked in).
# ffmpeg is not needed: the sandbox serves an exported bundle and never processes video.
#
#   docker build -t vigil-sandbox .
#   docker run --rm -p 8000:8000 -e MODEL_API_KEY=invalid vigil-sandbox
#
# Behind a reverse proxy, set FORWARDED_ALLOW_IPS to the proxy address so the per-IP rate
# limit sees real clients (uvicorn --proxy-headers only trusts listed proxies).

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first (cached layer), exactly as locked, without dev tools.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

# Application code and the demo bundle.
COPY vigil ./vigil
COPY web ./web
COPY config ./config
COPY demo ./demo
COPY eval ./eval
RUN uv sync --locked --no-dev \
 && useradd --system --uid 10001 --no-create-home --home-dir /nonexistent vigil

USER vigil

ENV VIGIL_MODE=sandbox \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["uvicorn", "vigil.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
