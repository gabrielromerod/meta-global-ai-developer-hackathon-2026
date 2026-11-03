# Vigil hosted sandbox (spec 5.11): FastAPI + static web + three.js over the demo bundle.
# Cached by default; live calls need MODEL_API_KEY passed as a runtime secret (never baked in).
# ffmpeg is not needed: the sandbox serves an exported bundle and never processes video.
#
#   docker build -t vigil-sandbox .
#   docker run --rm -p 8000:8000 -e MODEL_API_KEY=invalid vigil-sandbox
#
# Behind a reverse proxy, set FORWARDED_ALLOW_IPS to the proxy address so the per-IP rate
# limit sees real clients (uvicorn --proxy-headers only trusts listed proxies).
#
# Spend ledger: every live call is ledgered in SQLite at VIGIL_LEDGER_PATH=/data/ledger.db,
# on the /data volume, so a restart or redeploy does not reset the $25 judging cap, the $5 per
# PT day cap or the $140 credit cap. Mount a named volume to keep it across containers:
#   docker run ... -v vigil-ledger:/data vigil-sandbox
# Deploy as a single replica (one container, one uvicorn worker): spend reservations are held
# in process, so two replicas sharing one ledger could each admit the last dollar. If /data is
# not writable the sandbox still starts; the ledger stays in memory and paid live calls are
# refused (fail closed) while cached results keep working.

FROM node:24.15.0-alpine AS ui-build
WORKDIR /ui
COPY web-next/package.json web-next/package-lock.json ./
RUN npm ci
COPY web-next ./
RUN npm run build

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libimage-exiftool-perl \
 && rm -rf /var/lib/apt/lists/*

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
COPY --from=ui-build /ui/dist ./web-next/dist
COPY config ./config
COPY demo ./demo
COPY eval ./eval
RUN uv sync --locked --no-dev \
 && useradd --system --uid 10001 --no-create-home --home-dir /nonexistent vigil \
 && mkdir -p /data \
 && chown vigil /data

# The durable spend ledger lives here (single replica; see the header comment).
VOLUME ["/data"]

USER vigil

ENV VIGIL_MODE=sandbox \
    VIGIL_META_CACHE_ONLY=true \
    VIGIL_LEDGER_PATH=/data/ledger.db \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["uvicorn", "vigil.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
