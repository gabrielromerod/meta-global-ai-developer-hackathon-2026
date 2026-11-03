# Seven-camera field handover (offline-prepared, not field-accepted)

No camera or Meta API was contacted during this implementation. The owner confirmed no
Home Hub. Keep `side_left`, `backyard_1`, `backyard_2` in imported-clip mode; never open
continuous streams to the three battery cameras. Four AC cameras use a low-bitrate sub
ring and bounded event-triggered main clips. Doorbell clips come from its stream.

## Sandbox QA from Windows CMD

```cmd
cd /d C:\Users\lords\.codex\worktrees\ad9e\meta-global-ai-developer-hackathon-2026
set VIGIL_MODE=sandbox
set MODEL_API_KEY=invalid
set VIGIL_META_CACHE_ONLY=true
set VIGIL_META_BASE_URL=http://127.0.0.1:9/v1
set VIGIL_DATA_DIR=data\qa-main
set VIGIL_DB_PATH=data\qa-main\vigil.db
set VIGIL_LEDGER_PATH=data\qa-main\ledger.db
set VIGIL_CACHE_DIR=data\qa-main\cache
uv run vigil serve --port 8000
```

Stop with Ctrl+C; repeat the last line to restart. Current `/` remains usable until
the final reviewed switch. React development build is served at `/next/`.
Build React with `cd web-next`, `npm ci`, `npm run build`, then restart FastAPI.

## Before field ingest

For each camera, supply a real still privately under `data/`, calibrate exact pixel
polygons and have the owner approve them. Current polygons are unreviewed templates.
Front Duo regions must cover sky/ridgeline, opposite houses/cars, neighbouring driveways,
curb numbers and timestamp/watermark. Near street/sidewalk and owned property remain
visible. All cameras need timestamp/watermark coverage. Never enable audio.

After actual manual approval, record the still SHA-256, exact mask digest and
`privacy_reviewed: true` in that camera's config. `privacy_digest(camera, polygons)` in
`vigil.ingest.review` computes the digest; it grants no approval. Changing any polygon
invalidates the review. Ingest, processing, upload and session export reject missing review.

Run `uv run vigil doctor`. Real camera privacy and clock rows intentionally remain
MISSING until measured. Drift above 2 seconds prevents cross-camera linking. Transit
windows remain unmeasured until the field walk; no guessed timing links are accepted.
The pinned `reolink-aio==0.22.0` and ExifTool are installed; go2rtc and ML packages are not.
Camera probe/capture and any Meta calls still need the owner's explicit authorization.

## Battery import

Place silent Reolink app exports in `data/import/<camera_id>/`. Include a UTC
`YYYYmmddTHHMMSSZ` filename timestamp, or a sidecar named `clip.mp4.json`:

```json
{"start":"2026-11-03T18:14:00-08:00"}
```

The timestamp must have an explicit timezone. No file-mtime guesses are used. After
privacy review, run e.g. `uv run vigil reolink import side_left --session passage-evening`.
The original clip is retained; a new session contains masked windows and is labelled
Imported clips. Existing sessions are not overwritten. An audio stream is an ingest error.

## AC event capture and disk safety

After camera authorization and privacy review, the owner's `vigil reolink guard`
command starts only AC sub-stream rings, opens main video on person/vehicle events,
and retains masked observed parts plus explicit missing intervals. It does not invoke
Meta models. Main capture is bounded to 120 seconds and preserves interrupted fragments.
`EventRecorder` pins pre-roll and main sources. Oldest unpinned segments are evicted first
at the free-space floor; pinned evidence survives. If pinned evidence exhausts the floor,
capture stops with an error. Windows/cache retention is 48/72 hours. No real-data cleanup
was run during implementation.

Actual Wi-Fi performance, clocks, model outputs, privacy polygons, Duo homographies and
uncertainty, night/floodlight behaviour and full-camera acceptance remain field work.
All existing evidence is FIXTURE; no requirement is marked real-data Verified.
