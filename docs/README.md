# Vigil documentation

Everything here is derived from the engineering specification, [`spec/vigil-spec.md`](spec/vigil-spec.md). When a document and the spec disagree, the spec wins, except where a document records a deliberate, owner-approved deviation (each one is labelled **Deviation**).

Documents that teams tick (checklists, status tables) live here; explanations stay in the spec and are linked by section.

## Index

| Document | What it is for |
| --- | --- |
| [spec/vigil-spec.md](spec/vigil-spec.md) | The source of truth: requirements, architecture, plan, budget, quality, readiness (read-only for workstreams) |
| [audit/2026-11-02-repo-audit.md](audit/2026-11-02-repo-audit.md) | Section 0 repo audit: no prior work, every requirement starts at *Not verified* |
| [requirements/functional.md](requirements/functional.md) | Checklist of FR-001 to FR-043 with module, test, demo evidence, blocker and status |
| [requirements/non-functional.md](requirements/non-functional.md) | Checklist of NFR-001 to NFR-037 with target, validation, blocker and status |
| [use-cases.md](use-cases.md) | Actors, UC-01 to UC-11, journeys J1 to J4 and the global error table, condensed with links |
| [demo-happy-path.md](demo-happy-path.md) | Scenarios A, B, C, the 8-step judge sequence, fallbacks, evidence per criterion and a rehearsal checklist |
| [architecture/README.md](architecture/README.md) | All 14 Mermaid diagrams from the spec, each with an explanation and the files it maps to |
| [plans/phase-0-baseline.md](plans/phase-0-baseline.md) | Bootstrap phase 0: baseline and audit |
| [plans/phase-1-foundation.md](plans/phase-1-foundation.md) | Bootstrap phase 1: foundation, shared contracts and CI |
| [plans/phase-2-parallel-core.md](plans/phase-2-parallel-core.md) | Bootstrap phase 2: parallel offline core, docs and tooling |
| [plans/phase-3-ci-and-h01.md](plans/phase-3-ci-and-h01.md) | Bootstrap phase 3: CI completion and the H-01 GPU probe |
| [plans/phase-4-github-backlog.md](plans/phase-4-github-backlog.md) | Bootstrap phase 4: GitHub issues, labels and milestones |
| [plans/phase-5-readiness.md](plans/phase-5-readiness.md) | Bootstrap phase 5: verification and readiness review |
| [plans/schedule.md](plans/schedule.md) | T-01 to T-30, H-01 to H-04, D-1 and gates G1 to G4 on the Mon Nov 2 to Wed Nov 4 calendar, with blockers |
| [backlog.md](backlog.md) | Markdown mirror of the GitHub issues to create: labels and milestones |
| [conventions.md](conventions.md) | Toolchain, ownership boundaries, TDD, markers, commits, branching, privacy, budget, definition of done |
| [readiness.md](readiness.md) | Current readiness snapshot: missing functionality, blockers to clear, where status is tracked |
| [runbooks/reolink.md](runbooks/reolink.md) | Probe the cameras, set on-camera privacy masks, audio off, stream URLs, restreamer |
| [runbooks/lidar-scan.md](runbooks/lidar-scan.md) | Markers, 4 scan loops, Scaniverse export, scale check, metadata strip |
| [runbooks/calibration.md](runbooks/calibration.md) | Checkerboard intrinsics, marker-pair extrinsics, acceptance, fallbacks, Tue 10:00 cut-off |
| [runbooks/gpu-h01-h04.md](runbooks/gpu-h01-h04.md) | RTX 3090 tasks H-01 to H-04, WSL2 note, gate H-02 at Mon 22:00 |
| [runbooks/dgx-spark-d1.md](runbooks/dgx-spark-d1.md) | Conditional DGX Spark phase D-1: setup and validation (off by default) |
| [runbooks/credits-billing.md](runbooks/credits-billing.md) | Claiming credits, Credit Terms, $140 limit, keys, daily reconciliation, judging-period decision |
| [runbooks/submission.md](runbooks/submission.md) | The Wed 2:00 PM PT submission checklist |

Top-level documents: [../README.md](../README.md) (project front page), [../EVAL.md](../EVAL.md) (pre-registered targets and results), [../HACKATHON.md](../HACKATHON.md) (build window, prior work, contributors, consent).
