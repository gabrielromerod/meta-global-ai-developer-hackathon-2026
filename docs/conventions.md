# Conventions

How code, tests, commits and documents are written in this repository. Derived from the spec ([9](spec/vigil-spec.md#9-engineering-implementation-plan), [11.6](spec/vigil-spec.md#116-safeguards), [12](spec/vigil-spec.md#12-quality-and-verification)) plus the decisions made during the [bootstrap](plans/phase-1-foundation.md).

## Toolchain

| Item | Convention |
| --- | --- |
| Python | 3.12 only (`requires-python = ">=3.12,<3.13"`, `.python-version`) |
| Package manager | uv. `uv sync` installs the locked environment; `uv run <cmd>` runs inside it |
| Dependencies | Exact pins in `pyproject.toml`; `uv.lock` pins the transitive set. Heavy or hardware-only packages are optional extras (`reolink`, `spatial`) and must be imported lazily with a clear "optional, not installed" error. `torch` is not a dependency; GPU code guards its import |
| ffmpeg | Always resolve through `vigil.settings.ffmpeg_bin()` and `ffprobe_bin()`, never a bare `"ffmpeg"`: on the Windows workstation winget installs it outside `PATH` |
| Task runners | `make <target>` on Linux, macOS, WSL and CI; `pwsh scripts/tasks.ps1 <target>` on Windows. Same targets: `setup lint format test e2e demo eval export scan` |
| CLI | `vigil` (typer), defined in `vigil/cli.py` |

## Lint, format and typing

- ruff is the only linter and formatter: line length 100, target `py312`, rules `E F W I B UP SIM RUF S PT` (see `[tool.ruff]` in `pyproject.toml`). `web/twin/vendor` and `docs/spec` are excluded.
- Run before every hand-off: `uv run ruff format <paths>` then `uv run ruff check <paths>`.
- Type hints on every public function. Use the pydantic models in `vigil/models.py` for anything that crosses a module boundary; never redefine them. If a module needs a new shared type, request it from the integrator and use a module-private model meanwhile.
- `from __future__ import annotations` at the top of modules; `X | None` rather than `Optional[X]`.
- Pure functions where the spec says so (verdict, rules, validator): no I/O, no clock, no randomness without an injected `rng`.

## Module ownership and integration boundaries

- Each workstream owns a set of paths and writes only those.
- **Only the integrator edits** `pyproject.toml`, `uv.lock`, `vigil/models.py`, `vigil/store/schema.sql`, `vigil/settings.py`, `vigil/cli.py`, `tests/conftest.py`, `Makefile`, `scripts/tasks.ps1` and `.github/**`.
- Changes to those files are requested in the workstream report (contract requests, dependency requests), never made directly.
- Module interfaces follow [spec 9.5](spec/vigil-spec.md#95-module-interfaces). Keep the names; refine signatures only when the spec requires it, and report the change.
- Where existing code differs from the spec, keep the existing names and update the docs rather than renaming working code (spec section 0).
- `docs/spec/` and `docs/audit/` are read-only for workstreams.

## Test-driven development

1. Write the failing test first, using the names from [spec 12.1](spec/vigil-spec.md#121-test-suites) and the [global error table](spec/vigil-spec.md#global-error-scenarios) (`test_sam_parse_empty`, `test_sam_window_split`, `test_sam_400`, `test_client_retry`, `test_wonder_malformed`, `test_sync_residual`, `test_spend_cap`).
2. Implement until green; refactor with the test still green.
3. Tests are deterministic, offline and fast (under about 20 s per file). No network, no credentials.
4. Binary fixtures (videos, images, meshes) are generated at test time into `tmp_path`; never commit large binaries. Recorded Meta responses live in `tests/fixtures/meta/` and contain no real footage.
5. Layout: `tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/fixtures/`. Shared fixtures (`sample_config`, `po_side_gate`, `rule_r7`) live in `tests/conftest.py`.

### pytest markers

Defined in `pyproject.toml` with `--strict-markers`. The default run excludes `live`, `gpu` and `e2e`.

| Marker | Meaning | Default run | CI |
| --- | --- | --- | --- |
| `live` | Real, billed Meta API calls; behind the budget guard; run by hand before gates | Excluded | Never |
| `gpu` | Needs a probed local GPU (H-01) | Excluded | Never |
| `slow` | Takes more than a few seconds | Included | Yes |
| `e2e` | Playwright against a running server | Excluded | Separate step (spec 12.2 step 7) |
| `hardware` | Needs Reolink cameras or other field hardware | Not excluded by `addopts` today, so every `hardware` test must skip itself when the hardware is absent | Must skip (no hardware on runners) |

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `type(scope): summary` in the imperative, lower case, no trailing period.

| Type | Use for |
| --- | --- |
| `feat(scope)` | New behaviour, e.g. `feat(reasoning): verdict truth table` |
| `fix(scope)` | Bug fix |
| `test(scope)` | Tests only |
| `docs(scope)` | Documentation only |
| `build` | Toolchain, dependencies, packaging |
| `ci` | Workflow changes |
| `chore` | Housekeeping |

Scopes are package or area names: `ingest`, `meta`, `perception`, `spatial`, `reasoning`, `store`, `api`, `web`, `eval`, `reolink`, `docs`. Reference requirement IDs in the body (`Closes FR-016`). Never put credentials, real addresses or personal data in a commit message.

## Branching (deviation from spec 12.3)

**Deviation.** [Spec 12.3](spec/vigil-spec.md#123-definition-of-done-for-any-task) says "Code merged through a pull request with CI green". The owner chose instead: **commit and push to `main` after each validated phase, with CI green.** A phase is validated when its lint and tests pass locally and its report is reviewed by the integrator. Pull requests remain available for risky changes, but are not required.

Consequences: keep `main` releasable at every push; never push a red tree; if CI goes red after a push, fixing it is the next commit.

## Code decides, models propose

- Meta models perceive (SAM 3.1), describe (Spark), write (Wonder) and transcribe (Voice). Vigil's code links, checks and decides.
- The verdict is a pure function of the rule floor, gaps and a cited proposal ([spec 9.4](spec/vigil-spec.md#94-contracts)). Only a rule can produce *Needs your attention*; Wonder may raise *Normal* to *Noteworthy*, never lower.
- Every model sentence passes the validator; gap sentences are written by code.
- Model proposals that cause actions (watches) pass an allowlist and caps; anything else is rejected and logged (NFR-016).
- Every displayed model output carries its model ID and call ID (NFR-022).

## Privacy rules

- No real footage, raw segments, scans, credentials, GPS or personal data in the repository. `data/` and media files are gitignored; only masked demo assets go in `demo/`.
- Privacy polygons are blacked out and audio removed before anything is stored for upload; uploads are refused otherwise (FR-003).
- No code, schema, prompt or UI produces face, age, gender, skin or ethnicity attributes; stories say "a person" or "they"; no judgements such as "suspicious", "intruder" or "thief" (NFR-003, validator check 5).
- Vigil never identifies people. Rules that mention identity are rewritten to "anyone" with a disclaimer.
- Standard mode only: no `-contributor` model IDs (NFR-004; CI greps for them).
- Credentials only in `.env` on the edge machine; never logged (NFR-014, NFR-031).
- Consent from everyone filmed; plates covered with "VIGIL-01"; no house number or street-facing frames (NFR-032).

## Budget rules

- Every Meta call goes through `MetaClient`, which prices it before sending and enforces the total cap ($140), the feature budgets ([11.4](spec/vigil-spec.md#114-cost-by-feature)) and the daily cap ($10 in the sandbox).
- Cache first: identical requests are never paid twice.
- Batch commands print a pre-flight estimate and need `--confirm` above $5.
- After the credit window, live calls are disabled unless the owner sets `VIGIL_ALLOW_PAID=1` (NFR-037).
- Tests never make billed calls; `live` tests are run by hand and logged.
- Reconcile the ledger with the Billing page daily ([credits runbook](runbooks/credits-billing.md)).

## Definition of done (adapted from spec 12.3)

- [ ] Committed and pushed to `main` after the phase is validated, with CI green (replaces "merged through a pull request", see [branching](#branching-deviation-from-spec-123))
- [ ] Its tests named in [spec 12.1](spec/vigil-spec.md#121-test-suites) exist and pass
- [ ] Status in the [functional](requirements/functional.md) and [non-functional](requirements/non-functional.md) checklists updated: *Offline-verified* by test, *Verified* on real data (or manual check logged with a date), or *Blocked* with the reason
- [ ] Any number it produces is written to [EVAL.md](../EVAL.md), not only to chat or notes
- [ ] No raw footage, credentials or location metadata added to the repo
- [ ] `ruff format` and `ruff check` clean on the changed paths
