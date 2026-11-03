# Runbook: Meta API credits and billing

Spec: [section 11](../spec/vigil-spec.md#11-meta-api-credit-plan-150). Requirements: FR-043, NFR-012, NFR-013, NFR-036, NFR-037.

**Blocked-by: owner** for every step on this page. Nothing here is automated, and no agent makes a billed call.

## What is verified

From [spec 11.1](../spec/vigil-spec.md#111-what-is-verified-about-the-credits):

| Term | Status |
| --- | --- |
| $150 in Meta Model API credits per selected participant | Verified (Official Rules) |
| Valid for a "10-day development window" | Wording verified; exact start and end **not published** |
| A separate **Credit Terms** document applies | Exists; text behind the Cerebral Valley login, **not read** |
| Claim individually by **Nov 4, 9 PM ET** through a form | Mirror only ([event guide copy](https://github.com/meta-ai-hackathon/meta-hack/blob/main/info/event%20guide.md)) |
| A credit card on the account with a temporary pre-authorisation | Mirror only |
| A spend limit on the Billing page | Mirror only; ⚠️ whether it hard-stops calls is unverified |
| What happens after credits run out or expire | **Unknown**: assume the card is charged |

## 1. Claim the credits (today, deadline Nov 4, 9 PM ET = 6 PM PT)

- [ ] Each participant claims individually through the form. Claim **now**: T-03 smoke tests (Mon 12:30 PT) need them.
- [ ] Check the Billing page for any spend since Oct 26 and note the starting balance.

## 2. Read the Credit Terms

- [ ] Exact expiry (start and end of the 10-day window)
- [ ] Per-model coverage (the 4 models Vigil uses: `sam-3.1`, `muse-spark-1.3`, `muse-wonder-1.0`, `muse-voice-transcribe-1.0`)
- [ ] What happens at zero balance
- [ ] Set `VIGIL_CREDIT_WINDOW_END` in `.env` (ISO-8601) to the window end. Until it is known, use the earliest plausible end.

## 3. Set the $140 Billing limit

- [ ] Billing page spend limit at **$140**, before T-03.
- [ ] ⚠️ Test whether it hard-stops calls. Regardless of the result, the **budget guard in code is the real stop**: total cap $140, feature budgets from [11.4](../spec/vigil-spec.md#114-cost-by-feature), daily cap, warnings at 50, 75 and 90%.

## 4. Separate keys

- [ ] One key for **development** (edge machine `.env`), one for the **sandbox** (host secret), so the public one can be revoked alone.
- [ ] ⚠️ Check whether per-project limits exist (the billing URL suggests projects).
- [ ] Keys are never committed, logged or pasted into issues (NFR-014; gitleaks in CI).

## 5. Confirm coverage with the smoke tests (T-03)

Run `scripts/smoke_meta.py --live` (one call per model, behind the budget guard), then check that the Billing balance dropped by the logged amount for each model. That turns "expected" into "verified" for the 4 models.

## 6. Daily reconciliation in `eval/budget.md`

Once a day, compare the ledger total with the Billing page and append a row to `eval/budget.md`:

| Date (PT) | Ledger total (USD) | Billing page (USD) | Drift % | Notes |
| --- | --- | --- | --- | --- |
| 2026-11-02 | | | | |

A drift over **10%** means updating the price table ([11.3](../spec/vigil-spec.md#113-unit-prices-used)) before spending more.

## 7. Planned spend

[Spec 11.5](../spec/vigil-spec.md#115-phased-usage-plan-and-balance): about **$55 to $95** of $150, depending on gate H-02. Reserve at least $40; hard cap $140. The largest unknown is Spark tokens per 10 s clip (assumed 30,000) until T-03 measures it; then `vigil cost estimate` recomputes the plan.

## 8. Decision: live calls during judging (before Nov 4, 9 PM ET)

Judging (Nov 5 to 9) probably falls **after** the credit window, so live calls could be charged to the card.

| Option | Effect |
| --- | --- |
| **Cached-only (default)** | The sandbox switches to cached-only at `VIGIL_CREDIT_WINDOW_END`; every flow still works (NFR-009, NFR-037) |
| Approve a separate cap (for example $15 total) | Owner sets `VIGIL_ALLOW_PAID=1` and the cap on the sandbox host; recorded here with the date |

Decision: _____ (owner, date) 

## If credits run out or expire

- Sandbox serves cached results only; every flow still works.
- Perception runs on local SAM; triage on Glimmer; non-escalated stories use templates; the 3 demo Wonder stories are already cached.
- Voice rules fall back to typed rules.
