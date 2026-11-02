#!/usr/bin/env bash
# Location and device metadata scan (NFR-032): no GPS or device metadata in committed scans,
# stills and clips.
#
# Usage: scripts/metadata_scan.sh [ROOT=demo]
#   EXIFTOOL=/path/to/exiftool        exiftool binary (default: exiftool on PATH)
#   METADATA_SCAN_ALLOW_DEVICE=1      report device tags (Make, Model, serials) as warnings
#
# Exit codes: 0 clean, missing ROOT, or exiftool absent (prints SKIPPED; CI installs it);
#             1 GPS tags found, or device tags found (unless allowed).
set -u

ROOT="${1:-demo}"
EXIFTOOL="${EXIFTOOL:-exiftool}"

if [ ! -e "$ROOT" ]; then
  echo "metadata scan: $ROOT does not exist; nothing to scan. PASS"
  exit 0
fi

if ! command -v "$EXIFTOOL" >/dev/null 2>&1; then
  echo "metadata scan: exiftool not found ($EXIFTOOL); install it or set EXIFTOOL. SKIPPED"
  exit 0
fi

# -ee also reads GPS embedded in video tracks; -m/-q -q silence minor warnings.
# exiftool exits 2 when no file passes -if, so its status is ignored and the output decides.
GPS_HITS="$("$EXIFTOOL" -r -m -q -q -ee -api LargeFileSupport=1 \
  -if '$GPSLatitude or $GPSLongitude or $GPSPosition or $GPSCoordinates or $GPSAltitude' \
  -p '$Directory/$FileName' "$ROOT" 2>/dev/null || true)"

DEVICE_HITS="$("$EXIFTOOL" -r -m -q -q -api LargeFileSupport=1 \
  -if '$Make or $Model or $SerialNumber or $InternalSerialNumber or $BodySerialNumber or $LensSerialNumber or $HostComputer or $OwnerName' \
  -p '$Directory/$FileName: $Make $Model' "$ROOT" 2>/dev/null || true)"

status=0
if [ -n "$GPS_HITS" ]; then
  echo "metadata scan: GPS metadata found in:"
  printf '%s\n' "$GPS_HITS" | sed 's/^/  /'
  status=1
fi
if [ -n "$DEVICE_HITS" ]; then
  echo "metadata scan: device metadata found in:"
  printf '%s\n' "$DEVICE_HITS" | sed 's/^/  /'
  if [ "${METADATA_SCAN_ALLOW_DEVICE:-0}" != "1" ]; then
    status=1
  fi
fi

if [ "$status" -eq 0 ]; then
  echo "metadata scan: no GPS or device metadata under $ROOT. PASS"
else
  echo "metadata scan: FAIL (strip with: exiftool -all= -overwrite_original <file>)"
fi
exit "$status"
