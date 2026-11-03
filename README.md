# Vigil

Vigil links home-camera events into cited visit stories. Meta models perceive and describe; code filters street activity, links observations, applies owner rules and decides the verdict. Vigil never identifies people.

Built for the Meta Global AI Developer Hackathon 2026. Current evidence is **FIXTURE**: authored responses, generated media and offline tests. No real camera or successful Meta inference has been accepted. See [readiness](docs/readiness.md), [test timing](docs/timing.md) and the [specification](docs/spec/vigil-spec.md).

## App and camera preparation

The React app uses TypeScript/Vite, Radix/shadcn patterns, Tailwind, Lucide, Motion, TanStack Query and React Three Fiber/drei. It provides Home/Attention, clips, media search, cited Messages, browser-local household notes, rules, owner settings and an honest unmeasured benchmark. Video, SAM overlays, citations and the generic house share one evidence clock; missing clips stay unavailable.

The configured home has seven Wi-Fi Reolink cameras: two front Duo Floodlights, doorbell, porch, left-passage Argus and two backyard Argus PT Solar cameras. The owner confirmed no Home Hub. Battery cameras use timestamped imports; four AC cameras support event capture and pre-roll. All cameras remain blocked until real privacy stills and exact masks are approved. Unknown transit/clock/calibration values are not guessed.

Public 3D is generic massing with no textures, address, neighbours or compass. Duo uploads/exports use reviewed anti-doxxing masks and stripped metadata. Camera audio is rejected. The phone voice-rule path is separate and keeps speech in memory.

## Windows CMD quickstart

Requires Python3.12, uv, ffmpeg/ffprobe, ExifTool and Node (CI pins24.15.0). From the repository:

```cmd
uv sync --locked
npm --prefix web-next ci
npm --prefix web-next run build
set VIGIL_MODE=sandbox
set MODEL_API_KEY=invalid
set VIGIL_META_CACHE_ONLY=true
set VIGIL_META_BASE_URL=http://127.0.0.1:9/v1
set VIGIL_DATA_DIR=data\qa-main
set VIGIL_DB_PATH=data\qa-main\vigil.db
set VIGIL_LEDGER_PATH=data\qa-main\ledger.db
set VIGIL_CACHE_DIR=data\qa-main\cache
set VIGIL_BUNDLE_DIR=demo\synthetic
uv run vigil serve --port 8000
```

Open http://127.0.0.1:8000/ for the reviewed React app. `/next/` serves the same build. Stop with Ctrl+C and repeat the last command to restart. Full setup, runtime assertions and field steps: [seven-camera runbook](docs/runbooks/seven-camera-setup.md).

Camera connections, Meta requests, paid work, ML/weight installs and go2rtc require the owner's explicit approval. Historical schedules and prior budget discussions are not fresh authorization. Models always use MetaClient's cache, budget guard and ledger. No judging/paid flag is set by this quickstart.

## Verification

```cmd
uv run ruff check .
uv run ruff format --check .
uv run pytest
npm --prefix web-next test
npm --prefix web-next run build
uv run pytest -m e2e tests/e2e -q
uv run python scripts/privacy_scan.py demo --quiet
uv run python scripts/metadata_scan.py demo
uv run python scripts/scan_ui_evidence.py
```

Post-cutover verification: **1,543 backend tests**, **134 frontend tests** and **45 browser tests** pass; the same45 browser cases also pass against the reviewed Docker sandbox. Earlier Linux full offline verification passed1,543 tests with networking disabled before the mechanical route switch. Frontend production build and Ruff pass. These are fixture results, not hardware accuracy, provider billing or physical-device certification. [Browser acceptance](tests/e2e/README.md) maps every original case to the new UI and records stronger privacy/media checks.

Committed screenshots make the repository large. For a code-only checkout, Git's blob filtering and sparse checkout can omit `qa/`; the reviewed evidence stays available in Git. Docker already excludes QA, secrets, raw data and local caches from its build context.

## Boundaries and remaining acceptance

SAM3.1 tracks masked event windows; Muse Spark supplies descriptions/allowlisted rule drafts; Muse Wonder receives only the event ledger and every sentence is validated. Optional local Glimmer/SAM/point-cloud work is explicitly incomplete and requires separate hardware/install approval. The cloud chain, GLB import, topology, privacy, capture/import/retention and doctor logic are covered offline.

Real stills/masks, camera clocks, calibration/homographies, transit walks, footage, consented voice recordings and successful approved model responses remain missing. Owner Windows/check-ins persist; the existing point/rule catalogue is explicitly server-session state. Do not treat the fixture dashboard as an operating real-home guardian. One invalid-key HTTP401 test incident and its transport/privacy remediation are documented in [readiness](docs/readiness.md).
