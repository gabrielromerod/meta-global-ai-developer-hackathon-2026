# Vigil documentation

Everything here is derived from the engineering specification, [`spec/vigil-spec.md`](spec/vigil-spec.md). When a document and the spec disagree, the spec wins, except where a document records a deliberate, owner-approved deviation (each one is labelled **Deviation**).

Documents that teams tick (checklists, status tables) live here; explanations stay in the spec and are linked by section.

## Index

| Document | What it is for |
| --- | --- |
| [spec/vigil-spec.md](spec/vigil-spec.md) | The source of truth: requirements, architecture, plan, budget and unit economics, quality, readiness (read-only for workstreams) |
| [spec/changes/2026-11-02-business-corrections.md](spec/changes/2026-11-02-business-corrections.md) | The Nov 2 change set: spatial-origin roles, voice rules back to P0, landmark onboarding versus audit harness, unit economics, live calls during judging, re-baselined schedule |
| [audit/2026-11-02-repo-audit.md](audit/2026-11-02-repo-audit.md) | Section 0 repo audit: no prior work, every requirement starts at *Not verified* |
| [requirements/functional.md](requirements/functional.md) | Checklist of FR-001 to FR-044 with module, test, demo evidence, blocker and status |
| [requirements/non-functional.md](requirements/non-functional.md) | Checklist of NFR-001 to NFR-037 with target, validation, blocker and status |
| [use-cases.md](use-cases.md) | Actors, UC-01 to UC-11, journeys J1 to J4 and the global error table, condensed with links |
| [demo-happy-path.md](demo-happy-path.md) | Scenarios A, A′, B, B′, C (A′ versus C), the 8-step judge sequence with voice in step 6, fallback notices, evidence per criterion and a rehearsal checklist |
| [architecture/README.md](architecture/README.md) | All 14 Mermaid diagrams from the spec, each with an explanation and the files it maps to |
| [plans/phase-0-baseline.md](plans/phase-0-baseline.md) | Bootstrap phase 0: baseline and audit |
| [plans/phase-1-foundation.md](plans/phase-1-foundation.md) | Bootstrap phase 1: foundation, shared contracts and CI |
| [plans/phase-2-parallel-core.md](plans/phase-2-parallel-core.md) | Bootstrap phase 2: parallel offline core, docs and tooling |
| [plans/phase-3-ci-and-h01.md](plans/phase-3-ci-and-h01.md) | Bootstrap phase 3: CI completion and the H-01 GPU probe |
| [plans/phase-4-github-backlog.md](plans/phase-4-github-backlog.md) | Bootstrap phase 4: GitHub issues, labels and milestones |
| [plans/phase-5-readiness.md](plans/phase-5-readiness.md) | Bootstrap phase 5: verification and readiness review |
| [plans/schedule.md](plans/schedule.md) | Revised spec 9.7 timeline: daylight and night blocks, T-07a and T-07b, H-01 to H-04, D-1, gates G1 to G4, blockers |
| [backlog.md](backlog.md) | Snapshot of GitHub issues #1 to #80 (made by `scripts/backlog/backlog.py`): labels, milestones, issue index |
| [conventions.md](conventions.md) | Toolchain, ownership boundaries, TDD, markers, commits, branching, privacy, budget, definition of done |
| [readiness.md](readiness.md) | Current readiness snapshot: evidence (tests, CI run), remaining gaps, blockers, next steps |
| [runbooks/reolink.md](runbooks/reolink.md) | Probe the cameras, on-camera privacy masks, zone kinds to draw, audio off, stream URLs, restreamer |
| [runbooks/lidar-scan.md](runbooks/lidar-scan.md) | Landmarks, 6 surveyed audit markers per camera, scan loops, Scaniverse export, scale check, metadata strip |
| [runbooks/calibration.md](runbooks/calibration.md) | Product path (nominal FOV, 6 SAM-proposed landmarks, PnP), optional lens profile per camera model, audit harness, Tue 10:00 cut-off |
| [runbooks/gpu-h01-h04.md](runbooks/gpu-h01-h04.md) | RTX 3090 tasks H-01 to H-04, WSL2 note, gate H-02 at Mon 22:00 |
| [runbooks/dgx-spark-d1.md](runbooks/dgx-spark-d1.md) | Conditional DGX Spark phase D-1: setup and validation (off by default) |
| [runbooks/credits-billing.md](runbooks/credits-billing.md) | Claiming credits, Credit Terms, $140 limit, keys, daily reconciliation, live calls during judging ($25 cap, Billing second stop) |
| [runbooks/submission.md](runbooks/submission.md) | The Wed 2:00 PM PT submission checklist (spec 13.5) |

Top-level documents: [../README.md](../README.md) (project front page), [../EVAL.md](../EVAL.md) (pre-registered targets and results), [../HACKATHON.md](../HACKATHON.md) (build window, prior work, contributors, consent).
