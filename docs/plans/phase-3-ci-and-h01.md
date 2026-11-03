# Phase 3: CI completion and H-01

| Item | Value |
| --- | --- |
| When | Mon Nov 2, 2026, after phase 2 merges; H-01 due Mon 12:30 PT per spec |
| Owner | Integrator (CI); owner at the workstation (H-01) |
| Status | Not started |

## Goal

Bring CI up to the full [spec 12.2 pipeline](../spec/vigil-spec.md#122-ci-pipeline-githubworkflowsciyml) and prove the RTX 3090 with a runtime probe before any GPU work (NFR-034).

## CI steps (spec 12.2)

| Step | Spec | State after phase 1 | Work in phase 3 |
| --- | --- | --- | --- |
| 1 | ruff lint and format check | Present (plus the `-contributor` grep for NFR-004) | none |
| 2 | gitleaks secret scan | Present | none |
| 3 | unit, property and integration tests (`pytest -m "not live"`) | Present | Confirm the markers exclude `live`, `gpu`, `e2e`, `hardware` |
| 4 | determinism check (pipeline twice, diff) | Missing | Add once `test_determinism.py` and the golden fixtures exist (NFR-011) |
| 5 | privacy scan and exiftool metadata scan over `demo/` | Missing | Add `scripts/privacy_scan.py` and `scripts/metadata_scan.sh` steps (NFR-001, NFR-032) |
| 6 | build the Docker image; start with `VIGIL_MODE=sandbox` and an invalid key | Missing | Needs the `Dockerfile` (T-28) |
| 7 | Playwright E2E, offline and mobile suites | Missing | Needs the web app and bundle (T-21, T-24) |
| 8 | upload Playwright traces and screenshots as artifacts | Missing | With step 7 |

Steps 6 to 8 depend on later build tasks; add them as the inputs land, and never mark them green before they run.

## H-01 GPU probe

Procedure: [GPU runbook](../runbooks/gpu-h01-h04.md#h-01-gpu-probe). Output: `eval/hardware/3090.json`, marking the 3090 Ready or Not ready.

- **Blocked-by: hardware** (the RTX 3090 workstation), and `torch` is not installed in the default environment, so the probe needs the GPU extra or a WSL2 environment set up by the owner.
- Until H-01 passes, `VIGIL_SAM_BACKEND=api` and `VIGIL_TRIAGE_BACKEND=spark` stay the defaults.

## Exit criteria

- [ ] CI steps 1 to 5 present and green on `main`
- [ ] Steps 6 to 8 tracked as issues in the [backlog](../backlog.md) with their blocking task
- [ ] H-01 report committed, or H-01 recorded as blocked with the reason
- [ ] Committed and pushed to `main` with CI green

Next: [phase 4](phase-4-github-backlog.md).
