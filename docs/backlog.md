# Backlog

Markdown mirror of the GitHub issues created in [bootstrap phase 4](plans/phase-4-github-backlog.md). This file and GitHub must agree; when they differ, update both. Times are PT. Schedule: [plans/schedule.md](plans/schedule.md).

## Labels

| Group | Label | Meaning |
| --- | --- | --- |
| Track | `track:A` | Pipeline |
| | `track:B` | Models and reasoning |
| | `track:C` | App and 3D |
| | `track:D` | Field work and evidence |
| Priority | `P0` | Required for a working demo |
| | `P1` | Required for a top score |
| | `P2` | Optional; only if G3 passes early |
| Type | `type:task` | Build task T-01 to T-30 |
| | `type:hardware` | H-01 to H-04, D-1 |
| | `type:requirement` | FR-001 to FR-043 (and the NFR tracking issue) |
| | `type:gate` | Gate decisions (optional; gates are milestones) |
| | `type:docs` | Documentation |
| Blocked | `blocked:credits` | Needs billed Meta API calls |
| | `blocked:hardware` | Needs cameras, LiDAR, filming or the RTX 3090 |
| | `blocked:dgx` | Needs the DGX Spark (D-1 only) |
| | `blocked:owner` | Needs an owner action or decision |

## Milestones

| Milestone | Due (PT) | Done when |
| --- | --- | --- |
| G1 | Mon Nov 2, 23:00 | Footage and labels committed; SAM tracks for A, B, C; GLB built |
| G2 | Tue Nov 3, 13:00 | Scenario C end to end, including 3D positions and the gap |
| G3 | Tue Nov 3, 18:00 | MVP freeze: all P0 pass in CI |
| G4 | Tue Nov 3, 23:00 | Evidence complete; sandbox opened on a phone |
| Submission | Wed Nov 4, 14:00 | Submission checklist ticked; submitted |

## Build tasks (30)

| ID | Title | Labels | Milestone | Due | Depends on | Closes |
| --- | --- | --- | --- | --- | --- | --- |
| T-01 | Audit repo; claim credits and set spend limit; pick track; commit EVAL.md targets | `track:D` `P0` `type:task` `blocked:owner` | G1 | Mon 11:30 | none | EVAL pre-registration |
| T-02 | Scaffold and CI | `track:A` `P0` `type:task` | G1 | Mon 12:30 | T-01 | CI steps 1 to 3 |
| T-03 | Meta smoke tests; resolve the 3 open API questions | `track:B` `P0` `type:task` `blocked:credits` `blocked:owner` | G1 | Mon 12:30 | T-01 | Spec 5.14 open items |
| T-04 | Reolink probe; on-camera privacy masks; audio off | `track:D` `P0` `type:task` `blocked:hardware` | G1 | Mon 12:30 | T-01 | FR-030, FR-001 (real config) |
| T-05 | Restreamer and capture service | `track:A` `P0` `type:task` `blocked:hardware` | G1 | Mon 14:00 | T-04 | FR-031, NFR-029 |
| T-06 | Markers, 4 LiDAR loops, checkerboard views, calibration stills | `track:D` `P0` `type:task` `blocked:hardware` | G1 | Mon 16:30 | T-04 | Inputs for FR-035 to FR-037 |
| T-07 | Film 12 scenarios with consent; write labels before processing | `track:D` `P0` `type:task` `blocked:hardware` `blocked:owner` | G1 | Mon 21:00 | T-05 | FR-002 (sync clap), labels for FR-024 |
| T-08 | Privacy, windows, motion gate, privacy scan | `track:A` `P0` `type:task` | G1 | Mon 17:00 | T-05 | FR-003, FR-004, FR-005 |
| T-09 | Meta client, cache, ledger; SAM concept tracking | `track:B` `P0` `type:task` `blocked:credits` | G1 | Mon 18:00 | T-03 | FR-006, FR-023, FR-043 |
| T-10 | 3D model build | `track:C` `P0` `type:task` `blocked:hardware` | G1 | Mon 20:00 | T-06 | FR-035 |
| T-11 | Track stitching and overlays | `track:A` `P0` `type:task` | G1 | Mon 21:00 | T-09 | FR-007 |
| T-12 | Calibration tool and solver | `track:C` `P0` `type:task` `blocked:hardware` | G1 | Mon 23:00 | T-10 | FR-036 |
| T-13 | Event builder | `track:A` `P0` `type:task` | G2 | Tue 09:00 | T-11 | FR-008 |
| T-14 | Extrinsics accepted, or switch to the fallback (Tue 10:00 cut-off) | `track:C` `P0` `type:task` `blocked:hardware` | G2 | Tue 10:00 | T-12 | FR-037 |
| T-15 | Marker walk for 3D accuracy | `track:D` `P0` `type:task` `blocked:hardware` | G2 | Tue 11:00 | T-14 | NFR-025, NFR-026 inputs |
| T-16 | Appearance notes | `track:B` `P0` `type:task` `blocked:credits` | G2 | Tue 10:00 | T-11 | FR-009 |
| T-17 | Coverage and blind regions | `track:C` `P0` `type:task` `blocked:hardware` | G2 | Tue 11:00 | T-14 | FR-038 |
| T-18 | Topology, visits, gaps | `track:B` `P0` `type:task` | G2 | Tue 12:00 | T-13, T-16, T-17 | FR-010, FR-011 |
| T-19 | Position estimates | `track:C` `P0` `type:task` | G2 | Tue 12:00 | T-14 | FR-039 |
| T-20 | Rules, story, validator, verdict | `track:B` `P0` `type:task` `blocked:credits` | G2 | Tue 13:00 | T-18 | FR-012, FR-014, FR-015, FR-016 |
| T-21 | API, export, cards, synced player | `track:C` `P0` `type:task` | G3 | Tue 15:00 | G2 | FR-017, FR-018, FR-027 |
| T-22 | Tap-to-protect, typed rules | `track:B` `P0` `type:task` `blocked:credits` | G3 | Tue 16:00 | G2 | FR-019, FR-021 |
| T-23 | Triage and closed loop | `track:B` `P1` `type:task` `blocked:credits` | G3 | Tue 17:00 | T-20 | FR-013, FR-020, FR-028 |
| T-24 | 3D viewer | `track:C` `P0` `type:task` | G3 | Tue 17:30 | T-21, T-19 | FR-040 |
| T-25 | Guards and telemetry panel | `track:C` `P0` `type:task` | G3 | Tue 18:00 | T-21 | FR-023 (UI), FR-026 |
| T-26 | Reolink events, live loop, LAN live view | `track:A` `P1` `type:task` `blocked:hardware` | G4 | Tue 21:00 | G3 | FR-032, FR-033, FR-034 |
| T-27 | Benchmark, spatial accuracy, baseline | `track:D` `P0` `type:task` `blocked:credits` `blocked:hardware` | G4 | Tue 22:00 | G3, T-15 | FR-024, FR-025, NFR-023 to NFR-026 |
| T-28 | Deploy sandbox; E2E suite in CI | `track:C` `P0` `type:task` `blocked:owner` | G4 | Tue 23:00 | G3 | CI steps 6 to 8, NFR-005, NFR-009 |
| T-29 | Record live home clip; edit video; README; HACKATHON.md | `track:D` `P0` `type:task` `blocked:hardware` `blocked:owner` | Submission | Wed 12:00 | G4 | Video, README, HACKATHON.md |
| T-30 | Final scans and submission | `track:D` `P0` `type:task` `blocked:owner` | Submission | Wed 14:00 | T-29 | [Submission checklist](runbooks/submission.md) |

