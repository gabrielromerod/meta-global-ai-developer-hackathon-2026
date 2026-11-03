# Vigil evaluation

**Registered on 2026-11-02, before any run.** The targets below were committed before any footage was processed, any benchmark was run or any model output was seen. They stay fixed after this commit. The commit that adds results must be later than the commit that adds these targets (`git log -- EVAL.md`).

Sources: [NFR-023 to NFR-026, NFR-035](docs/spec/vigil-spec.md#2-non-functional-requirements), [FR-024](docs/spec/vigil-spec.md#1-functional-requirements), [spec 12.1](docs/spec/vigil-spec.md#121-test-suites).

## Method

- **Data:** 12 labelled scenarios filmed on the 4 home Reolink cameras with consenting adults from the team. Labels (`eval/labels/<scenario>.json`) are written **before** processing.
- **Run:** `vigil eval` computes every metric from the labels and the pipeline output and writes `eval/results.json` and the Results tables below. Re-running from the cache must give identical results.
- **Spatial:** a person stands on 6 surveyed markers per camera that were not used for calibration (`vigil eval --spatial`).
- **Night and day** are reported separately (infrared footage weakens colour-based linking).
- **Misses are reported**, never hidden or re-targeted.
- **Definitions.** The spec fixes the targets but not every formula. The definitions in the tables below are the ones registered here; if the owner changes a definition, it must happen in a commit before the first run, with the reason.

## Pre-registered targets

### Accuracy (NFR-023)

| Metric | Definition | Target |
| --- | --- | --- |
| Alert reduction | 1 − (alerts raised by Vigil ÷ motion triggers) over the 12 scenarios, the same counts as the sandbox summary "N motion triggers → visits → alerts"; the reduction against the naive baseline (FR-025) is reported alongside | at least 80% |
| Correct verdict | Scenarios whose verdict matches the label | at least 10 of 12 |
| Link precision | Correct cross-camera links ÷ links made, on the labelled set | at least 90% |
| Claims inside gaps | Shipped sentences stating an action at a time inside a gap | 0 |
| Uncited sentences | Shipped model sentences without a valid event citation | 0 |

### Spatial (NFR-024, NFR-025, NFR-026)

| Metric | Target |
| --- | --- |
| Intrinsics RMS reprojection, per camera | under 1.0 px |
| Extrinsics mean reprojection, per camera | under 4 px at 1280 px width |
| Held-out ground error, per camera | under 0.25 m |
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

### Cost (NFR-012, NFR-036)

| Measure | Target |
| --- | --- |
| Full benchmark (12 scenarios) | under $25 |
| Total Meta API spend | under $140; no feature over its budget |

## Results

Results are appended after the run; misses are reported.

Targets pre-registered in `<hash>` (<ISO date>); results in `<hash>` (<ISO date>). Fill in from `git log --format="%h %ad %s" --date=iso -- EVAL.md eval/labels` when results are added.

Every target above gets one row here, in the form: metric | value | target | met or **missed**. Night and day are reported separately where they apply.

_No results yet._
