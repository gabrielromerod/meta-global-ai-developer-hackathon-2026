---
name: budget-check
description: Use when about to take any live or paid Meta Model API action - pytest -m live, scripts/smoke_meta.py --live, vigil process or vigil eval that may call the API, enabling sandbox live buttons, recording fixtures - and when reconciling spend, checking the $140 credit cap, the $10/day sandbox cap, the $25 judging cap, the credit window end, VIGIL_JUDGING_END, or eval/budget.md.
---

# Budget check

## Overview

Every paid call is priced before it is sent, and nothing paid happens without the owner.
The code guard (`vigil/meta/budget.py`, used by `MetaClient`) is the real stop; this
checklist makes sure a human-approved plan exists before the guard is even reached.
Account steps (claiming credits, Credit Terms, Billing limit, keys) are in
`docs/runbooks/credits-billing.md`.

## Limits (spec 11, FR-043, NFR-036/037)

| Limit | Value | Setting |
| --- | --- | --- |
| Credit cap | $140 (of $150 credits), `credit`-tagged spend only | `VIGIL_TOTAL_CAP_USD` |
| Sandbox daily cap (before window end) | $10/day | `VIGIL_DAILY_CAP_USD` |
| Feature budgets | spec 11.4 table | budget guard |
| Warnings | 50%, 75%, 90% | budget guard |
| Credit window end | owner-confirmed ISO time | `VIGIL_CREDIT_WINDOW_END` |
| Paid after window | only with `VIGIL_ALLOW_PAID=1` (owner only; decided ON for judging, Nov 2) | `VIGIL_ALLOW_PAID` |
| Judging cap (post-window `paid` spend) | $25 total; binds before the daily cap | `VIGIL_JUDGING_CAP_USD` |
| Judging daily cap | $5 per PT calendar day | `VIGIL_JUDGING_DAILY_CAP_USD` |
| Judging end | no paid call after Nov 10, 23:59 PT (default when unset) | `VIGIL_JUDGING_END` |
| Batch `--confirm` | required above $5 | CLI |

Allowed models: `sam-3.1`, `muse-spark-1.3`, `muse-wonder-1.0`, `muse-voice-transcribe-1.0`.
Never a `-contributor` ID, web-search tool or Muse Image.

## Before any live action

1. **Estimate** with the budget module (prices from spec 11.3):
   ```bash
   uv run python -c "from vigil.meta.budget import estimate; print(estimate('sam-3.1', 'perception', frames=600))"
   ```
   Use the real unit kwargs `estimate()` accepts (check its docstring/signature); for
   batches, `uv run vigil cost estimate` or the pre-flight printout of `vigil process` / `vigil eval`.
2. **Check headroom:** ledger total so far (the `model_calls` table, `cost_usd` where
   `cached = 0`) plus the estimate stays under $140, under the feature budget and, for the
   sandbox, under today's $10.
3. **Check the window:** before `VIGIL_CREDIT_WINDOW_END` the call is `credit`-funded. After it,
   the call is `paid` and allowed only with `VIGIL_ALLOW_PAID=1`, within the $25 / $5-per-day
   judging cap and before `VIGIL_JUDGING_END`. The allowance is set for the judges'
   sandbox (T-28); any other paid call needs the owner's explicit approval.
4. **Prefer free paths:** cache hit, recorded fixture, local SAM / Glimmer, template story.
5. **Ask the owner** with the estimate, models, call count and purpose. Proceed only on an
   explicit yes in this session. Never set `VIGIL_ALLOW_PAID` or raise a cap yourself.

## Daily reconciliation (safeguard 7)

Append one row per day to `eval/budget.md`:

| Date (PT) | Ledger `credit` USD | Ledger `paid` USD | Billing page USD | Drift % | Action |
| --- | --- | --- | --- | --- | --- |

- Ledger totals come from the `model_calls` table (split by `funding`); the Billing page figure comes from the
  owner (Claude cannot log in to Billing).
- Drift over 10%: stop paid calls and update the price table in `vigil/meta/budget.py`
  (via a `vigil-fr-tdd` change with tests) before spending more.
- Also note the remaining credit and the spec 11.5 phase you are in.

## Red flags

- "It's only one call" without an estimate or approval.
- Running `pytest -m live` or `--live` scripts in CI, a loop or a background job.
- Bypassing `MetaClient` (direct httpx) so the guard never sees the call.
- Paid calls outside the sandbox after the credit window, past the judging cap or after
  `VIGIL_JUDGING_END`, or "the Billing page limit will stop it" (it may not).
