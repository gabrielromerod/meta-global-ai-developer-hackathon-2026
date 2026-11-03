# Phase 0: baseline and audit

**Part of the repository bootstrap** (phases 0 to 5). These phases set up the repository so the spec's build tasks ([T-01 to T-30](schedule.md)) can run in parallel. They are not a replacement for the spec's [task table](../spec/vigil-spec.md#97-tasks-in-order-times-pt-tracks-a-pipeline-b-models-and-reasoning-c-app-and-3d-d-field-work-and-evidence).

| Item | Value |
| --- | --- |
| When | Mon Nov 2, 2026, by 11:30 PT (part of T-01) |
| Commit | `375320f` chore: initial commit with Vigil specification |
| Status | Done |

## Goal

Establish what exists before any code is written, so prior work can be disclosed and every requirement starts from an honest status.

## Steps

1. Commit the specification as the first commit (`docs/spec/vigil-spec.md`).
2. Run the [20-minute repo audit](../spec/vigil-spec.md#20-minute-repo-audit-run-first-then-update-the-status-column-in-section-1): commits since and before 2026-10-26, source file inventory, remote check.
3. Record the result in [`docs/audit/2026-11-02-repo-audit.md`](../audit/2026-11-02-repo-audit.md).
4. Set every FR and NFR to *Not verified* in the [requirement checklists](../requirements/functional.md).

## Result

- No commits before or after 2026-10-26 other than the specification; no source files; the remote was private and empty.
- **No prior work.** [HACKATHON.md](../../HACKATHON.md) says so and links the audit.
- Commit range for the submission starts at `375320f`.

## Exit criteria

- [x] Spec committed
- [x] Audit written and committed
- [x] All requirement statuses at *Not verified*

## Still open from T-01 (owner actions, not part of the bootstrap)

T-01 in the spec also includes claiming credits, setting the spend limit, picking the track and committing EVAL.md targets. The EVAL.md targets are committed in phase 2 (this documentation workstream). The rest needs the owner: see [credits runbook](../runbooks/credits-billing.md) and [blockers](../readiness.md#blockers-to-clear-today).

Next: [phase 1](phase-1-foundation.md).
