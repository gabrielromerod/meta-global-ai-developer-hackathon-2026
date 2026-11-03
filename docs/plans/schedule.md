# Schedule: Mon Nov 2 to Wed Nov 4, 2026 (PT)

Derived from the spec's [task table (9.7)](../spec/vigil-spec.md#97-tasks-in-order-times-pt-tracks-a-pipeline-b-models-and-reasoning-c-app-and-3d-d-field-work-and-evidence), [hardware tasks (10.2)](../spec/vigil-spec.md#102-hardware-verification-tasks-added-to-section-9) and [phase D-1 (10.4)](../spec/vigil-spec.md#104-advance-notice-dgx-spark-phase-d-1-conditional-not-yet-triggered). All times are Pacific Time. The bootstrap phases ([phase 0](phase-0-baseline.md) to [phase 5](phase-5-readiness.md)) run on Monday around T-01 and T-02.

**Tracks:** A pipeline · B models and reasoning · C app and 3D · D field work and evidence.

**Dependency columns** (✔ = the task cannot be finished without it):

- **Credits:** billed Meta Model API calls (credits claimed, $140 limit set, budget guard on).
- **Hardware:** field hardware or field work: Reolink cameras, iPhone Pro LiDAR, filming with consent, RTX 3090.
- **DGX:** the DGX Spark (phase D-1 only).
- **Owner:** an owner action or decision (account, billing, consent, licence, host, submission).

## Monday Nov 2

