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
