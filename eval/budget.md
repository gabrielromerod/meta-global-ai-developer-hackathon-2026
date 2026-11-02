# Budget reconciliation log

Daily comparison of the spend ledger (`model_calls.cost_usd`, priced by `vigil/meta/budget.py`
from the spec 11.3 table) with the Meta Billing page, as described in
[docs/runbooks/credits-billing.md](../docs/runbooks/credits-billing.md) section 6.
Requirements: FR-043, NFR-036, NFR-037. Hard cap **$140** total, sandbox **$10/day**.

How to fill a row (once a day, owner):

1. Ledger total: `SELECT ROUND(SUM(cost_usd), 4) FROM model_calls WHERE cached = 0;` on the
   edge DB (plus the sandbox DB once it makes live calls).
2. Billing page: the amount spent shown on the Meta Billing page at the same time.
3. Drift % = (Billing page - Ledger total) / Billing page x 100.
4. Notes: anything that explains the drift, and what was run that day.

**A drift over 10% stops all paid calls until the price table (spec 11.3 and
`vigil/meta/budget.py`) is updated** and `uv run vigil cost estimate` is re-run with the
measured numbers.

| Date (PT) | Ledger total (USD) | Billing page (USD) | Drift % | Notes |
| --- | --- | --- | --- | --- |
| 2026-11-02 | | | | |