## Hardware tasks and the conditional phase (5)

The spec assigns these no track; they gate the model backends, so they carry `track:B`.

| ID | Title | Labels | Milestone | Due | Depends on | Closes |
| --- | --- | --- | --- | --- | --- | --- |
| H-01 | GPU probe on the RTX 3090 | `track:B` `P1` `type:hardware` `blocked:hardware` | G1 | Mon 12:30 | none | NFR-034 |
| H-02 | Local SAM 3.1 benchmark (gate Mon 22:00) | `track:B` `P1` `type:hardware` `blocked:hardware` `blocked:owner` | G1 | Mon 22:00 | H-01 | FR-042 (SAM local) |
| H-03 | Local Glimmer benchmark | `track:B` `P1` `type:hardware` `blocked:hardware` | G2 | Tue 12:00 | H-01 | FR-028, FR-042 (triage local) |
| H-04 | Local versus API SAM parity | `track:B` `P1` `type:hardware` `blocked:hardware` `blocked:credits` | G2 | Tue 12:00 | H-02 | NFR-035 |
| D-1 | DGX Spark full-window SAM (conditional; only if H-02 fails) | `track:B` `P1` `type:hardware` `blocked:dgx` `blocked:owner` | G2 | Tue 08:00 to 12:00 | H-02 fails, G1 | FR-042 (remote backend) |

## Requirements (43)

Milestone = the milestone of the task that closes the requirement. Full rows: [functional checklist](requirements/functional.md).

