#!/usr/bin/env bash
# Local demo/recording launch: edge mode with a fresh owner token for this run, handed only to a
# browser on this machine (VIGIL_OWNER_AUTOLOGIN), masked clips only, opt-in face profiles, and
# only this home's recordings (VIGIL_REAL_ONLY: nothing from the demo bundle).
# The token lives in this process's environment only; .env is not touched.
set -euo pipefail
cd "$(dirname "$0")/.."
export VIGIL_MODE=edge
export VIGIL_OWNER_TOKEN="${VIGIL_OWNER_TOKEN:-$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')}"
export VIGIL_OWNER_AUTOLOGIN=1
export VIGIL_REAL_ONLY=1
export VIGIL_MASKED_VIEW=1
export VIGIL_FACE_TEMPLATES=1
exec uv run vigil serve --host 127.0.0.1 --port "${PORT:-8000}"
