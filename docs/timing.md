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

| Clips/Media full offline baseline (FIXTURE) | 2026-11-03T04:12:32.508097-08:00 | 2026-11-03T04:14:57.640011-08:00 | stopped on parent request after partial pytest progress; no final result; source c820bb4; full pre-main suites remain lead-owned |
| Clips/Media browser matrix (FIXTURE) | 2026-11-03T12:11:57.622Z | 2026-11-03T12:18:17.077Z | source c820bb4; 44 viewport/theme/page cases; 0 failures |
| Clips/Media final frontend suite/build (FIXTURE) | 2026-11-03T12:24Z | 2026-11-03T12:25Z | minute-resolution command interval; 56 tests passed; TypeScript/Vite build passed; Ruff check/format passed |

| Clips/Media field boundary regression (FIXTURE) | 2026-11-03T13:12:54.966Z | 2026-11-03T13:13:03.298Z | source 8f4ca05; 8 cases, 96 measurements; 0 failures; unchanged >=3:1 threshold |
| Clips/Media boundary-fix frontend suite/build (FIXTURE) | 2026-11-03T05:12:54.6827332-08:00 | 2026-11-03T05:13:01.1689054-08:00 | 56 tests and production build passed |

| Offline HTTP backstop and point privacy full regression | 2026-11-03T05:39:59.266719-08:00 | 2026-11-03T05:43:10.709972-08:00 | exit 0; captured command output |

| Wave 2 controls full Chromium matrix | 2026-11-03T12:49:27.844Z | 2026-11-03T12:57:34.519Z | FIXTURE: source f6e05af; 198 layout/state cases, 506 focus observations, 2288 PNGs; 0 failures, 0 errors. Correct selected-panel scrolling supplemented below. |
| Wave 2 controls natural keyboard and contrast | 2026-11-03T13:02:06.687Z | 2026-11-03T13:02:22.371Z | FIXTURE: source d8ba87b; 22 cases, 528 Tab/Shift+Tab steps, ordinary motion, modal focus trap/return and enabled-form contrast; 0 errors. |
| Wave 2 controls selected-panel scrolling | 2026-11-03T13:04:35.632Z | 2026-11-03T13:04:50.842Z | FIXTURE: source d8ba87b; 88 cases, 176 PNGs, all 11 viewport pairs and both themes; 0 errors. |
| Wave 2 controls full frontend verification before Chat timing fix | 2026-11-03T13:15:02.9354273Z | 2026-11-03T13:15:08.9058151Z | FIXTURE: 80 passed, 1 unchanged Chat immediate-visibility race failed; build passed. No assertion weakened. |
| Wave 2 controls full frontend verification after approved dependency test fix | 2026-11-03T13:16:08.7757174Z | 2026-11-03T13:16:14.6357134Z | FIXTURE: exact approved 5f717af applied as 715e677; 81 passed including 19 controls tests; build passed. Root owns full Python/main merge validation. |
| Wave 2 controls round 1 scope reproduction | 2026-11-03T13:40:24.831Z | 2026-11-03T13:40:27.340Z | FIXTURE: unchanged production source 8e74611a; zone-only scope falsely shows All configured cameras in all 4 viewport/theme pairs; 16 of 20 new explicit-label checks fail. New unit cases RED: 3 failed, 20 passed. |
| Wave 2 controls scope repair browser check | 2026-11-03T13:41:48.270Z | 2026-11-03T13:41:51.049Z | FIXTURE: source 612c9ea0; all 20 scope checks pass at 1280x600 and 390x844 in both themes, top/bottom list capture, 0 console/network errors and no desktop document scroll. |
| Wave 2 controls round 2 full frontend verification | 2026-11-03T13:42:37.7403842Z | 2026-11-03T13:42:45.8629707Z | FIXTURE: 85 tests passed including 23 controls tests; build passed; no tests weakened. Unchanged Python suite not rerun, per assignment. |

- REAL: 2026-11-03 05:55 PT local Docker Gitleaks v8.30.1: 133 commits, 8.92 MB, 8.73 seconds, no leaks after narrowly scoped PNG-digest correction; separate scope probe retained both expected secret findings.

- FIXTURE: tracked QA provenance scan started 2026-11-03 05:55 PT and finished 06:01 PT: zero failures, all tracked QA manifests and media checked (before Motion merge).
| Wave 2 motion final viewport matrix, source 4fa2342 | 2026-11-03T04:44:13.374-08:00 | 2026-11-03T05:01:21.938-08:00 | FIXTURE: two disjoint shards, 44 viewport/theme/preference cases, 4,704 captured states; zero failures, console errors, failed requests and desktop document overflow. Separate scene matrix covers the same 44 combinations; adaptive state-preservation regression passed. |
| Wave 2 motion frontend full suite, source 4fa2342 | 2026-11-03T05:09:42-08:00 | 2026-11-03T05:09:46.05-08:00 | REAL logic / FIXTURE inputs: 73 tests passed, 11 new motion tests. TypeScript/Vite build and whole-checkout Ruff check/format also passed (completion observed by 05:09:56-08:00). No Python source change; full Python/E2E pre-main gate remains lead-owned. |
| Wave 2 motion round-two frontend full suite, source f61680ed | 2026-11-03T05:49:36-08:00 | 2026-11-03T05:49:43-08:00 | REAL logic / FIXTURE inputs: 75 tests passed, including 13 motion tests. TypeScript/Vite build passed in the same invocation (completion observed by 05:49:59-08:00). Isolated listener browser passed at 05:49:36.974-08:00; adaptive browser passed 6 state checks, 20-route churn and in-flight stop. Python/E2E pre-main gate remains lead-owned. |
| Wave 2 motion round-two focused preference matrix, source ebc421a9 | 2026-11-03T05:51:37.527-08:00 | 2026-11-03T05:52:11.095-08:00 | FIXTURE: 11 sizes, both themes, ordinary→reduced→ordinary, 22 cases/66 states; no failures/errors/failed requests/desktop overflow. Isolated-hook and adaptive checks also passed on exact source; 82 PNGs including inspection sheets passed root UI privacy/provenance gate. Only QA capture waits changed after production fix 47dddac6. |

- REAL logic / FIXTURE: React integration frontend tests 2026-11-03 06:12:53–06:12:58 PT: 122 passed; consumer API nine tests 06:12:59–06:13:01 PT passed; production build 06:13:01–06:13:03 PT passed. Generated video decode/seek/overlay/snapshot focused E2E passed in 8.56 s at approximately 06:11–06:12 PT. These are not main-merge gates; complete suites remain required.
