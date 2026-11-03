# Phase 1: foundation, shared contracts and CI

| Item | Value |
| --- | --- |
| When | Mon Nov 2, 2026, about 11:55 to 12:00 PT (covers spec T-02) |
| Commit | `3d53d05` build: project foundation, shared contracts, package skeleton and CI |
| Owner | Integrator |
| Status | Done: commit `3d53d05`; latest [CI run 41587853241](https://github.com/gabrielromerod/meta-global-ai-developer-hackathon-2026/actions/runs/41587853241) green on `46c5b68` |

## Goal

Give every parallel workstream one stable base: the toolchain, the shared types, the configuration, the package skeleton with spec [9.5](../spec/vigil-spec.md#95-module-interfaces) signatures as stubs, and a CI that runs on every push.

## Deliverables

| Area | Files | Spec |
| --- | --- | --- |
| Toolchain | `pyproject.toml` (Python 3.12, exact pins), `uv.lock`, `.python-version`, ruff and pytest config with markers | [9.2](../spec/vigil-spec.md#92-dependencies-pin-exact-versions-in-pyprojecttoml-on-day-1) |
| Shared contracts | `vigil/models.py` (pydantic models used across modules), `vigil/store/schema.sql` | [9.3](../spec/vigil-spec.md#93-data-model-vigilstoreschemasql), [9.4](../spec/vigil-spec.md#94-contracts) |
| Settings | `vigil/settings.py` (env settings, `ffmpeg_bin()` and `ffprobe_bin()`), `.env.example` | [11.6](../spec/vigil-spec.md#116-safeguards) |
| Configuration | `config/cameras.yaml` (sample geometry: `front`, `side_left`, `side_right`, `backyard`, blind region `shed_back`, topology) | [9.4](../spec/vigil-spec.md#94-contracts) |
| Package skeleton | `vigil/{reolink,ingest,meta,perception,spatial,reasoning,store,api,eval}/` stubs; `vigil/cli.py` | [9.1](../spec/vigil-spec.md#91-repository-structure) |
| Tests | `tests/conftest.py` shared fixtures (`sample_config`, `po_side_gate`, `rule_r7`), `tests/unit/test_models.py` | [12.1](../spec/vigil-spec.md#121-test-suites) |
| Task runners | `Makefile` (Linux, macOS, CI), `scripts/tasks.ps1` (Windows) | [9.1](../spec/vigil-spec.md#91-repository-structure) |
| CI | `.github/workflows/ci.yml`: ruff, contributor-ID grep, gitleaks, pytest (not live) | [12.2](../spec/vigil-spec.md#122-ci-pipeline-githubworkflowsciyml) steps 1 to 3 |

## Decisions

- **Integration boundary.** Only the integrator edits `pyproject.toml`, `uv.lock`, `vigil/models.py`, `vigil/store/schema.sql`, `vigil/settings.py`, `vigil/cli.py`, `tests/conftest.py`, the task runners and CI. See [conventions](../conventions.md#module-ownership-and-integration-boundaries).
- **Optional heavy dependencies** (`reolink-aio`, `open3d`, `trimesh`, `torch`) are extras, never required by tests.
- **ffmpeg** is installed by winget on the Windows workstation and may not be on `PATH`; always resolve it through `ffmpeg_bin()` and `ffprobe_bin()`.

## Exit criteria

- [x] Committed to `main` as `3d53d05` (owner's branching choice, see [conventions](../conventions.md#branching-deviation-from-spec-123))
- [ ] `uv sync` succeeds; `uv run pytest` green; ruff clean (integrator to confirm and tick)
- [ ] Pushed, with CI green on `main` (integrator to confirm in GitHub Actions and tick)

Next: [phase 2](phase-2-parallel-core.md).
