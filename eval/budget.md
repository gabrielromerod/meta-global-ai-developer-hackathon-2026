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
| 2026-11-04 | 0.27 credit (24 uncached calls) + 0.0025 paid (Oct 26 test row) | owner to read | | First live real-event run, owner-approved: `vigil process --cloud` on one front_right_duo arrival (4 windows, 497 billed SAM frames). SAM $0.16, Spark appearance $0.039 (1 empty answer: default reasoning effort spent 898/900 output tokens; fixed with low effort), Wonder story $0.068 (2 runs). Conservative pre-flight said $38.09. Remaining credit headroom ≈ $139.73 of $140. |
| 2026-11-04 | 0.45 credit cumulative | owner to read | | Second owner-approved run: front_left_duo arrival, $0.18. Triage answer failed once (SparkAnswerError, code fallback used). |
| 2026-11-04 | 0.54 credit cumulative | owner to read | | Three verification re-runs of the front_left_duo arrival after fixes ($0.09; SAM always from cache). Triage now completes at low effort with 1600 output tokens. |
| 2026-11-04 | 1.01 credit cumulative | owner to read | | Owner-approved run (estimate ~$0.45) after narrowing the Duo street masks: merged two-camera moment `moment-482000ba7a6c752b` $0.39 (re-masked parts, so SAM billed again), front_right_duo re-run $0.08, front_left_duo $0.00 (all cached). Total $0.47 under a $0.60 SIGINT watchdog. |
| 2026-11-04 | 1.07 credit cumulative | owner to read | | Owner-approved re-run of the merged moment after the overlap-edge fix (estimate ~$0.04, actual $0.063: Wonder $0.051 for the larger two-camera ledger, triage $0.012; SAM and Spark appearance cached). One visit, person chained across both Duo cameras. |
