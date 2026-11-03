# Phase 2: parallel offline core, documentation and tooling

| Item | Value |
| --- | --- |
| When | Mon Nov 2, 2026, from about 12:00 PT |
| Workstreams | 9 in parallel, each with exclusive write ownership of its paths |
| Status | Done offline: 1275 tests pass on Nov 2, including the Nov 2 spec changes ([readiness](../readiness.md)) |

## Goal

Build everything that can be built and proven **offline** (synthetic data, recorded fixtures, no Meta calls, no field hardware) at the same time, so that when footage, scans and credits arrive the pipeline only needs real inputs.

## Rules for every workstream

- Write only the paths you own; request changes to shared files through the integrator ([conventions](../conventions.md#module-ownership-and-integration-boundaries)).
- Test first, with the test names from [spec 12.1](../spec/vigil-spec.md#121-test-suites) and the [global error table](../spec/vigil-spec.md#global-error-scenarios).
- Tests are deterministic, offline and fast; binary fixtures are generated at test time into `tmp_path`.
- No real Meta API call; anything networked is behind the `live` marker and the budget guard.
- No real footage, credentials, GPS or personal data; no face, age, gender, skin or ethnicity attributes anywhere.
- Before handing back: `uv run ruff format`, `uv run ruff check` and `uv run pytest` on your paths, all clean, and an honest report.

## Scope by area

| Area | Offline target | Requirements reachable offline | Waits on |
| --- | --- | --- | --- |
| Ingest | config loader, sync, privacy, windows, motion | FR-001, FR-003, FR-004 (edges), FR-005 (logic), NFR-001, NFR-002 | Footage for real-data acceptance |
| Meta client | client, retries, cache, ledger, budget guard, SAM parsing, Spark, Wonder, ASR adapters on recorded fixtures | FR-006 (parsing), FR-023, FR-043, NFR-004, NFR-010 | Credits for live smoke (T-03) |
| Perception | stitching, events, overlays | FR-007, FR-008 | Real tracks |
| Spatial | synthetic-camera calibration, locate, coverage; scan build behind an optional import | FR-036, FR-037, FR-038, FR-039 (synthetic), NFR-026 (synthetic) | LiDAR scan, checkerboards, markers |
| Reasoning | topology, visits, gaps, rules, triage, story, validator, verdict, loop | FR-010 to FR-016, FR-020, NFR-016 | Labelled scenarios |
| API and web | routes, guards, live stream, cards, player, 3D viewer | FR-017, FR-018, FR-026, NFR-009, NFR-015 | Demo bundle |
| Reolink | probe and capture against fakes; AI events from recorded payloads | FR-030 to FR-032 (offline parts) | Cameras |
| Eval and tooling | metrics, run, baseline, spatial eval; privacy and metadata scans | FR-024 (logic), NFR-011 | Labels |
| **Documentation (D1)** | this docs tree, README, EVAL.md (pre-registered targets), HACKATHON.md, 14 diagrams validated | Pre-registration for NFR-023, NFR-025, NFR-026, NFR-035 | none |

## Exit criteria

- [ ] Every workstream report received with exact commands and results
- [ ] Integrator merges contract and dependency requests into the shared files
- [ ] `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` green on the merged tree
- [ ] Requirement statuses moved to *Offline-verified* where tests prove it ([functional](../requirements/functional.md), [non-functional](../requirements/non-functional.md))
- [ ] EVAL.md targets committed before any benchmark run (pre-registration)
- [ ] Committed and pushed to `main` with CI green

Next: [phase 3](phase-3-ci-and-h01.md).
