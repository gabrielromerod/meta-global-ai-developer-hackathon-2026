# Runbook: submission (Wed Nov 4, 2:00 PM PT)

Task: **T-30**. Spec: [13.5 Submission checklist](../spec/vigil-spec.md#135-submission-checklist-wed-200-pm-pt). Milestone: **Submission** (issue #75).

**Blocked-by: owner** (submitting the form, track, team members, video upload).

## Checklist (spec 13.5)

- [ ] All P0 requirements Verified by test in CI; P1 results written in EVAL.md, including misses ([functional](../requirements/functional.md), [non-functional](../requirements/non-functional.md))
- [ ] Sandbox URL opens on a phone and a laptop in a private window; the offline E2E run is green
- [ ] Video under 3:00: judge path, live home clip with measured lag, benchmark table; public link tested
- [ ] Sandbox env set: `VIGIL_ALLOW_PAID=1` from window end, `VIGIL_JUDGING_CAP_USD=25`, `VIGIL_JUDGING_END` (Nov 10, 23:59 PT), `VIGIL_CREDIT_WINDOW_END` confirmed; the judging-cap test is green
- [ ] README: value line, video, sandbox link, model table with file paths, EVAL table, honest limits (near-real-time, uncertainty radii, IR at night, roles are spatial origin not identity, household members arriving from the street without a check-in can trigger `non_household` rules, 5- or 4-model configuration used, edge-hardware power cost)
- [ ] HACKATHON.md: build window, commit range, any prior work, contributors, consent statement
- [ ] EVAL.md: targets commit earlier than the results commit
- [ ] Privacy scan, metadata scan and gitleaks clean; no raw footage or credentials in the repo
- [ ] Cellular port check passed; live mode turned off on the edge machine after recording
- [ ] Form submitted with track, team members and links; confirmation saved

## How to check each item

| Item | Check |
| --- | --- |
| P0 in CI | Every P0 row in the [functional checklist](../requirements/functional.md) is *Verified*, or its miss is explained in EVAL.md; the blocking CI lane (lint, gitleaks, the 5 P0 suites) is green on the submitted commit, and every report-only red has an open issue |
| Sandbox | Open the URL in a private window on a phone and a laptop; CI's Docker E2E job is green on the submitted commit |
| Judging env | On the host: the 4 variables above. Locally: `uv run pytest tests/unit/test_budget.py tests/integration/test_guards.py -q` green (judging cap, daily cap, `VIGIL_JUDGING_END`) |
| Video | Duration under 3:00; open the public link while logged out |
| README | Replace "Video: TBD" and "Sandbox: TBD" in [README.md](../../README.md); EVAL table filled from `eval/results.json`; the model table says whether the 5-model loop ran (H-03 passed) or the 4-model fallback (Spark triage) |
| HACKATHON.md | Commit range updated to the submitted commit; contributors and consent statement (including the voice-fixture speaker) confirmed by the owner ([HACKATHON.md](../../HACKATHON.md)) |
| Pre-registration | `git log --format="%h %ad %s" --date=iso -- EVAL.md`: the targets commits precede the results commit |
| Scans | `make scan` (or `pwsh scripts/tasks.ps1 scan` plus `bash scripts/metadata_scan.sh demo`), the repository-wide audio check (only the files in `config/audio_fixtures.json`), the gitleaks job, and a manual review of every frame set in `demo/` |
| Exposure | A phone on cellular reaches no camera or edge port; live LAN mode stopped |
| Form | Screenshot or email of the confirmation saved privately |

## Also before submitting

- [ ] [Demo rehearsal checklist](../demo-happy-path.md#rehearsal-checklist) run on the deployed sandbox
- [ ] Judging-period settings recorded ([credits runbook](credits-billing.md#8-live-calls-during-judging-decided-on-nov-2)), including the Billing-page second stop at window end
- [ ] README links the 90-second fallback screen recording and local `make demo` instructions
