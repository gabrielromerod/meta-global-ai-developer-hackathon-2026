# Vigil: agent instructions

Vigil turns home-camera motion into one cited story per visit, placed in a 3D model of the
house. **Meta models perceive and write; Vigil's code links, checks and decides.**
The spec is `docs/spec/vigil-spec.md` (FRs in section 1, NFRs in 2, contracts 9.3 to 9.5,
tests 12.1). Read the section for your task before you change code. This file is the single
source of agent instructions; `AGENTS.md` only points here.

## Commands

| Task | Command |
| --- | --- |
| Install (Python 3.12, uv) | `uv sync` |
| Unit and integration tests (excludes live, gpu, e2e) | `uv run pytest` |
| One file, quiet | `uv run pytest tests/unit/test_verdict.py -q` |
| Browser E2E | `uv run playwright install chromium` then `uv run pytest -m e2e tests/e2e` |
| Lint / format | `uv run ruff check .` and `uv run ruff format .` (CI runs `ruff format --check .`) |
| CLI | `uv run vigil --help` (`version`, `ingest`, `process`, `eval`, `export`, `serve`, `spatial`, `reolink`, `cost`) |
| Task runner | Windows: `pwsh scripts/tasks.ps1 <target>` (or `powershell -File scripts/tasks.ps1 <target>`); elsewhere: `make <target>` |

Targets: `setup lint format test e2e demo eval export scan`. `make scan` runs the privacy scan
and the exiftool metadata scan; the PowerShell `scan` runs only the privacy scan, so on Windows
also run `bash scripts/metadata_scan.sh demo`.

**ffmpeg/ffprobe:** always resolve them with `vigil.settings.ffmpeg_bin()` /
`ffprobe_bin()` (override, then PATH, then the WinGet Links folder). Never call bare `"ffmpeg"`.

## Repository map (spec 9.1)

```text
config/        cameras.yaml (cameras, zones, privacy, blind regions, topology), calibration.json
vigil/models.py   shared pydantic contracts      vigil/settings.py  env settings, ffmpeg resolution
vigil/reolink/    probe, capture, ai_events      vigil/ingest/      sync, privacy, windows, motion
vigil/meta/       client (MetaClient), budget, cache, sam, sam_local, spark, wonder, asr, glimmer, prompts/
vigil/perception/ tracks, events, overlays       vigil/spatial/     scan, calibrate, coverage, locate
vigil/reasoning/  topology, visits, rules, triage, story, validator, verdict, loop, templates
vigil/store/      schema.sql, db, export         vigil/api/         app, routes, live, guards
vigil/eval/       run, metrics, baseline, spatial_eval
web/ (index, cards, player; twin/ three.js viewer; calibrate/ LAN tool)   infra/go2rtc.yaml
eval/labels/ eval/hardware/ eval/budget.md    EVAL.md    demo/ (masked bundle)   data/ (gitignored)
scripts/       tasks.ps1, smoke_meta.py, gpu_probe.py, privacy_scan.py, metadata_scan.sh
tests/         unit/ integration/ e2e/ fixtures/ (conftest.py shares sample_config, po_side_gate, rule_r7)
docs/          spec/, requirements/, runbooks/, architecture/, plans/, conventions.md, readiness.md
```

## Architecture invariants (do not break)

- **Verdict is code.** `vigil/reasoning/verdict.py` is a pure function (spec 9.4). Rules set
  the floor; **only a rule can produce `needs_attention`**; an unresolved gap with no rule
  gives `cant_confirm`; Wonder may raise normal to noteworthy, never lower anything.
- **Gaps are data.** Gap sentences are written by code, never by a model. No positions or
  claims inside a gap; no interpolation across one.
- **Wonder never sees pixels.** It gets the visit ledger as JSON. Every sentence must cite
  event IDs and pass `validator.py`; failure means one retry with reasons, then the template.
- **Every model call goes through `vigil/meta/client.py` `MetaClient`**: cache first, budget
  guard (`vigil/meta/budget.py`) prices it before sending, ledger row after. No direct httpx
  calls to Meta from any other module.
