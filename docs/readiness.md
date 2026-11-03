# Readiness checklist

**Date: 2026-11-02** (Mon Nov 2, 13:15 PT, end of the bootstrap). Spec: [section 13](spec/vigil-spec.md#13-final-readiness). Vigil is ready to submit when every row of the [traceability matrix](requirements/functional.md#traceability-matrix-spec-131) has a green test and the demo evidence it names, on real data.

Everything below is evidenced by a command that was run on this date, or by a file in the repo. CI evidence is filled in by the integrator: run `<CI run URL>` at commit `<commit>`. **Nothing has been verified on real data yet**: no footage, scan, calibration or billed Meta API call exists.

## Requirement status

| Set | Total | Offline-verified | Partial (offline) | Blocked | Not verified | Verified |
| --- | --- | --- | --- | --- | --- | --- |
| Functional ([checklist](requirements/functional.md)) | 44 | 25 | 16 | 1 | 2 | 0 |
| Non-functional ([checklist](requirements/non-functional.md)) | 37 | 13 | 13 | 9 | 2 | 0 |

The spec now has 44 FRs: the [Nov 2 change set](spec/changes/2026-11-02-business-corrections.md) added FR-044 and changed several FRs and NFRs after the offline code was written, which is why 16 FRs are only *Partial (offline)*.

## Completed

| Item | Evidence |
| --- | --- |
| Phase 0: repo audit | [audit/2026-11-02-repo-audit.md](audit/2026-11-02-repo-audit.md) |
| Phase 1: foundation, shared contracts, CI | Commit `3d53d05` ("build: project foundation, shared contracts, package skeleton and CI"); [.github/workflows/ci.yml](../.github/workflows/ci.yml) runs ruff, the contributor-ID grep, gitleaks, pytest, the determinism double run, the privacy and metadata scans and the Docker E2E job. Result for the current tree: `<CI run URL>` at `<commit>` |
| Phase 2: offline core | All modules in [spec 9.1](spec/vigil-spec.md#91-repository-structure) exist under `vigil/`, plus `vigil/pipeline.py`, `web/` (cards, player, `twin/` viewer, `calibrate/`), `demo/synthetic/` (synthetic bundle and builder) and `config/` (`cameras.yaml`, `rules.default.json`, `allowlist.json`) |
| Unit and integration suite | `uv run pytest -q -rA`: **801 collected (12 e2e deselected): 800 passed, 1 failed** in 75.95 s. 648 unit tests in 28 files under `tests/unit/`, 153 integration tests in 8 files under `tests/integration/`. The failure is `tests/integration/test_store.py::test_synthetic_bundle_regenerates_byte_identical` (see [Remaining gaps](#remaining-gaps)) |
| Browser E2E | `uv run pytest -m e2e tests/e2e -q`: **12 passed** in 8.69 s (Chromium; `tests/e2e/test_judge_path.py` 8, `tests/e2e/test_mobile.py` 4), served with `MODEL_API_KEY=invalid` and an unreachable live backend. One `PytestRemovedIn10Warning` about the session-scoped `base_url` fixture |
| H-01 GPU probe | [eval/hardware/3090.json](../eval/hardware/3090.json): RTX 3090, driver 617.42, CUDA driver 13.4, `ready: true`, probed 2026-11-02T20:50:57Z, Windows 11. It reports torch 2.14.1+cu130, but `torch` is **not** installed in the project environment (`uv run python -c "import torch"` fails) |
| CLI | `uv run vigil --help` lists `version ingest process eval export serve spatial reolink cost demo`; commands that need field data or credits exit with a "blocked:" reason (covered by `tests/unit/test_cli.py`, 44 tests) |
| Pre-registered artefacts | [EVAL.md](../EVAL.md) targets section; [eval/labels/README.md](../eval/labels/README.md) and `_template.json` (no scenario labels yet); [eval/budget.md](../eval/budget.md) with an empty 2026-11-02 row |
| Docs | [requirements/functional.md](requirements/functional.md) and [requirements/non-functional.md](requirements/non-functional.md) reconciled against the test run above; runbooks under [runbooks/](runbooks/reolink.md) |

**Lint is not clean** (seen on 2026-11-02, so CI's lint step will fail until fixed): `uv run ruff check .` reports 1 error (E501 at `vigil/settings.py:51`, an integrator-owned file); `uv run ruff format --check .` reports `.claude/skills/meta-fixture/SKILL.md` would be reformatted.

## Offline-verified requirements

Offline-verified means tests exercise the offline acceptance on synthetic data or authored fixtures and pass. Real-data acceptance is still open for every row.

| ID | Requirement (short) | Key evidence |
| --- | --- | --- |
| FR-001 | Camera config and topology | `tests/unit/test_config.py`, `tests/unit/test_topology.py` |
| FR-002 | Clock alignment | `tests/unit/test_sync.py` |
| FR-003 | Privacy at source | `tests/unit/test_privacy.py`, `tests/integration/test_contracts.py` |
| FR-004 | Windowing | `tests/unit/test_windows.py` |
| FR-005 | Motion gate | `tests/unit/test_motion.py` |
| FR-006 | SAM 3.1 tracking (authored fixtures) | `tests/unit/test_sam_parse.py`, `tests/integration/test_client_faults.py` |
| FR-007 | Track stitching | `tests/unit/test_tracks.py` |
| FR-009 | Appearance notes | `tests/unit/test_spark_schema.py` |
| FR-011 | Gaps | `tests/unit/test_visits.py`, `tests/integration/test_golden.py` |
| FR-014 | Wonder story | `tests/unit/test_wonder.py`, `tests/unit/test_story.py` |
| FR-015 | Citation validator | `tests/unit/test_validator.py` |
| FR-016 | Verdict | `tests/unit/test_verdict.py` |
| FR-017 | Visit cards | `tests/e2e/test_judge_path.py`, `tests/integration/test_api.py` |
| FR-018 | Synced player | `tests/e2e/test_judge_path.py` |
| FR-019 | Tap-to-protect (cached, fake live backend) | `tests/unit/test_sam_parse.py`, `tests/integration/test_api.py` |
| FR-020 | Closed loop | `tests/unit/test_loop.py`, `tests/integration/test_golden.py` |
| FR-023 | Call ledger and telemetry | `tests/integration/test_client_faults.py`, `tests/integration/test_api.py` |
| FR-024 | Evaluation harness | `tests/unit/test_eval_metrics.py` |
| FR-025 | Naive baseline | `tests/unit/test_eval_metrics.py` |
| FR-026 | Sandbox modes and guards | `tests/integration/test_guards.py`, `tests/e2e/test_judge_path.py` |
| FR-030 | Reolink probe (fake transport) | `tests/integration/test_reolink.py` |
| FR-031 | Continuous capture (fake processes) | `tests/unit/test_capture.py` |
| FR-032 | Reolink AI events (fake adapter) | `tests/integration/test_reolink.py` |
| FR-038 | Coverage and blind regions | `tests/unit/test_coverage.py` |
| FR-039 | 3D position estimates | `tests/unit/test_locate.py`, `tests/unit/test_locate_coverage.py` |
| NFR-001 | No unmasked pixel | `tests/unit/test_privacy.py` |
| NFR-004 | Standard models only | `tests/unit/test_budget.py`, `tests/integration/test_guards.py` |
| NFR-009 | Works with the API unreachable | `tests/e2e/`, `tests/integration/test_api.py` |
| NFR-010 | Retries, then cached result with notice | `tests/integration/test_client_faults.py` |
| NFR-011 | Determinism | `tests/integration/test_determinism.py` |
| NFR-013 | Sandbox daily cap | `tests/integration/test_guards.py` |
| NFR-015 | Rate limits and input bounds | `tests/integration/test_guards.py` |
| NFR-016 | Allowlist-only actions | `tests/unit/test_loop.py` |
| NFR-017 | Phone layout | `tests/e2e/test_mobile.py` |
| NFR-018 | One click to evidence | `tests/e2e/test_judge_path.py` |
| NFR-026 | Truthful uncertainty (synthetic) | `tests/unit/test_locate_coverage.py` |
| NFR-032 | No location metadata | `tests/unit/test_privacy.py`, `tests/unit/test_scan.py` |
| NFR-034 | GPU probe before use | `tests/unit/test_eval_metrics.py`, `eval/hardware/3090.json` |

## Remaining gaps

Code or tests that are still missing, stubbed or partial. None of these needs credits or hardware to start.

- **Failing test.** `tests/integration/test_store.py::test_synthetic_bundle_regenerates_byte_identical`: the committed `demo/synthetic/manifest.json` no longer matches what `demo/synthetic/build.py` produces (hashes of `presets.json`, `tables/model_calls.json`, `tables/visits.json` and `trace.json` differ). Regenerate the bundle or fix the builder, then re-run the privacy gate on `demo/`.
- **Lint.** E501 in `vigil/settings.py:51`; `ruff format` wants to reformat `.claude/skills/meta-fixture/SKILL.md`.
- **FR-035 3D build.** `vigil/spatial/scan.py` `build_model` raises `SpatialBuildBlockedError`: registration, ground mesh and height grid are not implemented (Open3D is an optional extra). Scale check, world frame, metadata stripping and the GLB size limit are done.
- **FR-042 / NFR-035 local SAM.** `vigil/meta/sam_local.py` `track_concept_local` is a stub (`NotImplementedError`); `VIGIL_SAM_BACKEND` / `VIGIL_TRIAGE_BACKEND` selection has no tests.
- **FR-028 Glimmer server.** Only the client (`vigil/meta/glimmer.py`) exists and is tested; there is no llama.cpp server setup or H-03 run.
- **Live paths.** FR-033: no in-order, once-only window loop. FR-034: no WebRTC view test. No live Meta call has ever run: all Meta fixtures under `tests/fixtures/meta/` are authored, not recorded (T-03).
- **Nov 2 spec changes not yet in code:** FR-044 spatial-origin roles and FR-029 expected windows and check-in (not implemented; `test_roles` and `test_expected_windows` missing); FR-008 origin tagging; FR-010 subject chains and `group:<role>`; FR-012 `applies_to` beyond `anyone` and the r7 window moving to 17:30–06:00 (the `tests/conftest.py` fixture still says 22:00–06:00); FR-013 household-insider touch exception; FR-021 role phrasings (`test_compile_rule_identity_exception_becomes_anyone` encodes the old mapping); FR-022 browser WAV capture, 3 audio fixture buttons and `config/audio_fixtures.json`; FR-036 `fov_nominal` flag and per-model lens profiles; FR-037 SAM landmark proposals; FR-043 / NFR-036 / NFR-037 the $25 judging cap, `VIGIL_JUDGING_END` and the `credit`/`paid` ledger tag; NFR-003 allowlist checks for the track, subject, event and position schemas; validator check 7 (role assertions).
- **Performance tests.** `test_perf.py` does not exist (NFR-005, NFR-030, FR-040 frame rate and load time).
- **Provenance.** NFR-022 mask badges are untested (sentence badges pass).
- **Reproducibility.** NFR-021 timed clean-clone run not done.
- **Schedule doc.** [plans/schedule.md](plans/schedule.md) predates the re-baselined [spec 9.7](spec/vigil-spec.md#97-tasks-in-order-times-pt-tracks-a-pipeline-b-models-and-reasoning-c-app-and-3d-d-field-work-and-evidence) (daylight and night blocks); where they differ, the spec wins and the steps below follow the spec.

## Blocked by Meta API credits

Needs claimed credits, the $140 limit and the budget guard on (see the [credits runbook](runbooks/credits-billing.md) and the `budget-check` skill). Nothing here may run without explicit owner approval.

- T-03 smoke tests (`scripts/smoke_meta.py --live`): one recorded response per model, and the 3 open API questions in [spec 5.14](spec/vigil-spec.md#514-verified-meta-api-facts-this-design-depends-on) (Wonder strict schema, Voice Transcribe batch endpoint with WAV, Spark video with a strict schema).
- Real-data acceptance of FR-004 (SAM accepts real windows), FR-006, FR-007, FR-009, FR-013 (Spark path), FR-014, FR-019 (live mask), FR-020, FR-021 (10 reference phrasings), FR-022 (5 spoken phrasings), FR-023, FR-025, FR-037 (SAM landmark proposals, unless local), FR-043 (estimate within 10% of the Billing page).
- NFR-006, NFR-007, NFR-012, NFR-020, NFR-035 (API side), NFR-036.

## Blocked by field hardware

Needs the 4 Reolink cameras, the iPhone Pro LiDAR, filming with consent, the RTX 3090 with open weights, or a phone for field checks ([field runbooks](runbooks/reolink.md), `field-runbook` skill).

- **Reolink cameras (T-04, T-05, T-26):** FR-030, FR-031, FR-032, FR-033, FR-034; NFR-027, NFR-028, NFR-029, NFR-031 (cellular port check), NFR-033.
- **LiDAR scan and calibration (T-06, T-10, T-12, T-14, T-15, T-17):** FR-035, FR-036, FR-037, FR-038, FR-039, FR-040 (real GLB); NFR-024, NFR-025, NFR-026 (real markers), NFR-030, NFR-032 (real scans to review).
- **Filmed, labelled scenarios (T-07a, T-07b):** FR-002, FR-003, FR-005, FR-008, FR-010, FR-011, FR-017, FR-018, FR-024, FR-027 (real bundle), FR-044; NFR-001, NFR-002 (3 WAV fixtures), NFR-003 (12-story scan), NFR-008, NFR-019, NFR-023.
- **RTX 3090 with open weights (H-02 to H-04):** FR-028, FR-042, NFR-035.
- **ESP32 boards:** FR-041 (deferred past Nov 4).

## Blocked by DGX Spark (D-1, conditional)

Off by default ([runbook](runbooks/dgx-spark-d1.md), [spec 10.4](spec/vigil-spec.md#104-advance-notice-dgx-spark-phase-d-1-conditional-not-yet-triggered)). It runs **only if gate H-02 fails at Mon 22:00 PT**, Tue 08:00 to 12:00 PT, after G1, with the Spark connected by Tue 08:00. If triggered: NFR-034 needs a probe report for the Spark before use, and FR-042's `VIGIL_SAM_BACKEND=remote` (`sam-worker`) needs building. Nothing else depends on it.

## Needs owner action

### Blockers to clear today

From [spec 13.4](spec/vigil-spec.md#134-blockers-to-clear-today), with the extra owner actions found in the bootstrap. Tick here, with the date. The agents cannot do any of these.

- [ ] **Claim the Meta API credits** (deadline Nov 4, 9 PM ET = 6 PM PT; needed Monday for T-03) ([credits runbook](runbooks/credits-billing.md))
- [ ] **Read the Credit Terms**: exact expiry (sets `VIGIL_CREDIT_WINDOW_END`), per-model coverage, what happens at zero balance
- [ ] **Set the $140 Billing limit**, and check the Billing page for any spend since Oct 26; separate dev and sandbox keys
- [ ] **Consent** from everyone who will appear on camera (held privately; statement in [HACKATHON.md](../HACKATHON.md))
- [ ] **Reolink models** for the 4 cameras, firmware, and whether an NVR or Home Hub is used ([reolink runbook](runbooks/reolink.md))
- [ ] An iPhone Pro with LiDAR available before sunset (4:55 PM PT) ([lidar runbook](runbooks/lidar-scan.md))
- [ ] **Track** (Indie or Startup) and **team members** confirmed ([HACKATHON.md](../HACKATHON.md))
- [ ] **`MODEL_API_KEY` GitHub secret** for the sandbox key (CI never makes live calls; needed for T-28 deploy)
- [ ] **Hosting account** for the sandbox deploy (T-28, Tue 23:00)
- [ ] **Make the repository public** before submission (T-30, Wed 14:00 PT) ([submission runbook](runbooks/submission.md))
- [ ] **Judging-period live calls**: spec 13.4 records the owner decision of Nov 2 as ON with a $25 hard cap ($5/day, until Nov 10 23:59 PT). Still open: confirm it, set `VIGIL_CREDIT_WINDOW_END` before Nov 4, 9 PM ET, and approve `VIGIL_ALLOW_PAID=1` on the sandbox only (the judging cap is not implemented yet, see Remaining gaps)
- [ ] **Accept the SAM 3.1 licence on Hugging Face** (H-02, H-04, FR-042)
- [ ] **Approve the torch / GPU install for H-01 to H-04**: `eval/hardware/3090.json` was produced with torch 2.14.1+cu130 from outside the project environment; adding torch (and sam3) to the project needs owner approval ([GPU runbook](runbooks/gpu-h01-h04.md))
- [ ] **Approve the Muse Glimmer 4-bit GGUF download** and the llama.cpp server for H-03 (FR-028)

Already done per spec 13.4: repo access and audit (Nov 2); H-01 run on the RTX 3090 (Ready, Windows 11).

## Next executable steps

In order, from Mon Nov 2, 13:15 PT, following [spec 9.7](spec/vigil-spec.md#97-tasks-in-order-times-pt-tracks-a-pipeline-b-models-and-reasoning-c-app-and-3d-d-field-work-and-evidence) and [spec 10.2](spec/vigil-spec.md#102-hardware-verification-tasks-added-to-section-9). Gates are in the [schedule](plans/schedule.md#gates).

### Monday Nov 2

1. **Now (integrator, no blocker):** regenerate `demo/synthetic` or fix the builder so `test_synthetic_bundle_regenerates_byte_identical` passes; fix the E501 in `vigil/settings.py` and the `ruff format` finding; push and record `<CI run URL>` and `<commit>` here and in the checklists.
2. **Overdue (owner, due 13:00):** T-01 remainder: claim credits, set the $140 limit, pick the track; commit EVAL.md targets.
3. **13:45** T-04 Reolink probe, on-camera privacy masks, audio off; zone `kind`s (egress, perimeter) drawn.
4. **14:30** T-05 restreamer and capture service running before filming; T-03 Meta smoke tests (credits; owner approval).
5. **15:45** T-06 LiDAR loops, 6 landmark pairs per camera, 6 audit markers per camera surveyed, 2 scale distances.
6. **16:50** T-07a daytime scenarios A, B, B′ filmed with consent; labels written and committed before processing; 3 consented WAV fixtures for FR-022. Sunset 16:55.
7. **17:15 to 19:00** night block: T-07b night scenarios A′ and C after about 17:55 (cameras in IR), labels first.
8. **20:00** T-08 privacy, windows and motion gate on real footage; T-10 3D model build (FR-035 code gap must be closed first).
9. **21:00** T-09 SAM tracks for A, B, C (API or local).
10. **22:00** H-02 local SAM 3.1 benchmark, **gate** (needs the licence and the torch approval); T-11 stitching on real tracks.
11. **23:00** T-12 landmark tool and solver; **G1**: footage and labels committed, SAM tracks for A, B, C, GLB built. Overnight: 2 h capture endurance (NFR-029, NFR-033).

In parallel on Monday, with no blocker: implement the Nov 2 spec changes listed under Remaining gaps (FR-044 roles first, since FR-008, FR-010, FR-012, FR-013 and FR-021 depend on it), the judging cap (FR-043), and `test_perf.py`.

### Tuesday Nov 3

12. **08:00 to 12:00** D-1 on the DGX Spark, only if H-02 failed.
13. **09:00** T-13 event builder with origin tagging on real tracks.
14. **10:00** T-14 extrinsics accepted, or switch to the site-plan fallback (cut-off); T-16 appearance notes (credits).
15. **10:30** T-15 audit-harness marker walk (daylight).
16. **11:00** T-17 coverage and blind regions.
17. **12:00** T-18 topology, visits, gaps, roles; T-19 position estimates; H-03 Glimmer benchmark; H-04 local versus API SAM parity.
18. **13:00** T-20 rules, story, validator, verdict (credits); **G2**: scenario C end to end.
19. **15:00** T-21 API, export, cards, synced player on the real bundle.
20. **16:00** T-22 tap-to-protect, voice and typed rules, expected windows and check-in.
21. **17:00** T-23 triage and closed loop. **17:30** T-24 3D viewer.
22. **18:00** T-25 guards (including the judging cap) and telemetry; **G3 MVP freeze**: the 5 blocking P0 suites of [spec 12.1](spec/vigil-spec.md#121-test-suites) pass in CI.
23. **21:00** T-26 Reolink events, live loop, LAN live view.
24. **22:00** T-27 benchmark, audit harness, baseline, unit-economics measurements.
25. **23:00** T-28 deploy the sandbox with the judging config (needs hosting account and `MODEL_API_KEY` secret); **G4**: evidence complete, sandbox opened on a phone.

### Wednesday Nov 4

26. **12:00** T-29 live home clip, video under 3:00, README, HACKATHON.md.
27. **14:00** T-30 final scans and submission ([submission runbook](runbooks/submission.md)); repository public.
28. **18:00 PT (9 PM ET)** credits claim deadline; `VIGIL_CREDIT_WINDOW_END` set and the judging-period configuration recorded.

## Critical risks

Tracked in [spec 13.3](spec/vigil-spec.md#133-critical-risks). Decision points on the calendar are in the [schedule](plans/schedule.md#gates).