| Time | Task | Track | Depends on | Credits | Hardware | DGX | Owner | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 11:30 | T-01 Audit; claim credits and set spend limit; pick track; commit EVAL.md targets incl. NFR-025, NFR-026 | D | none | | | | ✔ claim, limit, track | Audit done ([phase 0](phase-0-baseline.md)); EVAL.md targets committed; owner items open |
| 12:30 | T-02 Scaffold and CI | A | T-01 | | | | | CI green: ruff, pytest, gitleaks ([phase 1](phase-1-foundation.md)) |
| 12:30 | T-03 Meta smoke tests; resolve the 3 open API questions | B | T-01 | ✔ | | | ✔ keys | One recorded response per model; findings in spec 5.14 |
| 12:30 | T-04 Reolink probe; on-camera privacy masks; audio off | D | T-01 | | ✔ cameras | | ✔ camera models, NVR | FR-030 passes; mask confirmed in RTSP ([runbook](../runbooks/reolink.md)) |
| 12:30 | H-01 GPU probe | (hw) | none | | ✔ RTX 3090 | | ✔ OS / WSL2 | `eval/hardware/3090.json` ([runbook](../runbooks/gpu-h01-h04.md)) |
| 14:00 | T-05 Restreamer and capture service | A | T-04 | | ✔ | | | 30 min test without gaps; 2 h overnight (NFR-029) |
| 16:30 (before dusk) | T-06 Markers, 4 LiDAR loops, checkerboard views, calibration stills | D | T-04 | | ✔ iPhone Pro, markers, board | | | Exports on disk; 2 distances measured ([runbook](../runbooks/lidar-scan.md)) |
| 17:00 | T-08 Privacy, windows, motion gate, privacy scan | A | T-05 | | (real footage for acceptance) | | | FR-003 to FR-005 tests pass |
| 18:00 | T-09 Meta client, cache, ledger; SAM concept tracking | B | T-03 | ✔ fixtures from T-03 | | | | FR-006, FR-023 pass on fixtures |
| 20:00 | T-10 3D model build | C | T-06 | | ✔ scan (Open3D extra) | | | FR-035 passes |
| 21:00 | T-07 Film 12 scenarios with consent; labels before processing | D | T-05 | | ✔ filming | | ✔ consent | 12 labelled scenarios; consent held privately |
| 21:00 | T-11 Track stitching and overlays | A | T-09 | | | | | FR-007 passes |
| **22:00** | **H-02 Local SAM 3.1 benchmark (gate)** | (hw) | H-01 | | ✔ RTX 3090 + weights | | ✔ HF licence | Gate decision: 3090 passes, or API SAM ([runbook](../runbooks/gpu-h01-h04.md#gate-h-02-mon-2200-pt)) |
| 23:00 | T-12 Calibration tool and solver | C | T-10 | | ✔ checkerboard views | | | FR-036 passes for 4 cameras |
| **23:00** | **G1** | all | | | | | | Footage and labels committed; SAM tracks for A, B, C; GLB built |

Overnight: 2 h capture endurance test (NFR-029, NFR-033); notice for D-1 issued at 22:00 only if H-02 fails.

## Tuesday Nov 3

| Time | Task | Track | Depends on | Credits | Hardware | DGX | Owner | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 08:00 to 12:00 | D-1 (conditional) Full-window SAM on the DGX Spark | (hw) | H-02 fails, G1 | | | ✔ | ✔ connect by 08:00 | Validated or powered down ([runbook](../runbooks/dgx-spark-d1.md)) |
| 09:00 | T-13 Event builder | A | T-11 | | | | | FR-008 passes |
| **10:00 cut-off** | **T-14 Extrinsics accepted, or switch to the fallback** | C | T-12 | | ✔ markers, stills | | | FR-037 passes, or site-plan fallback active ([runbook](../runbooks/calibration.md#the-tue-1000-cut-off)) |
| 10:00 | T-16 Appearance notes | B | T-11 | ✔ Spark | | | | FR-009 passes |
| 11:00 | T-15 Marker walk for 3D accuracy | D | T-14 | | ✔ | | | Recordings of 6 markers per camera |
| 11:00 | T-17 Coverage and blind regions | C | T-14 | | ✔ walk test | | | FR-038 passes |
| 12:00 | T-18 Topology, visits, gaps | B | T-13, T-16, T-17 | | (labelled set) | | | FR-010, FR-011 pass |
| 12:00 | T-19 Position estimates | C | T-14 | | (real calibration) | | | FR-039 unit tests pass |
| 12:00 | H-03 Local Glimmer benchmark | (hw) | H-01 | | ✔ RTX 3090 + GGUF | | | Tokens/s, VRAM, JSON-valid rate, agreement with Spark |
| 12:00 | H-04 Local versus API SAM parity | (hw) | H-02 | ✔ API side | ✔ RTX 3090 | | | Mean IoU and ID switches (NFR-035) |
| 13:00 | T-20 Rules, story, validator, verdict | B | T-18 | ✔ Wonder | | | | FR-012, FR-014 to FR-016 pass |
| **13:00** | **G2** | all | | | | | | Scenario C end to end, with 3D positions and the gap |
| 15:00 | T-21 API, export, cards, synced player | C | G2 | | | | | FR-017, FR-018, FR-027 pass |
| 16:00 | T-22 Tap-to-protect, typed rules | B | G2 | ✔ SAM image, Spark | | | | FR-019, FR-021 pass |
| 17:00 | T-23 Triage and closed loop | B | T-20 | ✔ Spark fallback | (Glimmer on 3090) | | | FR-013, FR-020 pass |
| 17:30 | T-24 3D viewer | C | T-21, T-19 | | (real GLB) | | | FR-040 passes |
| 18:00 | T-25 Guards and telemetry panel | C | T-21 | | | | | FR-023 UI, FR-026 pass |
| **18:00** | **G3 MVP freeze** | all | | | | | | All P0 pass in CI |
| 21:00 | T-26 Reolink events, live loop, LAN live view | A | G3 | (if API SAM) | ✔ cameras | | | FR-032 to FR-034 pass |
| 22:00 | T-27 Benchmark, spatial accuracy, baseline | D | G3, T-15 | ✔ | ✔ GPU, footage | | | Results committed, misses included |
| 23:00 | T-28 Deploy sandbox; E2E suite in CI | C | G3 | (sandbox live cap) | | | ✔ host account, secrets | Live URL passes E2E from CI |
| **23:00** | **G4** | all | | | | | | Evidence complete; sandbox opened on a phone |

## Wednesday Nov 4

| Time | Task | Track | Depends on | Credits | Hardware | DGX | Owner | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12:00 | T-29 Record live home clip; edit video; README; HACKATHON.md | D | G4 | (video live calls) | ✔ live home mode | | ✔ video, consent statement | Video under 3:00; link tested privately |
| **14:00** | **T-30 Final scans and submission** | D | T-29 | | | | ✔ submit form | [Submission checklist](../runbooks/submission.md) ticked; submitted |
| 18:00 (= 9 PM ET) | Credits claim deadline and judging-period live-call decision | owner | | ✔ | | | ✔ | Credits claimed earlier (needed Monday); decision recorded ([runbook](../runbooks/credits-billing.md)) |

## Gates

| Gate | When (PT) | Pass condition | If it fails |
| --- | --- | --- | --- |
| H-02 | Mon 22:00 | A 10 s window processed in chunks in 10 s or less; at most 1 extra ID switch per window versus the API | Live mode and benchmark use API SAM; D-1 becomes optional (notice issued) |
| G1 | Mon 23:00 | Footage and labels committed; SAM tracks for A, B, C; GLB built | The gates decide the cuts (spec 9 intro); team decision, record it here |
| Spatial cut-off | Tue 10:00 | Extrinsics accepted (FR-037) | Switch to the measured site-plan fallback and keep going (spec 0, 7) |
| G2 | Tue 13:00 | Scenario C end to end | Team decision; if one person builds alone, T-25 and the baseline (FR-025) become optional (spec 9 intro) |
| G3 | Tue 18:00 | All P0 pass in CI (MVP freeze) | P2 is built only if G3 passes early (spec 1) |
| G4 | Tue 23:00 | Evidence complete; sandbox on a phone | Team decision; the README must link the 90-second fallback recording either way (spec 4 fallbacks) |
| Submission | Wed 14:00 | Submission checklist ticked | Submit; EVAL.md reports misses (spec 2, 12) |

## Blockers (spec 13.4)

Owner actions that hold the schedule. Tracked in [readiness](../readiness.md#blockers-to-clear-today).

| Blocker | Blocks | Kind |
| --- | --- | --- |
| Claim credits; set the $140 Billing limit; separate dev and sandbox keys | T-03 and every task marked Credits | owner, credits |
| Read the Credit Terms (expiry, per-model coverage, zero balance) | NFR-037 window end; judging-period decision | owner |
| Reolink models and any NVR or Home Hub | T-04, T-05, T-26 | owner, hardware |
| iPhone Pro with LiDAR before dusk Monday | T-06, T-10, T-12 to T-17 | hardware |
| Track (Indie or Startup) and team members | T-30, HACKATHON.md | owner |
| Consent from everyone on camera | T-07, T-15, T-29 | owner |
| H-01 on the 3090; workstation OS (Windows with WSL2, or Linux) | H-02 to H-04, FR-028, FR-042 | hardware, owner |
| Live calls during judging: cached-only (default) or a separate cap | Sandbox config after Nov 4 | owner |
