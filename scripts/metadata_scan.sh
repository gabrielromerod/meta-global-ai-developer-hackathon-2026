#!/usr/bin/env bash
# Same fail-closed scanner on Windows, Linux and CI. ExifTool is mandatory.
set -eu
exec uv run python "$(dirname "$0")/metadata_scan.py" "${1:-demo}"
