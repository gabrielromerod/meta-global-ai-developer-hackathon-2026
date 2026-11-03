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

| Wave 1 chat full offline suite | 2026-11-03T03:12:25-08:00 | 2026-11-03T03:15:54-08:00 | 1474 passed, 24 deselected, 208.79 s; one existing Starlette warning; ruff check/format passed |
| Wave 1 chat final npm tests/build | 2026-11-03T03:17:27-08:00 | 2026-11-03T03:17:35-08:00 | 14 tests passed, TypeScript/Vite build passed |

| Wave 1 shell Python verification | 2026-11-03T03:12:07-08:00 | 2026-11-03T03:16:51-08:00 (completion observed) | REAL logic / FIXTURE inputs: ruff check + format check passed; pytest 1474 passed, 24 deselected, 1 dependency deprecation warning; pytest runtime 212.80s |
| Wave 1 shell Chromium final state capture | 2026-11-03T03:21:38-08:00 | 2026-11-03T03:23:26-08:00 | FIXTURE: 11 viewports, 448 state PNGs, no desktop document scroll, 0 console errors, 0 failed requests; source f2ca626 |
| Wave 1 shell round 2 affected UI matrix | 2026-11-03T04:02:08.272000-08:00 | 2026-11-03T04:02:35.931000-08:00 | FIXTURE: 11 viewports, both themes for Clips/Media, keyboard and pointer notification focus, dropdown layering; 0 failures/errors/failed requests. npm test 40 passed; build passed. |

| Complete seven-camera backend regression | 2026-11-03T05:19:21.688151-08:00 | 2026-11-03T05:22:04.148635-08:00 | exit 0; captured command output |
