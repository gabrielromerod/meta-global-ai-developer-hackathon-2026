# Vigil task runner for Linux, macOS, WSL and CI. Windows: scripts/tasks.ps1 has the same targets.
.PHONY: setup lint format test test-all e2e demo eval export scan serve

setup:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest

test-all:
	uv run pytest -m 'not live'

e2e:
	uv run playwright install chromium
	uv run pytest -m e2e tests/e2e

demo:
	uv run vigil serve --host 127.0.0.1 --port 8000

eval:
	uv run vigil eval

export:
	uv run vigil export

scan:
	uv run python scripts/privacy_scan.py demo
	bash scripts/metadata_scan.sh demo
