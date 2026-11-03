---
name: vigil-fr-tdd
description: Use when implementing, changing or fixing a Vigil functional or non-functional requirement (FR-001 to FR-044, NFR-001 to NFR-037), replacing a NotImplementedError stub in vigil/, adding a spec 12.1 test, or when asked to "build FR-0xx", "make test_xxx pass" or update requirement status and traceability.
---

# Vigil FR, test-first

## Overview

Every requirement is done only when its spec-named test fails first, then passes, and the
requirement table says so. Code that exists before its test is deleted and rewritten.

## Steps

1. **Locate the requirement.**
   - `docs/spec/vigil-spec.md`: section 1 (FR) or 2 (NFR) row, its use case in section 3,
     the contract in 9.4, the signature in 9.5, the test file in 12.1.
   - `docs/requirements/functional.md` or `docs/requirements/non-functional.md` for the
     module, test names, Blocked-by and current status.
   - Search fast: `grep -n "FR-0xx" docs/spec/vigil-spec.md docs/requirements/*.md`.
2. **Find the owner module and test file** from spec 9.1 and 12.1 (e.g. FR-016 ->
   `vigil/reasoning/verdict.py`, `tests/unit/test_verdict.py`). Error cases come from the
   section 3 "Global error scenarios" table (`test_sam_parse_empty`, `test_sam_window_split`,
   `test_sam_400`, `test_client_retry`, `test_wonder_malformed`, `test_sync_residual`,
   `test_spend_cap`). Use those names exactly.
3. **Write the failing test (RED).**
   - Import types from `vigil.models`; reuse `tests/conftest.py` fixtures (`sample_config`,
     `po_side_gate`, `rule_r7`).
   - Encode the acceptance criterion literally (thresholds, error names, 0 pixels, 0.2 s).
   - Synthetic media goes to `tmp_path` (OpenCV/numpy + `vigil.settings.ffmpeg_bin()`).
   - Meta responses: replay fixtures from `tests/fixtures/meta/` via respx or a fake client
     (see the `meta-fixture` skill). Never call the network.
   - Mark anything billed `@pytest.mark.live`, GPU `gpu`, field `hardware`, slow `slow`.
   - Run `uv run pytest tests/unit/test_<x>.py -q` and **see it fail for the right reason**
     (assertion or NotImplementedError, not an import typo).
4. **Implement (GREEN)** in the owning module only, with the minimum code to pass.
   Keep the 9.5 names; refine signatures only when the spec requires it.
5. **Verify.**
   ```bash
   uv run ruff format <your paths>
   uv run ruff check <your paths>
   uv run pytest <your test files> -q
   uv run pytest -q          # whole default suite still green
   ```
6. **Update traceability** in the same change: in `docs/requirements/*.md` set the status
   reached (usually Offline-verified) and fill the test column with the real test names
   (drop the `*` marker once the name exists). Numbers go to `EVAL.md`.

## Boundaries

- Integrator-owned: `pyproject.toml`, `uv.lock`, `vigil/models.py`, `vigil/settings.py`,
  `vigil/cli.py`, `vigil/store/schema.sql`, `tests/conftest.py`, `Makefile`,
  `scripts/tasks.ps1`, `.github/**`. Do not edit them silently. If you need a field,
  dependency or CLI command: write a contract request in your report and use a
  module-private model meanwhile.
- Optional heavy deps (`open3d`, `trimesh`, `reolink-aio`, `torch`): lazy import inside the
  function, raise a clear "optional dependency missing" error, never needed by tests.
- Invariants from `CLAUDE.md` override convenience: verdict stays pure, only rules give
  `needs_attention`, gap sentences come from code, all model calls via `MetaClient`, roles come
  from spatial origin with `unknown` failing closed, rules fire only by `applies_to`.

## Status levels

Use the legend in `docs/requirements/functional.md` (same for `non-functional.md`):

| Evidence | Status you may write |
| --- | --- |
| No passing evidence yet, or some tests red/skipped | Not verified |
| Some offline behaviour green, some missing | Partial (offline), saying which part is missing |
| Offline tests green on synthetic data or recorded fixtures | Offline-verified, with test names |
| Spec acceptance met on real data, CI green or manual check logged with a date | Verified |
| Cannot progress until the *Blocked-by* item (credits, hardware, DGX, owner) clears | Blocked |

**Never write Verified from offline tests alone.** Field-only criteria (e.g. "2 h capture",
"probe passes for all 4 cameras") stay open until the runbook result is logged.

## Red flags: stop and restart the cycle

- Implementation written before the test, or the test never observed failing.
- Test passes only because it is skipped, mocked to return the expected answer, or marked live.
- "I'll update the requirement table later."
- Editing `vigil/models.py` to make a test compile.
- A test that needs network, credentials, real footage or a GPU to run by default.
