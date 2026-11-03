# Backlog

The backlog lives in **GitHub issues [#1 to #80](https://github.com/gabrielromerod/meta-global-ai-developer-hackathon-2026/issues?q=is%3Aissue)**, created and kept in sync from the spec by [`scripts/backlog/backlog.py`](../scripts/backlog/backlog.py) (bootstrap [phase 4](plans/phase-4-github-backlog.md)). GitHub is the source of truth; this page is a read-only snapshot of it taken on Mon Nov 2, 2026. Requirement status lives in the [functional](requirements/functional.md) and [non-functional](requirements/non-functional.md) checklists; times in the [schedule](plans/schedule.md).

## How the issues are made

- `uv run python scripts/backlog/backlog.py build` parses the spec (sections 1, 9.7 and 10.2) into `scripts/backlog/backlog.json`: 44 FRs, 31 build tasks (T-01 to T-30, with T-07 split into T-07a and T-07b) and 5 hardware items (H-01 to H-04, D-1).
- `sync` is a dry run; `sync --apply` creates the labels, milestones and issues with the owner's `gh` login. Issues are matched by their ID prefix (`FR-001:`, `T-07a:`, `H-02:`), so re-running is idempotent. Labels are reconciled; titles and bodies are never overwritten, so edits made on GitHub survive.
- `scripts/backlog/status.json` adds the `offline-done` label to the FRs it lists and closes finished items with a comment. It still lists the 25 FRs that were offline-done at the first sync; the checklists now show 36 *Offline-verified* FRs, so the labels lag until the owner updates `status.json` and re-runs `sync --apply`.

## Labels

| Group | Label | Meaning |
| --- | --- | --- |
| Type | `type:fr` | Functional requirement (spec 1) |
| | `type:task` | Build-plan task (spec 9.7) |
| | `type:hw` | Hardware verification (spec 10.2) and D-1 |
| Priority | `P0`, `P1`, `P2` | FR priority from the spec |
| Track | `track:A` to `track:D` | Pipeline · models and reasoning · app and 3D · field work and evidence |
| Blocked | `blocked:credits`, `blocked:hardware`, `blocked:dgx`, `blocked:owner` | What still stands between the item and its acceptance |
| Status | `offline-done` | Offline part implemented and green in CI on synthetic data; real-data acceptance pending |

## Milestones

| Milestone | Due (PT) | Done when |
| --- | --- | --- |
| G1 | Mon Nov 2, 23:00 | Footage and labels committed; SAM tracks for the demo scenarios; GLB built |
| G2 | Tue Nov 3, 13:00 | Scenario C end to end, including 3D positions and the gap |
| G3 MVP freeze | Tue Nov 3, 18:00 | The 5 blocking P0 suites pass in CI |
| G4 | Tue Nov 3, 23:00 | Evidence complete; sandbox opened on a phone |
| Submission | Wed Nov 4, 14:00 | Spec 13.5 checklist ticked; form submitted |

The G1 and G3 descriptions on GitHub (from `MILESTONES` in `backlog.py`) still say "SAM tracks for A, B, C" and "all P0 pass in CI"; the [schedule](plans/schedule.md#gates) has the revised wording (5 scenarios; the 5 blocking P0 suites). GitHub keeps only the due date, not the time, so the times above are the ones that count.

## Issue index (snapshot, Nov 2)

#1–#44 are FR-001 to FR-044, #45–#75 the build tasks, #76–#80 the hardware items. Closed: #46 (T-02) and #76 (H-01).

| Issue | ID | Title | Pri | Track | Milestone | Blocked | offline-done | State |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| #1 | FR-001 | Camera config | P0 | A | G3 MVP freeze |  | yes | open |
| #2 | FR-002 | Clock alignment | P0 | A | G3 MVP freeze | hardware | yes | open |
| #3 | FR-003 | Privacy at source | P0 | A | G3 MVP freeze |  | yes | open |
| #4 | FR-004 | Windowing | P0 | A | G3 MVP freeze | credits | yes | open |
| #5 | FR-005 | Motion gate | P0 | A | G3 MVP freeze | hardware | yes | open |
| #6 | FR-006 | SAM 3.1 tracking | P0 | A | G3 MVP freeze | credits | yes | open |
| #7 | FR-007 | Track stitching | P0 | A | G3 MVP freeze |  | yes | open |
| #8 | FR-008 | Event builder with origin tagging | P0 | A | G3 MVP freeze |  |  | open |
| #9 | FR-009 | Appearance notes | P0 | B | G3 MVP freeze | credits | yes | open |
| #10 | FR-010 | Visit assembly | P0 | B | G3 MVP freeze | hardware |  | open |
| #11 | FR-011 | Gaps | P0 | B | G3 MVP freeze | hardware | yes | open |
| #12 | FR-012 | Rules engine | P0 | B | G3 MVP freeze |  |  | open |
| #13 | FR-013 | Triage | P1 | B | G4 | credits |  | open |
| #14 | FR-014 | Story | P0 | B | G3 MVP freeze | credits | yes | open |
| #15 | FR-015 | Citation validator | P0 | B | G3 MVP freeze |  | yes | open |
| #16 | FR-016 | Verdict | P0 | B | G3 MVP freeze |  | yes | open |
| #17 | FR-017 | Visit cards | P0 | C | G3 MVP freeze |  | yes | open |
| #18 | FR-018 | Synced player | P0 | C | G3 MVP freeze |  | yes | open |
| #19 | FR-019 | Tap-to-protect | P0 | B | G3 MVP freeze | credits | yes | open |
| #20 | FR-020 | Closed loop | P1 | B | G4 | credits | yes | open |
| #21 | FR-021 | Typed rules | P0 | B | G3 MVP freeze | credits |  | open |
| #22 | FR-022 | Voice rules ("tap and speak") | P0 | B | G3 MVP freeze | credits |  | open |
| #23 | FR-023 | Call ledger and telemetry | P0 | B | G3 MVP freeze |  | yes | open |
| #24 | FR-024 | Evaluation harness | P0 | D | G3 MVP freeze | hardware | yes | open |
| #25 | FR-025 | Naive baseline | P1 | D | G4 | credits | yes | open |
| #26 | FR-026 | Sandbox modes and guards | P0 | C | G3 MVP freeze |  | yes | open |
| #27 | FR-027 | Export and scenario switcher | P0 | C | G3 MVP freeze | hardware |  | open |
| #28 | FR-028 | Glimmer triage | P1 | B | G4 | hardware, owner |  | open |
| #29 | FR-029 | Expected Guest / Delivery Window and owner check-in (was "owner label") | P1 | C | G4 |  |  | open |
| #30 | FR-030 | Reolink connection and probe | P0 | A | G3 MVP freeze | hardware | yes | open |
| #31 | FR-031 | Continuous capture | P0 | A | G3 MVP freeze | hardware | yes | open |
| #32 | FR-032 | Reolink AI events | P1 | A | G4 | hardware | yes | open |
| #33 | FR-033 | Near-real-time loop | P1 | A | G4 | credits, hardware |  | open |
| #34 | FR-034 | LAN live view | P1 | C | G4 | hardware |  | open |
| #35 | FR-035 | 3D model build | P0 | C | G3 MVP freeze | hardware |  | open |
| #36 | FR-036 | Intrinsics | P0 | C | G3 MVP freeze | hardware |  | open |
| #37 | FR-037 | Extrinsics from landmarks | P0 | C | G3 MVP freeze | hardware |  | open |
| #38 | FR-038 | Coverage and blind regions | P0 | C | G3 MVP freeze | hardware | yes | open |
| #39 | FR-039 | 3D position estimates | P0 | C | G3 MVP freeze | hardware | yes | open |
| #40 | FR-040 | 3D viewer | P0 | C | G3 MVP freeze | hardware |  | open |
| #41 | FR-041 | Wi-Fi motion annotation (after the hackathon): ESPectre over MQTT, ann | P2 | D | none | hardware |  | open |
| #42 | FR-042 | Local inference backends | P1 | B | G4 | hardware, owner |  | open |
| #43 | FR-043 | Budget guard | P0 | B | G3 MVP freeze | credits |  | open |
| #44 | FR-044 | Spatial origin roles (new; no identification) | P0 | B | G3 MVP freeze | hardware |  | open |
| #45 | T-01 | Audit repo ✓; claim credits and set the spend limit; pick track; commit EVAL.md targets |  | D | G1 | owner |  | open |
| #46 | T-02 | Scaffold and CI ✓ |  | A | G1 |  |  | closed |
| #47 | T-04 | Reolink probe; on-camera privacy masks; audio off |  | D | G1 | hardware |  | open |
| #48 | T-05 | Restreamer and capture service |  | A | G1 | hardware |  | open |
| #49 | T-03 | Meta smoke tests; resolve the 3 open API questions (incl. Voice WAV) |  | B | G1 | credits |  | open |
| #50 | T-06 | LiDAR loops; 6 landmark pairs per camera (nominal FOV); place and survey 6 audit marker… |  | D | G1 | hardware |  | open |
| #51 | T-07a | Film daytime scenarios A, B, B′ (and the other daytime benchmark scenarios) with consen… |  | D | G1 | hardware, owner |  | open |
| #52 | T-07b | Film night scenarios A′ (front-door egress, side-gate touch after 17:30) and C (side-al… |  | D | G1 | hardware, owner |  | open |
| #53 | T-08 | Privacy, windows, motion gate on real footage |  | A | G1 |  |  | open |
| #54 | T-09 | SAM concept tracking on the 5 demo scenarios |  | B | G1 |  |  | open |
| #55 | T-10 | 3D model build |  | C | G1 | hardware |  | open |
| #56 | T-11 | Track stitching and overlays on real tracks |  | A | G1 |  |  | open |
| #57 | T-12 | Landmark tool (SAM proposals + mesh clicks) and solver |  | C | G1 | hardware |  | open |
| #58 | T-13 | Event builder with origin tagging (real tracks) |  | A | G2 |  |  | open |
| #59 | T-15 | Audit-harness marker walk (daylight) |  | D | G2 | hardware |  | open |
| #60 | T-14 | Extrinsics from landmarks accepted, or switch to the fallback |  | C | G2 | hardware |  | open |
| #61 | T-16 | Appearance notes |  | B | G2 | credits |  | open |
| #62 | T-17 | Coverage and blind regions |  | C | G2 | hardware |  | open |
| #63 | T-18 | Topology, visits, gaps, roles |  | B | G2 |  |  | open |
| #64 | T-19 | Position estimates |  | C | G2 | hardware |  | open |
| #65 | T-20 | Rules (with `applies_to`), story, validator (check 7), verdict |  | B | G2 | credits |  | open |
| #66 | T-21 | API, export, cards, synced player |  | C | G3 MVP freeze |  |  | open |
| #67 | T-22 | Tap-to-protect; voice and typed rules (mic, 3 audio fixture buttons, typing); expected… |  | B | G3 MVP freeze | credits |  | open |
| #68 | T-23 | Triage and closed loop |  | B | G3 MVP freeze | hardware |  | open |
| #69 | T-24 | 3D viewer |  | C | G3 MVP freeze |  |  | open |
| #70 | T-25 | Guards (incl. judging cap) and telemetry panel |  | C | G3 MVP freeze |  |  | open |
| #71 | T-26 | Reolink events, live loop, LAN live view |  | A | G4 | hardware |  | open |
| #72 | T-27 | Benchmark, audit harness, baseline, unit-economics measurements (11.9) |  | D | G4 | credits, hardware |  | open |
| #73 | T-28 | Deploy sandbox with judging config (`VIGIL_ALLOW_PAID=1` from window end, `VIGIL_JUDGIN… |  | C | G4 | owner |  | open |
| #74 | T-29 | Record live home clip; edit video; README; HACKATHON.md |  | D | Submission | hardware, owner |  | open |
| #75 | T-30 | Final scans and submission |  | D | Submission | owner |  | open |
| #76 | H-01 | GPU probe |  | B | G1 |  |  | closed |
| #77 | H-02 | Local SAM 3.1 benchmark |  | B | G1 | hardware, owner |  | open |
| #78 | H-03 | Local Glimmer benchmark |  | B | G2 | hardware, owner |  | open |
| #79 | H-04 | Local versus API SAM parity |  | B | G2 | credits |  | open |
| #80 | D-1 | DGX Spark full-window SAM 3.1 (conditional: only if gate H-02 fails) |  | B | G2 | dgx |  | open |
