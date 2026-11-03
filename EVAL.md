# Vigil evaluation

**Registered on 2026-11-02, before any run.** The targets below were committed before any footage was processed, any benchmark was run or any model output was seen. They stay fixed after this commit. The commit that adds results must be later than the commits that add these targets (`git log -- EVAL.md`). Additions and spec-driven changes made on 2026-11-02, still before any run, are listed under [Registration log](#registration-log).

Sources: [NFR-012, NFR-023 to NFR-026, NFR-035 to NFR-037](docs/spec/vigil-spec.md#2-non-functional-requirements), [FR-013, FR-024, FR-044](docs/spec/vigil-spec.md#1-functional-requirements), [spec 11.9](docs/spec/vigil-spec.md#119-commercial-unit-economics-new-why-the-edge-plus-cloud-cascade-wins), [spec 12.1](docs/spec/vigil-spec.md#121-test-suites).

## Method

- **Data:** 12 labelled scenarios filmed on the 4 home Reolink cameras with consenting adults from the team, including the 5 demo scenarios (A, A′, B, B′, C). Labels (`eval/labels/<scenario>.json`) are written **before** processing; they include each subject's role (`household_insider`, `expected_visitor`, `external_visitor`) from how the take was staged, never from identity.
- **Run:** `vigil eval` computes every metric from the labels and the pipeline output and writes `eval/results.json` and the Results tables below. Re-running from the cache must give identical results.
- **Spatial:** the audit harness: 6 surveyed ground markers per camera, never used for calibration; a person stands on them for the marker walk (`vigil eval --spatial`).
- **Night and day** are reported separately (infrared footage weakens colour-based linking and role carry-over).
- **Misses are reported**, never hidden or re-targeted.
- **Definitions.** The spec fixes the targets but not every formula. The definitions in the tables below are the ones registered here; if the owner changes a definition, it must happen in a commit before the first run, with the reason.

## Pre-registered targets

### Accuracy (NFR-023)

| Metric | Definition | Target |
| --- | --- | --- |
| Alert reduction | 1 − (alerts raised by Vigil ÷ motion triggers) over the 12 scenarios, the same counts as the sandbox summary "N motion triggers → V visits → alerts"; the reduction against the naive baseline (FR-025) is reported alongside | at least 80% |
| Correct verdict | Scenarios whose verdict matches the label | at least 10 of 12 |
| Link precision | Correct cross-camera links ÷ links made, on the labelled set | at least 90% |
| Claims inside gaps | Shipped sentences stating an action at a time inside a gap | 0 |
| Uncited sentences | Shipped model sentences without a valid event citation | 0 |

### Roles (FR-044), registered 2026-11-02

The spec sets no numeric target for roles; these are **reported, not targeted**. Vigil identifies no one: roles come from spatial origin, and every failure mode fails closed (more alerts, never fewer).

| Metric | Definition | Reported |
| --- | --- | --- |
| Assigned versus labelled role | Per labelled subject: the role Vigil assigned (with its `role_basis`) next to the labelled role; a confusion table over the 4 roles (`unknown` included) | Day and night separately |
| Role accuracy | Subjects whose assigned role equals the label ÷ labelled subjects | Day and night separately |
| **Role miss rate** | Household subjects (labelled `household_insider`) not assigned `household_insider` ÷ household subjects | Day and night separately |
| Alerts caused by role misses | Alerts on household subjects whose role was missed (a rule fired that would not have fired on `household_insider`) | Count, day and night |

The optional T-07b take (a household member returning through the side alley without a check-in) is a documented false alert: it counts as a role miss and its alert is reported here.

### Commercial unit economics (spec 11.9), registered 2026-11-02

Spec 11.9's tier figures are **hypotheses, not targets**. T-27 measures them on the recorded evening; the measured values are published in Results whether or not they match. No per-home monthly figure is published as measured: the 11.9 cost table stays an estimate, recomputed from measured inputs with `vigil cost estimate`.

| Measure | Definition | Hypothesis (spec 11.9) |
| --- | --- | --- |
| Tier 0 skip rate | Windows skipped as idle by the motion gate, with Reolink AI events forcing processing (no model call) ÷ all windows | about 85% |
| Tier 1 resolve rate | 1 − escalation rate (FR-013): visits not escalated to Wonder ÷ visits | about 90% |
| Escalated visits | Escalated visits on the recorded evening, and the per-day figure E only if the recording covers a full day | E = 2–4 per day |
| Tier 2 cost per escalated visit | Ledger cost of the Spark and Wonder calls per escalated visit | about $0.022 (compact-ledger story) or $0.040 (spec-size story) with appearance notes kept local; about $0.12 with 2 Spark appearance clips |

`vigil eval` reports the Tier 0 measure as `totals.tier0_skipped_share` (windows with status `idle` ÷ all windows, from `windows_skipped` and `windows_total`; `null` when there are no windows) and as the table row "Tier 0 skipped-window share (11.9)", reported only, with no target.

### Spatial (NFR-024, NFR-025, NFR-026)

| Metric | Target |
| --- | --- |
| Lens-profile RMS reprojection, per camera model that has a profile | under 1.0 px |
| Landmark mean reprojection, per camera | under 6 px at 1280 px width with nominal-FOV intrinsics; under 4 px with a lens profile |
| Held-out ground error on the audit markers, per camera | under 0.25 m |
| 3D position error for people, median, within 10 m of the camera (NFR-025) | under 0.5 m ⚠️ first estimate; 90th percentile reported |
| Test points inside their stated 95% radius (NFR-026) | at least 90% |

### Local versus hosted SAM 3.1 (NFR-035, H-04)

| Metric | Target |
| --- | --- |
| Mean mask IoU, local versus API, on 20 windows | at least 0.8 ⚠️ first estimate |
| ID switches per window from chunking (gate H-02) | at most 1 more than the API |

### Latency (first estimates)

Meta does not publish response times, so these are **first estimates** (⚠️). The first measured values are recorded in the Results section before the benchmark run; the targets do not change after that.

| ID | Measure | Target |
| --- | --- | --- |
| NFR-006 | Live tap-to-protect: click to mask drawn, over 20 calls | p50 under 5 s ⚠️ |
| NFR-007 | Live story re-run on cached perception (triage + Wonder + validation), over 10 runs | p50 under 30 s ⚠️ |
| NFR-027 | Reolink AI event to cone pulse, 10 staged walk-ins | p50 under 3 s ⚠️ |
| NFR-028 | Live lag: start of movement to SAM track and 3D disc, 20 walk-ins | p50 under 45 s ⚠️; p90 reported |
| NFR-008 | Offline processing: end of visit to published card | median per scenario reported |

### Cost (NFR-012, NFR-036, NFR-037)

| Measure | Target |
| --- | --- |
| Full benchmark (12 scenarios) | under $25 with local SAM; under $40 including the baseline if API SAM is needed (H-02 fails) |
| Credit-funded Meta API spend (ledger tag `credit`) | under $140; no feature over its spec 11.4 budget |
| Post-window spend during judging (ledger tag `paid`) | at most $25 in total and $5 per PT day; none after Nov 10, 23:59 PT |

## Registration log

| Date | Change | Why |
| --- | --- | --- |
| 2026-11-02 | First registration of the accuracy, spatial, parity, latency and cost targets | Before any run |
| 2026-11-02 | Spatial: "Extrinsics mean reprojection under 4 px" became the landmark threshold of 6 px (nominal FOV) or 4 px (lens profile); intrinsics RMS applies only where a lens profile exists | Spec NFR-024 and FR-036/FR-037 changed (Nov 2 change set); no calibration had run |
| 2026-11-02 | Cost: NFR-012 adds the under-$40 API-SAM case; the $140 counts `credit`-tagged spend only; the $25 judging cap (NFR-037) is added | Spec NFR-012, NFR-036, NFR-037 changed; no billed call had run |
| 2026-11-02 | Added the role metrics, including the **role miss rate**, and the 11.9 Tier 0 / Tier 1 measurement, both reported without targets | Spec FR-044 acceptance and 11.9 (T-27); no footage had been processed |

## Results

Results are appended after the run; misses are reported.

Targets pre-registered in `<hash>` (<ISO date>); results in `<hash>` (<ISO date>). Fill in from `git log --format="%h %ad %s" --date=iso -- EVAL.md eval/labels` when results are added.

Every target above gets one row here, in the form: metric | value | target | met or **missed**. Reported-only measures (roles, tiers) get their value and, where one exists, the hypothesis. Night and day are reported separately where they apply.

_No results yet._
