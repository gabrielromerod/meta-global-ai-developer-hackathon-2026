# Suite timing

All times include timezone. Full suites are required before each merge to main.

| Phase | Start | End | Result |
| --- | --- | --- | --- |
| Initial offline baseline | 2026-11-03T03:03:00-08:00 | 2026-11-03T03:05:40-08:00 | 1473 passed, 24 deselected; 159.70 s |

| Backend migration regression | not captured | not captured | 11 failed, 1469 passed; stricter scanner tests/config setup corrected; 204.44s |
| Focused pipeline/schema regression | not captured | not captured | 33 passed; 32.84s |
| Privacy/panorama/retention focus | not captured | not captured | 67 passed; 26.08s |

Initial baseline wall times are approximate; durations come from pytest. Later full pre-main suites record exact start/end automatically.

| Backend full regression | 2026-11-03T03:24:12.435244-08:00 | 2026-11-03T03:26:48.933844-08:00 | pytest exit 1; see captured command output |

| Backend full regression after export checks | 2026-11-03T03:44:43.709921-08:00 | 2026-11-03T03:48:20.937528-08:00 | exit 0; captured command output |

| Legacy app E2E compatibility before UI switch | 2026-11-03T03:48:20.937528-08:00 | 2026-11-03T03:48:47.366813-08:00 | exit 0; captured command output |

| Home/Attention full offline suite (FIXTURE) | 2026-11-03T03:21:16.8259134-08:00 | 2026-11-03T03:24:10.9967055-08:00 | exit 0; see home task evidence |
| Home/Attention browser matrix (FIXTURE) | 2026-11-03T03:27:10.4355185-08:00 | 2026-11-03T03:30:51.8486090-08:00 | 22 viewport/theme cases; 0 failures |

| Wave 1 twin: 20 UI tests, build and 11-viewport browser QA | 2026-11-03T03:29:31-08:00 | 2026-11-03T03:30:41-08:00 | PASS; source 4a1120e, 109 screenshots, dark/light, zero console/network/overflow/annotation-overlap errors |
| Wave 1 twin: full offline Python branch regression | Invocation timestamp not captured; duration 202.31 s | 2026-11-03T03:17:13-08:00 (pytest cache write timestamp) | 1474 passed, 24 E2E deselected, 1 existing Starlette deprecation warning; this is not a main-merge timing record |
