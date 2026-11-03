---
name: privacy-gate
description: Use when about to run vigil export, change anything under demo/ (including the demo/voice/ audio fixtures), commit or upload images, video, audio, GLB/PLY scans or stills, publish the sandbox or video, or when a diff touches media, fixtures from real cameras, scan exports or config privacy polygons.
---

# Privacy gate

## Overview

Nothing from the house leaves the edge machine unless it is masked, silent, metadata-free
and reviewed by a human. Automated scans are necessary, not sufficient. A failed check
blocks the export or commit; it is fixed, never waived.

## Automated checks (all must pass)

```bash
uv run python scripts/privacy_scan.py demo      # NFR-001/002: 0 unmasked pixels in polygons, 0 audio streams
bash scripts/metadata_scan.sh demo              # NFR-032: exiftool, 0 GPS/device metadata
gitleaks git --redact --verbose --exit-code 1 . # NFR-014/031: no secrets (if gitleaks is installed)
git status --porcelain                          # nothing under data/, no .env, no stray media
```

- Shortcut: `make scan` runs the first two. `pwsh scripts/tasks.ps1 scan` runs only the
  privacy scan, so on Windows run the metadata scan separately (needs Git Bash and exiftool).
- If exiftool or gitleaks is not installed, say so in your report; CI still runs gitleaks.
  Do not mark the gate passed on a skipped check.
- Run the scans on any other directory you are about to commit media from, not only `demo/`.
- **Audio (NFR-002):** the only audio files allowed anywhere in the repo are the consented
  voice-rule fixtures in `demo/voice/`, each listed by SHA-256 in `config/audio_fixtures.json`.
  CI fails on any tracked `.wav`, `.mp3`, `.m4a`, `.ogg` or `.webm` not on that list. Before
  adding a fixture: consenting adult team member, 16 kHz mono 16-bit PCM, under 30 s and 2 MB,
  no other voices or identifying background, hash and consent note recorded in the list.

## Manual frame review (every published frame set)

Open every clip and still that will be published and check:

- [ ] No neighbours, neighbouring houses or windows outside the privacy polygons
- [ ] No vehicle plates (demo cars carry paper "VIGIL-01" signs)
- [ ] No house number, street sign, mailbox name or recognisable landmark
- [ ] No street-facing frame that reveals the address
- [ ] Only consenting team adults appear; no children, no passers-by
- [ ] No audio track; no on-screen timestamp overlay that leaks location
- [ ] GLB/scan: no GPS, no device serial, textures do not show the address

Record the review (date, reviewer, files) in your report; the owner keeps consent records
privately, never in the repo.

## Never commit

- `data/` (raw segments, scans, checkerboard frames): gitignored and stays gitignored
- `.env`, credentials, camera hosts or IPs, RTSP URLs with passwords
- Unmasked or audio-bearing video, raw LiDAR exports, GPS-tagged images
- Real footage in `tests/`; tests generate synthetic media at runtime

## When a check fails

1. Stop the export/commit. Do not "fix later".
2. Fix the source: add or extend the polygon in `config/cameras.yaml`, re-run the masking
   (`vigil/ingest/privacy.py`), strip metadata, or drop the frame.
3. Re-run every check above from the start.
4. If something unsafe already reached a commit, tell the owner immediately; history
   rewriting is the owner's decision.

## Red flags

- "It's only a test frame", "the polygon is close enough", "CI will catch it".
- Committing with `git add -A` while `demo/` or media changed.
- Skipping manual review because the automated scan passed.
