# Schedule: Mon Nov 2 to Wed Nov 4, 2026 (PT)

Derived from the revised [task table (spec 9.7)](../spec/vigil-spec.md#97-tasks-in-order-times-pt-tracks-a-pipeline-b-models-and-reasoning-c-app-and-3d-d-field-work-and-evidence), [hardware tasks (10.2)](../spec/vigil-spec.md#102-hardware-verification-tasks-added-to-section-9) and [phase D-1 (10.4)](../spec/vigil-spec.md#104-advance-notice-dgx-spark-phase-d-1-conditional-not-yet-triggered), re-baselined on Nov 2 ([change set](../spec/changes/2026-11-02-business-corrections.md)). All times are Pacific Time. Sunset Mon Nov 2 is **4:55 PM PT** (owner-supplied; about 4:59 PM if the house is in Los Angeles), so field tasks that need daylight come first, and the night scenarios are filmed after about 17:55 (nautical dusk), with the cameras in IR. Software tasks whose offline code already landed on Nov 2 keep their slot for **real-data acceptance only**. Each task is a GitHub issue ([backlog](../backlog.md)).

**Tracks:** A pipeline · B models and reasoning · C app and 3D · D field work and evidence. **Needs:** credits (billed Meta calls), hardware (cameras, LiDAR, filming, RTX 3090), DGX (phase D-1 only), owner (account, billing, consent, licence, host, submission).

## Done

| Task | Evidence |
| --- | --- |
| T-01 audit part ✓ (the owner part stays open, see below) | [audit/2026-11-02-repo-audit.md](../audit/2026-11-02-repo-audit.md) |
| T-02 Scaffold and CI ✓ | Commit `3d53d05`; issue #46 closed; latest green run [41587853241](https://github.com/gabrielromerod/meta-global-ai-developer-hackathon-2026/actions/runs/41587853241) on `46c5b68` |
| H-01 GPU probe ✓ | `eval/hardware/3090.json`: Ready (torch 2.14.1 for CUDA 13.0, about 64 TFLOPS burn, 67 °C peak); issue #76 closed |

## Monday Nov 2

| Done by | Task | Track | Depends on | Needs | Done when |
| --- | --- | --- | --- | --- | --- |
| 13:00 | T-01 rest: claim credits, set the $140 spend limit, pick the track, commit EVAL.md targets | D | none | owner | Credits claimed; $140 limit set; targets committed |
| **Daylight block 13:00–16:55** | | | | | |
| **13:45** | T-04 Reolink probe; on-camera privacy masks; audio off | D | T-01 | hardware, owner (camera models, NVR) | FR-030 passes; mask confirmed in the RTSP stream; zone `kind`s drawn (egress, perimeter) ([runbook](../runbooks/reolink.md)) |
| 14:30 | T-05 Restreamer and capture service | A | T-04 | hardware | Capturing before T-07a starts; 2 h test runs overnight. Fallback: NVR or camera recording export |
| 14:30 | T-03 Meta smoke tests; the 3 open API questions (incl. Voice Transcribe with WAV) | B | T-01 (credits) | credits, owner | One recorded response per model |
| **15:45** | T-06 LiDAR loops; **6 landmark pairs per camera** (nominal FOV); place and survey **6 audit markers per camera**; 2 scale distances | D | T-04 | hardware | Exports on disk; landmarks visible in each still; marker survey sheet written ([runbook](../runbooks/lidar-scan.md)) |
| **16:50** | **T-07a** Film daytime scenarios **A, B, B′** (and the other daytime benchmark scenarios) with consent; labels before processing; record the 3 voice fixtures | D | T-05 | hardware, owner (consent) | Labelled before sunset; A filmed before B and B′, with nobody crossing the front-door egress polygon from outside in the 10 min before A; 3 consented WAVs in `demo/voice/`, SHA-256 in `config/audio_fixtures.json` |
| **Night block: 17:15 setup; filming after about 17:55 (IR) until 19:00** | | | | | |
| **19:00** | **T-07b** Film night scenarios **A′** (front-door egress, side-gate touch after 17:30) and **C** (side-alley entry, gate touch, 41 s shed gap), and the other night scenarios; optional labelled take of a household member returning through the side alley without a check-in | D | T-07a | hardware, owner (consent) | Labelled; r7's 17:30–06:00 window covers A′ and C; the A′ actor goes inside at least 10 min before the take (egress voiding) |
| 20:00 | T-08 Privacy, windows, motion gate on real footage | A | T-07a | (real footage) | FR-003 to FR-005 pass on real footage |
| 20:00 | T-10 3D model build | C | T-06 | hardware (scan; Open3D extra) | FR-035 passes (the build code is still blocked, see [readiness](../readiness.md#remaining-gaps-no-credits-or-hardware-needed-to-start)) |
| 21:00 | T-09 SAM concept tracking on the 5 demo scenarios | B | T-03, T-07b | credits or local GPU | Real SAM tracks for A, A′, B, B′, C |
| **22:00** | **H-02 Local SAM 3.1 benchmark (gate)** | B | H-01 | hardware, owner (HF licence, torch install) | Chunk settings chosen, or API fallback ([runbook](../runbooks/gpu-h01-h04.md)) |
| 22:00 | T-11 Track stitching and overlays on real tracks | A | T-09 | | FR-007 passes on real tracks |
| 23:00 | T-12 Landmark tool (SAM proposals + mesh clicks) and solver | C | T-10 | hardware | FR-036 (nominal or profile) for 4 cameras |
| **23:00** | **G1** | all | | | Footage and labels committed; SAM tracks for A, A′, B, B′, C; GLB built |

Overnight: 2 h capture endurance (NFR-029, NFR-033); the D-1 notice is issued at 22:00 only if H-02 fails.

## Tuesday Nov 3

| Done by | Task | Track | Depends on | Needs | Done when |
| --- | --- | --- | --- | --- | --- |
| 08:00–12:00 | D-1 (conditional) Full-window SAM on the DGX Spark | B | H-02 fails, G1 | DGX, owner | Validated or powered down ([runbook](../runbooks/dgx-spark-d1.md)) |
| 09:00 | T-13 Event builder with origin tagging (real tracks) | A | T-11 | | FR-008 on real tracks; origins match labels |
| **10:00 cut-off** | **T-14 Extrinsics from landmarks accepted, or switch to the fallback** | C | T-12 | hardware | FR-037 passes, or the site-plan fallback is active ([runbook](../runbooks/calibration.md#the-tue-1000-cut-off)) |
| 10:00 | T-16 Appearance notes | B | T-11 | credits | FR-009 passes |
| 10:30 | T-15 Audit-harness marker walk (daylight) | D | T-06 | hardware | Person on 6 markers per camera, recorded |
| 11:00 | T-17 Coverage and blind regions | C | T-14 | hardware | FR-038 passes |
| 12:00 | T-18 Topology, visits, gaps, **roles** | B | T-13, T-16, T-17 | (labelled set) | FR-010, FR-011, FR-044 pass on real data |
| 12:00 | T-19 Position estimates | C | T-14 | (real calibration) | FR-039 passes; audit radii applied |
| 12:00 | H-03 Local Glimmer benchmark | B | H-01 | hardware, owner (GGUF) | Tokens/s, VRAM, JSON-valid rate, agreement with Spark |
| 12:00 | H-04 Local versus API SAM parity | B | H-02 | credits, hardware | Mean IoU and ID switches (NFR-035) |
| 13:00 | T-20 Rules (with `applies_to`), story, validator (check 7), verdict | B | T-18 | credits | FR-012, FR-014 to FR-016 pass |
| **13:00** | **G2** | all | | | Scenario C end to end, including 3D positions, the gap and its role |
| 15:00 | T-21 API, export, cards, synced player | C | G2 | | FR-017, FR-018, FR-027 pass |
| 16:00 | T-22 Tap-to-protect; **voice and typed rules** (mic, 3 audio fixture buttons, typing); expected windows and owner check-in | B | G2 | credits | FR-019, FR-021, FR-022, FR-029 pass |
| 17:00 | T-23 Triage and closed loop | B | T-20 | (Glimmer on 3090) | FR-013, FR-020 pass |
| 17:30 | T-24 3D viewer | C | T-21, T-19 | (real GLB) | FR-040 passes |
| 18:00 | T-25 Guards (incl. judging cap) and telemetry panel | C | T-21 | | FR-023 UI, FR-026, FR-043 pass |
| **18:00** | **G3 MVP freeze** | all | | | The 5 blocking P0 CI suites ([spec 12.1](../spec/vigil-spec.md#121-test-suites)) pass |
| 21:00 | T-26 Reolink events, live loop, LAN live view | A | G3 | hardware | FR-032 to FR-034 pass |
| 22:00 | T-27 Benchmark, audit harness, baseline, unit-economics measurements (11.9) | D | G3, T-15 | credits, hardware | Results committed, misses included; Tier 0 / Tier 1 rates measured |
| 23:00 | T-28 Deploy the sandbox with the judging config (`VIGIL_ALLOW_PAID=1` from window end, `VIGIL_JUDGING_CAP_USD=25`, `VIGIL_JUDGING_END`); E2E in CI | C | G3 | owner (host, secrets) | Live URL passes E2E from CI; the judging cap is verified by test |
| **23:00** | **G4** | all | | | Evidence complete; sandbox opened on a phone |

## Wednesday Nov 4

| Done by | Task | Track | Depends on | Needs | Done when |
| --- | --- | --- | --- | --- | --- |
| 12:00 | T-29 Record live home clip; edit video; README; HACKATHON.md | D | G4 | hardware, owner | Video under 3:00, link tested privately |
| **14:00** | **T-30 Final scans and submission** | D | T-29 | owner | [Spec 13.5 checklist](../runbooks/submission.md) ticked; submitted |
| 18:00 (9 PM ET) | Credits claim deadline; `VIGIL_CREDIT_WINDOW_END` set; Billing second stop checked | owner | | credits, owner | Recorded in the [credits runbook](../runbooks/credits-billing.md) |

Judging runs Nov 5–10 PT with live calls on under the $25 cap; no paid call after `VIGIL_JUDGING_END` (Nov 10, 23:59 PT).

## Gates

| Gate | When (PT) | Pass condition | If it fails |
| --- | --- | --- | --- |
| H-02 | Mon 22:00 | A 10 s window processed in chunks in 10 s or less; at most 1 extra ID switch per window versus the API | Live mode and benchmark use API SAM; D-1 becomes optional (notice issued) |
| G1 | Mon 23:00 | Footage and labels committed; SAM tracks for A, A′, B, B′, C; GLB built | Team decision on cuts; record it here |
| Spatial cut-off | Tue 10:00 | Landmark extrinsics accepted (FR-037) | Switch to the measured site-plan fallback and keep going (spec 0, 7) |
| G2 | Tue 13:00 | Scenario C end to end, including its role | Team decision; T-25 and the baseline (FR-025) can become optional |
| G3 | Tue 18:00 | The 5 blocking P0 suites green in CI (MVP freeze); report-only reds have an open issue | P2 is built only if G3 passes early |
| G4 | Tue 23:00 | Evidence complete; sandbox on a phone | Team decision; the README links the 90-second fallback recording either way |
| Submission | Wed 14:00 | Spec 13.5 checklist ticked | Submit; EVAL.md reports misses |

## Blockers (spec 13.4)

Owner actions that hold the schedule; tracked with tick boxes in [readiness](../readiness.md#blockers-to-clear-today).

| Blocker | Blocks | Kind |
| --- | --- | --- |
| Claim credits; set the $140 Billing limit; separate dev and sandbox keys | T-03 and every task that needs credits | owner, credits |
| Read the Credit Terms (expiry, per-model coverage, zero balance) | `VIGIL_CREDIT_WINDOW_END`, the judging-cap switch | owner |
| Reolink models and any NVR or Home Hub | T-04, T-05, T-26 | owner, hardware |
| iPhone Pro with LiDAR before sunset Monday | T-06, T-10, T-12 to T-17 | hardware |
| Consent from everyone on camera or in a voice fixture | T-07a, T-07b, T-15, T-29 | owner |
| Track (Indie or Startup) and team members | T-30, HACKATHON.md | owner |
| SAM 3.1 licence, torch install, Glimmer GGUF | H-02 to H-04, FR-028, FR-042 | owner, hardware |
| Hosting account and `MODEL_API_KEY` secret | T-28 | owner |
