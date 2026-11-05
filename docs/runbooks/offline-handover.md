# Offline QA and key handover

REAL: the local sandbox server and installed `reolink-aio==0.22.0`.
FIXTURE: generated MP4/GLB media, authored HTTP replay, synthetic scenarios and browser tests.
No Meta call, camera connection or paid smoke run was performed for this work. There are
no captured live Meta responses in the new tests. Real-data acceptance remains open.

## QA in Windows CMD

```cmd
cd /d C:\Users\lords\Desktop\meta-global-ai-developer-hackathon-2026
set VIGIL_MODE=sandbox
set MODEL_API_KEY=invalid-qa-key-do-not-use
set VIGIL_META_CACHE_ONLY=true
uv run uvicorn vigil.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000. The background instance started during this task has parent
PID **36112**. To stop that instance from CMD:

```cmd
taskkill /PID 36112 /T /F
```

Then use the start commands above. For an instance you start in CMD, press Ctrl+C and
rerun the uvicorn command. Refresh the browser after frontend edits. Put QA reports in
qa/QA_NOTES.md; fixes are recorded there with their implementation SHA.

## Offline readiness check

```cmd
uv run vigil doctor
```

Exit 0 means the configuration checks are READY; exit 1 prints named MISSING entries.
The command never authenticates to Meta or probes cameras. Key presence is not proof of
API access; polygon presence is not proof of correct field placement. It checks the
credit/judging window, durable ledger, camera privacy, pinned SDK, hosts in .env, camera
credentials, ffmpeg/ffprobe, edge mode and owner token without printing secret values.

Current blockers: the real key and credit-window end, durable ledger configuration, four
camera IPs and credentials, backyard privacy polygons or an explicit owner declaration
of `privacy: none_needed`, edge-mode settings and an owner token. Review all sample
polygons against actual camera frames. Footage, scan and camera calibration remain owner
inputs. exiftool and gitleaks are not installed locally; the metadata scan was skipped,
so the full publication privacy gate has not passed.

When the owner supplies .env, clear QA overrides in the command window so .env can win:

```cmd
set MODEL_API_KEY=
set VIGIL_MODE=
set VIGIL_META_CACHE_ONLY=
uv run vigil doctor
```

## Later, only for an owner-approved cloud run

These commands were **not run live**. `evening` must already have ingested masked windows:

```cmd
uv run vigil process --session evening --cloud --confirm
uv run vigil export --session evening --out data\bundles\evening
set VIGIL_BUNDLE_DIR=data\bundles\evening
uv run vigil serve
```

The explicit cloud switch still uses MetaClient's cache, budget guard and ledger.
Session results and SQLite snapshots live in data/results/evening; the persistent owner
database is preserved. Export produces aligned masked videos, production overlays,
trace and twin data. Imported GLB, calibrated poses and calculated coverage are included
when their files are present. Run the required privacy gate before publishing media.

See [Wi-Fi session capture](wifi-session.md) and [GLB import](glb-import.md). The live smoke
script is prepared for the owner's later approval; it has only been contract-tested with
fakes here. No paid setting or judging cap was changed.
