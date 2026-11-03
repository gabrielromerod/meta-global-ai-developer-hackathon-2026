---
name: eval-preregister
description: Use when setting or changing EVAL.md targets, writing or editing eval/labels/, before running vigil eval or vigil eval --spatial/--latency, when appending benchmark results, or when a judge-facing claim cites accuracy, alert reduction, latency or cost numbers.
---

# Pre-registered evaluation

## Overview

Targets and labels are committed **before** any result exists; results are appended in a
**later** commit; misses are published. The commit dates are the proof (FR-024, NFR-023,
submission checklist "EVAL.md: targets commit earlier than the results commit").

## Order (never reorder)

1. **Targets commit.** Edit `EVAL.md` targets section: alert reduction >= 80%, correct
   verdict >= 10/12, link precision >= 90%, 0 claims inside gaps, 0 uncited sentences
   (NFR-023), plus NFR-024 to NFR-026 spatial targets, NFR-035 parity, and any latency
   target marked as a first estimate. State the metric definition and the data it runs on.
2. **Labels commit.** Write `eval/labels/<scenario>.json` from the footage **before**
   processing it (T-07): events, visits, expected verdict, gaps with times, links.
   Same commit as targets, or an earlier/later one, but before step 3.
3. Confirm both are committed and pushed: `git log --format="%h %ad %s" --date=iso -- EVAL.md eval/labels`.
   Ask the owner to commit if you are not allowed to.
4. **Run.** `uv run vigil eval` (labels `eval/labels`, output `eval/results.json`);
   spatial: `uv run vigil eval --spatial`; latency: `uv run vigil eval --latency`. Batch
   runs that may call the API need the `budget-check` skill first and `--confirm` above $5;
   prefer cached responses.
5. **Results commit.** Append results to `EVAL.md` (never edit the targets section) and
   commit `eval/results.json`. Every target gets a row: value, target, met / **missed**.

## Rules

- Never change a target or label after seeing a result. If a label is genuinely wrong,
  append a dated correction note explaining why, keep the original visible, and report
  both numbers.
- Misses are reported in the same table and in the README summary; never dropped.
- Re-running from cache must give identical results (FR-024, NFR-011); if not, fix the
  nondeterminism before publishing.
- Latency targets marked as estimates (spec 2) are fixed once the first measured values are
  written into `EVAL.md` before the benchmark run.

## Citing commit dates

```bash
git log --format="%h %ad %s" --date=iso -- EVAL.md        # targets vs results commits
git log --format="%h %ad %s" --date=iso -- eval/labels    # labels committed before results
```

In `EVAL.md` and the README write: "Targets pre-registered in `<hash>` (<ISO date>);
results in `<hash>` (<ISO date>)", with links to the commits on GitHub.

## Red flags

- Running `vigil eval` "just to see" before the targets commit exists.
- Editing thresholds in the same commit as results.
- Dropping a scenario or metric that missed.
- Quoting a number in chat that is not in `EVAL.md`.
