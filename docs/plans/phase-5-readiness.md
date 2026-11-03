# Phase 5: verification and readiness

| Item | Value |
| --- | --- |
| When | Mon Nov 2, 2026, end of the bootstrap; then repeated before each gate |
| Owner | Integrator |
| Status | Not started |

## Goal

Prove the bootstrap left the repository in a state the build tasks can rely on, and publish an honest readiness snapshot.

## Verification

| Check | Command | Pass when |
| --- | --- | --- |
| Lint | `uv run ruff check .` and `uv run ruff format --check .` | No findings |
| Tests | `uv run pytest` (Windows: `pwsh scripts/tasks.ps1 test`; Linux: `make test`) | All green; `live`, `gpu`, `e2e` deselected |
| CI | GitHub Actions on `main` | Green on the head commit |
| Secrets | gitleaks (CI step 2) | Clean |
| Diagrams | Mermaid CLI over `docs/architecture/*.mmd` | All 14 compile ([architecture](../architecture/README.md#validation)) |
| Doc links | Relative link and anchor check over `docs/`, `README.md`, `EVAL.md`, `HACKATHON.md` | Every link resolves |
| Pre-registration | `git log -- EVAL.md` | Targets commit is earlier than any results commit |
| Privacy | No real footage, credentials, GPS or personal data in the tree | Manual review plus the scans once they exist |

## Readiness snapshot

Update [readiness.md](../readiness.md) with:

1. The status of every FR and NFR, copied from the checklists (*Not verified*, *Offline-verified*, *Verified*, *Blocked*).
2. What is blocked, by what (credits, hardware, DGX, owner), and the decision point from [spec 13.3](../spec/vigil-spec.md#133-critical-risks).
3. The [blockers to clear today](../spec/vigil-spec.md#134-blockers-to-clear-today) and who owns each.

## Exit criteria

- [ ] Every check above passes, or its failure is written down with the reason
- [ ] Readiness snapshot committed
- [ ] Committed and pushed to `main` with CI green

After phase 5 the team works from the [schedule](schedule.md) and the [backlog](../backlog.md).