| ID | Title | Labels | Milestone | Closed by |
| --- | --- | --- | --- | --- |
| FR-001 | Camera config loader | `track:A` `P0` `type:requirement` | G1 | T-04, T-08 |
| FR-002 | Clock alignment | `track:A` `P0` `type:requirement` `blocked:hardware` | G1 | T-07, T-08 |
| FR-003 | Privacy at source | `track:A` `P0` `type:requirement` | G1 | T-08 |
| FR-004 | Windowing | `track:A` `P0` `type:requirement` `blocked:credits` | G1 | T-08 |
| FR-005 | Motion gate | `track:A` `P0` `type:requirement` `blocked:hardware` | G1 | T-08 |
| FR-006 | SAM 3.1 tracking | `track:B` `P0` `type:requirement` `blocked:credits` | G1 | T-09 |
| FR-007 | Track stitching | `track:A` `P0` `type:requirement` | G1 | T-11 |
| FR-008 | Event builder | `track:A` `P0` `type:requirement` `blocked:hardware` | G2 | T-13 |
| FR-009 | Appearance notes | `track:B` `P0` `type:requirement` `blocked:credits` | G2 | T-16 |
| FR-010 | Visit assembly | `track:B` `P0` `type:requirement` `blocked:hardware` | G2 | T-18 |
| FR-011 | Gaps | `track:B` `P0` `type:requirement` `blocked:hardware` | G2 | T-18 |
| FR-012 | Rules engine | `track:B` `P0` `type:requirement` | G2 | T-20 |
| FR-013 | Triage | `track:B` `P1` `type:requirement` `blocked:credits` | G3 | T-23 |
| FR-014 | Story | `track:B` `P0` `type:requirement` `blocked:credits` `blocked:hardware` | G2 | T-20 |
| FR-015 | Citation validator | `track:B` `P0` `type:requirement` | G2 | T-20 |
| FR-016 | Verdict | `track:B` `P0` `type:requirement` | G2 | T-20 |
| FR-017 | Visit cards | `track:C` `P0` `type:requirement` | G3 | T-21 |
| FR-018 | Synced player | `track:C` `P0` `type:requirement` | G3 | T-21 |
| FR-019 | Tap-to-protect | `track:B` `P0` `type:requirement` `blocked:credits` | G3 | T-22 |
| FR-020 | Closed loop | `track:B` `P1` `type:requirement` `blocked:credits` `blocked:hardware` | G3 | T-23 |
| FR-021 | Typed rules | `track:B` `P0` `type:requirement` `blocked:credits` | G3 | T-22 |
| FR-022 | Voice rules | `track:B` `P2` `type:requirement` `blocked:credits` | G4 | after G3, only if it passes early |
| FR-023 | Call ledger and telemetry | `track:B` `P0` `type:requirement` | G3 | T-09, T-25 |
| FR-024 | Evaluation harness | `track:D` `P0` `type:requirement` `blocked:hardware` | G4 | T-27 |
| FR-025 | Naive baseline | `track:D` `P1` `type:requirement` `blocked:credits` `blocked:hardware` | G4 | T-27 |
| FR-026 | Sandbox modes and guards | `track:C` `P0` `type:requirement` | G3 | T-25 |
| FR-027 | Export and scenario switcher | `track:C` `P0` `type:requirement` `blocked:hardware` | G3 | T-21 |
| FR-028 | Glimmer triage on the RTX 3090 | `track:B` `P1` `type:requirement` `blocked:hardware` | G3 | T-23, H-03 |
| FR-029 | Owner label "This was expected" | `track:C` `P2` `type:requirement` | G4 | after G3, only if it passes early |
| FR-030 | Reolink connection and probe | `track:D` `P0` `type:requirement` `blocked:hardware` | G1 | T-04 |
| FR-031 | Continuous capture | `track:A` `P0` `type:requirement` `blocked:hardware` | G1 | T-05 |
| FR-032 | Reolink AI events | `track:A` `P1` `type:requirement` `blocked:hardware` | G4 | T-26 |
| FR-033 | Near-real-time loop | `track:A` `P1` `type:requirement` `blocked:hardware` | G4 | T-26 |
| FR-034 | LAN live view | `track:A` `P1` `type:requirement` `blocked:hardware` | G4 | T-26 |
| FR-035 | 3D model build | `track:C` `P0` `type:requirement` `blocked:hardware` | G1 | T-10 |
| FR-036 | Intrinsic calibration | `track:C` `P0` `type:requirement` `blocked:hardware` | G1 | T-12 |
| FR-037 | Extrinsic calibration | `track:C` `P0` `type:requirement` `blocked:hardware` | G2 | T-14 |
| FR-038 | Coverage and blind regions | `track:C` `P0` `type:requirement` `blocked:hardware` | G2 | T-17 |
| FR-039 | 3D position estimates | `track:C` `P0` `type:requirement` `blocked:hardware` | G2 | T-19, T-15 |
| FR-040 | 3D viewer | `track:C` `P0` `type:requirement` `blocked:hardware` | G3 | T-24 |
| FR-041 | Wi-Fi motion annotation (after the hackathon) | `track:A` `P2` `type:requirement` `blocked:hardware` | none (after Nov 4) | not scheduled |
| FR-042 | Local inference backends | `track:B` `P1` `type:requirement` `blocked:hardware` `blocked:owner` | G2 | H-02 to H-04 (D-1 if triggered) |
| FR-043 | Budget guard | `track:B` `P0` `type:requirement` `blocked:credits` `blocked:owner` | G1 | T-09 (before any paid call) |

## Non-functional tracking (1)

| ID | Title | Labels | Milestone | Body |
| --- | --- | --- | --- | --- |
| NFR | NFR-001 to NFR-037 tracking | `type:requirement` | G4 | Checklist linking each row of [non-functional.md](requirements/non-functional.md) |

**Total issues: 79** (30 tasks + 5 hardware and conditional + 43 requirements + 1 NFR tracking).
