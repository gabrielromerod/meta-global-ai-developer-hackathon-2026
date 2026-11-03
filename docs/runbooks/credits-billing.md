# Runbook: Meta API credits and billing

Spec: [section 11](../spec/vigil-spec.md#11-meta-api-credit-plan--commercial-unit-economics) (11.6 safeguards, 11.7, 11.8). Requirements: FR-043, NFR-012, NFR-013, NFR-036, NFR-037.

**Blocked-by: owner** for every step on this page. Nothing here is automated, and no agent makes a billed call. The budget guard in code (`vigil/meta/budget.py`, used by `MetaClient`) is the real stop; it is tested offline (FR-043, NFR-036, NFR-037 are *Offline-verified*).

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

## 1. Claim the credits (deadline Nov 4, 9 PM ET = 6 PM PT)

- [ ] Each participant claims individually through the form. Claim **now**: T-03 (Mon 14:30 PT) needs them.
- [ ] Check the Billing page for any spend since Oct 26 and note the starting balance.

## 2. Read the Credit Terms

- [ ] Exact expiry (start and end of the 10-day window)
- [ ] Per-model coverage (`sam-3.1`, `muse-spark-1.3`, `muse-wonder-1.0`, `muse-voice-transcribe-1.0`)
- [ ] What happens at zero balance
- [ ] Set `VIGIL_CREDIT_WINDOW_END` (ISO-8601) in `.env` and on the sandbox host **before Nov 4, 9 PM ET**. Until it is known, use the earliest plausible end.

## 3. Set the $140 Billing limit

- [ ] Billing page spend limit at **$140**, before T-03.
- [ ] ⚠️ Test whether it hard-stops calls. Either way, the code guard enforces: $140 on `credit`-tagged spend, feature budgets from [11.4](../spec/vigil-spec.md#114-cost-by-feature), $10 per day in the sandbox, warnings at 50, 75 and 90%.

## 4. Separate keys

- [ ] One key for **development** (edge machine `.env`), one for the **sandbox** (host secret), so the public one can be revoked alone.
- [ ] ⚠️ Check whether per-project limits exist (the billing URL suggests projects).
- [ ] Keys are never committed, logged or pasted into issues (NFR-014; gitleaks in CI).

## 5. Confirm coverage with the smoke tests (T-03)

Run `scripts/smoke_meta.py --live` (one call per model, behind the budget guard, with the owner's approval and the `budget-check` skill), then check that the Billing balance dropped by the logged amount for each model. T-03 also answers whether Voice Transcribe accepts WAV (FR-022).

## 6. Daily reconciliation in `eval/budget.md`

Once a day, compare the ledger total with the Billing page and append a row to `eval/budget.md`. The ledger tags each call `credit` or `paid` (`model_calls.funding`); report both.

| Date (PT) | Ledger `credit` (USD) | Ledger `paid` (USD) | Billing page (USD) | Drift % | Notes |
| --- | --- | --- | --- | --- | --- |
| 2026-11-02 | | | | | |

A drift over **10%** means updating the price table ([11.3](../spec/vigil-spec.md#113-unit-prices-used)) before spending more.

### The ledger behind the caps

The ledger at `VIGIL_LEDGER_PATH` is the **single source of truth** for every cap ($140 credit, feature budgets, $10/day sandbox, $25 and $5/day judging). Read it for the daily row above.

- **Durable.** SQLite in WAL mode, `synchronous=FULL`, one row per billed attempt with `created_at` in UTC and the `funding` tag. On start, the budget guard and the sandbox guards rebuild their totals (by funding tag, PT day and feature) from this file, so a restart or redeploy does not reset any cap. All guards and clients in one process share one ledger.
- **Fails closed.** If `VIGIL_LEDGER_PATH` is unset, cannot be written, or a write fails mid-run, the app still starts with an in-memory ledger, but **paid calls are refused** (`ledger_not_durable`; the request serves the cached result with "Live budget for today used; recorded result shown"). Credit-window calls still run.
- **Docker.** The image sets `VIGIL_LEDGER_PATH=/data/ledger.db` and declares `VOLUME ["/data"]`. Mount a named volume at `/data` on the sandbox host and run **one replica**: reservations are held in memory per process, so two replicas on one file could both admit a call that only one fits.
- **Reservations.** Before sending, the client reserves the call's estimate atomically under the ledger lock; pending reservations count in every cap check, so concurrent requests cannot together cross a cap. The reservation is released when the ledger row is written. In the sandbox, `check_live_allowed` holds the estimate (for at most 600 s if the action fails before recording); recording the calls releases it. While a live action is in flight both holds count, so a call can be refused a few cents short of a cap (it shows "Live call failed"); this errs on the safe side.
- **Retries are charged.** Every billed attempt is charged at the estimate, and a retry that then succeeds also adds its actual price. The budget is re-checked before each retry; a retry that would cross a cap is not sent.
- **Judging end is absolute.** No live call of any funding is admitted at or after `VIGIL_JUDGING_END`, even when `VIGIL_CREDIT_WINDOW_END` is unset.

## 7. Planned spend

[Spec 11.5](../spec/vigil-spec.md#115-phased-usage-plan-and-balance): about **$55 to $95** of the $150 credits, depending on gate H-02, leaving at least $55 unspent (at least $45 below the $140 cap). Judging spend is separate: at most **$25**, charged to the card. The largest unknown is Spark tokens per 10 s clip (assumed 30,000) until T-03 measures it; then `vigil cost estimate` recomputes the plan.

## 8. Live calls during judging (decided on Nov 2)

**Decided by the owner on Nov 2: live calls stay ON during judging (Nov 5–10 PT)**, charged to the card on file, under a hard cap. Worst-case exposure: **$25**.

| Setting (sandbox host) | Value | Effect |
| --- | --- | --- |
| `VIGIL_ALLOW_PAID` | `1`, from the credit window end | Without it, Vigil switches to cached-only at `VIGIL_CREDIT_WINDOW_END` |
| `VIGIL_JUDGING_CAP_USD` | `25` | Total post-window (`paid`) spend; binds before the daily caps (6 days × $5 = $30) |
| `VIGIL_JUDGING_DAILY_CAP_USD` | `5` (default) | Per PT calendar day after the window |
| `VIGIL_JUDGING_END` | Nov 10, 23:59 PT (the default when unset) | No live call of any funding after it |
| `VIGIL_LEDGER_PATH` | `/data/ledger.db` (image default), on a mounted volume, one replica | Caps survive restarts; without a durable ledger, paid calls are refused |
| Rate limit | 10 live requests per minute per IP | Unchanged |

At a cap, after `VIGIL_JUDGING_END`, or on a timeout or failure, the request degrades to the cached result with "Live budget for today used; recorded result shown" or "Live call failed; recorded result from \<date> shown". A judge never sees a blank or disabled screen.

**Billing-page second stop.** At the moment the credit window ends, set the Billing-page limit to (credit spend shown at window end) + $25, or to $25 if the limit counts only card charges. ⚠️ Check which one the page measures before Nov 4, 9 PM ET.

- [ ] Card on file confirmed (owner, date: ____)
- [ ] `VIGIL_CREDIT_WINDOW_END` set (owner, date: ____)
- [ ] Sandbox env set: `VIGIL_ALLOW_PAID=1` from window end, `VIGIL_JUDGING_CAP_USD=25`, `VIGIL_JUDGING_END` (T-28)
- [ ] Sandbox ledger volume mounted at `/data`, single replica; after a redeploy, the day's spend is still shown (T-28)
- [ ] Billing second stop set at window end (owner, date: ____)
- [ ] Daily ledger check Nov 5–10 in `eval/budget.md`

## If credits run out or expire (spec 11.7)

- **Expired (window ended):** with `VIGIL_ALLOW_PAID=1`, live calls continue on the card up to $5 per day and $25 in total; at either cap, after `VIGIL_JUDGING_END`, or with the flag unset, the sandbox serves cached results with the notice, and every flow still works (NFR-009).
- **Exhausted ($140 reached before the window ends):** cached results only.
- Perception runs on local SAM; triage on Glimmer; non-escalated stories use templates; Wonder stories for the demo scenarios are already cached.
- Voice rules fall back to the 3 sample-audio buttons with cached transcripts, then typing.
