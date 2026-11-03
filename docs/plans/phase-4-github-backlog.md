# Phase 4: GitHub backlog

| Item | Value |
| --- | --- |
| When | Mon Nov 2, 2026, after phase 3 |
| Owner | Integrator, with the owner's GitHub account (`gh` CLI) |
| Status | Done: issues #1 to #80, labels and milestones created by `scripts/backlog/backlog.py` ([backlog](../backlog.md)) |

## Goal

Mirror the plan in GitHub so every task, gate and requirement is an issue with labels and a milestone, and the team can see what is blocked and why.

## What to create

The source of truth for the issue list is [backlog.md](../backlog.md).

| Kind | Count | Title pattern | Example |
| --- | --- | --- | --- |
| Build tasks | 30 | `T-NN <task>` | `T-14 Extrinsics accepted, or switch to the fallback` |
| Hardware tasks | 4 | `H-0N <task>` | `H-02 Local SAM 3.1 benchmark (gate)` |
| Conditional phase | 1 | `D-1 DGX Spark full-window SAM (conditional)` | |
| Requirements | 43 | `FR-NNN <short requirement>` | `FR-016 Verdict as a pure function` |
| NFR tracking | 1 | `NFR-001 to NFR-037 tracking` (checklist body linking [non-functional.md](../requirements/non-functional.md)) | |

### Labels

| Group | Labels |
| --- | --- |
| Track | `track:A` pipeline, `track:B` models and reasoning, `track:C` app and 3D, `track:D` field work and evidence |
| Priority | `P0`, `P1`, `P2` |
| Type | `type:task`, `type:requirement`, `type:hardware`, `type:gate`, `type:docs` |
| Blocked | `blocked:credits`, `blocked:hardware`, `blocked:dgx`, `blocked:owner` |

### Milestones (due dates in PT)

| Milestone | Due | Meaning |
| --- | --- | --- |
| G1 | Mon Nov 2, 23:00 | Footage and labels committed; SAM tracks for A, B, C; GLB built |
| G2 | Tue Nov 3, 13:00 | Scenario C end to end, including 3D positions and the gap |
| G3 | Tue Nov 3, 18:00 | MVP freeze: all P0 pass in CI |
| G4 | Tue Nov 3, 23:00 | Evidence complete; sandbox opened on a phone |
| Submission | Wed Nov 4, 14:00 | Section 13.5 checklist ticked; submitted |

## Steps

1. Create the labels and milestones (idempotent: skip any that exist).
2. Create issues from [backlog.md](../backlog.md), one per row, with the body linking the spec section and the requirement checklist row.
3. Link each FR issue to the task that closes it (for example FR-037 to T-14).
4. Apply `blocked:*` labels exactly as the backlog says; remove them as blockers clear.

Use `gh label create`, `gh api repos/{owner}/{repo}/milestones` and `gh issue create`. Do not write a bare `@name` in issue bodies; GitHub would notify that account.

## Exit criteria

- [ ] All labels and the 5 milestones exist
- [ ] 79 issues created (30 + 4 + 1 + 43 + 1), each with a milestone and labels
- [ ] Backlog file and GitHub agree (count check)

Next: [phase 5](phase-5-readiness.md).