- Model output can only act through allowlists (watch phrases, rule targets). Appearance
  notes never have face, age, gender, skin or ethnicity fields; stories never use those words.
- Detection layers stay separate in the UI: Reolink AI event, SAM track, 3D estimate, story.

## Integration boundaries

- Shared types live in `vigil/models.py`. Import them; never redefine them in a module.
- **Integrator-owned files** (change only when asked, and say so in your report):
  `pyproject.toml`, `uv.lock`, `vigil/models.py`, `vigil/settings.py`, `vigil/cli.py`,
  `vigil/store/schema.sql`, `tests/conftest.py`, `Makefile`, `scripts/tasks.ps1`, `.github/**`.
  Need a new field, dependency or CLI wiring? Request it; use a module-private model meanwhile.
- No `uv add` / `pip install` without the owner. Optional extras (`open3d`, `trimesh`,
  `reolink-aio`, `torch`) are lazy-imported with a clear "optional/blocked" error and are
  never required by tests.

## Testing rules

- **TDD.** Write the failing test first, named as in spec 12.1 and the section 3 "Global
  error scenarios" table (e.g. `test_sam_parse_empty`, `test_client_retry`, `test_spend_cap`).
  Use the `vigil-fr-tdd` skill.
- Markers (`--strict-markers`): `live` (billed Meta calls), `gpu`, `slow`, `e2e`, `hardware`.
  Default runs exclude `live`, `gpu` and `e2e`. **Live tests never run in CI** and only by
  the owner behind the budget guard.
- Tests are offline, deterministic and fast. Generate videos/images into `tmp_path` at test
  time; never commit large binaries. Replay Meta responses from `tests/fixtures/meta/`
  (see the `meta-fixture` skill); mock HTTP with respx.
- Before reporting done: `uv run ruff format <paths>`, `uv run ruff check <paths>`,
  `uv run pytest <tests> -q`. Report what you observed, including failures.

## Privacy rules

- Never commit raw footage, scans, credentials, `.env`, GPS/device metadata, house numbers,
  plates, neighbours or street-facing frames. `data/` is gitignored and stays that way.
- Run the `privacy-gate` skill before any export, any change under `demo/`, and any commit
  that adds media. No real footage or personal data in tests or fixtures.
- Credentials come from `.env` via settings; they never appear in logs, errors or fixtures.

## Budget rules (spec 11, FR-043, NFR-036/037)

- Hard cap **$140** total; sandbox **$10/day**; feature budgets per spec 11.4.
- Only Standard-mode model IDs (`sam-3.1`, `muse-spark-1.3`, `muse-wonder-1.0`,
  `muse-voice-transcribe-1.0`). **Never a `-contributor` ID** (CI greps for it).
- `VIGIL_ALLOW_PAID` is set only by the owner. Never set it, never bypass the guard.
- Never make a live Meta call without explicit owner approval; use the `budget-check` skill
  first. Batch commands print an estimate and need `--confirm` above $5.

## Git workflow

- Owner's choice (a deviation from spec 12.3's PR flow): commit to `main` after a validated
  phase, with CI green. Do not commit or push unless the owner asks.
- Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `build:`, `chore:`), with the
  `Co-Authored-By` trailer as configured for the session.
- Never skip hooks, force-push, or rewrite published history.

## FR traceability

- Requirement status lives in `docs/requirements/functional.md` and `non-functional.md`
  (statuses: Not verified, Offline-verified, Verified, Blocked). When an FR's offline tests
  pass, set Offline-verified and the test names in the same change. **Never mark Verified
  without real-data acceptance** (field data, or a manual check logged with a date).
- Numbers that matter (latency, cost, accuracy) go to `EVAL.md`, not only to chat.
- EVAL targets are pre-registered before results (`eval-preregister` skill).
- Blocked or owner-dependent work (credits, hardware, DGX, field steps) is listed in
  `docs/readiness.md`; add to it instead of silently skipping.

## Project skills (`.claude/skills/`)

`vigil-fr-tdd` · `meta-fixture` · `privacy-gate` · `eval-preregister` · `field-runbook` · `budget-check`
