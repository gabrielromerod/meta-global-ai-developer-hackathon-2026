# Browser QA notes

The QA server is http://127.0.0.1:8000 (sandbox, cache-only, invalid API key).
Current demo evidence is FIXTURE: synthetic scenarios, not real camera acceptance.

Add bugs below with steps, expected behavior, and observed behavior. Please give each item
a stable ID (QA-001, QA-002, ...). I check this file between numbered tasks. Fixed items
will include the implementation commit SHA after verification.

## Open

<!-- Add QA reports here. -->

## Fixed

<!-- QA-ID — fix description — commit SHA -->

- QA-HOME-001 — FIXTURE: short Windows/4:3 windows squeezed the hero. Responsive context placement, stretched slots, compact chrome and the short-height gutter preserve a minimum 180px scene through every configured view. Fixes: b613fc1, 4fc0631, 7be158f, 58a6098. Before-fix evidence: qa/home-regressions/7be158f-selected-camera-before.png.
- QA-HOME-002 — REAL logic / FIXTURE inputs: full Attention incorrectly inherited Home's five-card preview cap. The full page now preserves all ranked visits; seven-visit regression passes. Fix: 5674ab3.
- QA-HOME-003 — REAL logic / FIXTURE inputs: selected-camera fallback emitted a camera ID to the clip action. It now opens the matching clip ID; failing-then-passing UI regression covers it. Fix: 58a6098.

- QA-INTEGRATION-001 — FIXTURE: snapshot stayed disabled after a metadata seek. Ready/can-play/seek events now update decoded-frame availability; actual MP4 decode/seek/overlay/snapshot E2E passes. Fix: 49782952.
- QA-INTEGRATION-002 — REAL logic / FIXTURE: full Attention no longer loses normal-history filters or urgent items beyond five. Frontend and API tests failed first, then passed. Fix: 49782952.

- QA-INTEGRATION-003 — FIXTURE: actual visit review shrank the scene below 180 px in short desktops; root left-column internal scrolling now preserves a 190 px scene. Before: qa/screens/e1d4a6e7/1280x600/integration-dark-visit-v_c.png. All 16 focused short-desktop/phone themed cases pass the original thresholds. Fix: 25509839.
- QA-INTEGRATION-004 — FIXTURE: actual server voice sample labels overflowed 390 px phone width; sample buttons now wrap within the card. Before: qa/screens/e1d4a6e7/390x844/integration-dark-rules.png. The same focused matrix has zero document overflow. Fix: 25509839.

- QA-FINAL-001 — FIXTURE: native video Play/Pause now controls the shared real-video clock; two actual generated MP4s retain the original0.2s drift bound. Fix: b906989f.
- QA-FINAL-002 — FIXTURE: initial Messages loading, service failure and retry are distinct from an empty list. Fix: b906989f.
- QA-FINAL-003 — FIXTURE: area-view preset requests no longer override manual 3D presets. Fix: b906989f.
- QA-FINAL-004 — FIXTURE: microphone setup failure and late permission grants release tracks/context. Fake-device tests only. Fix: b906989f.
- QA-FINAL-005 — FIXTURE: rule confirmation consumes the authoritative active response, clears its draft and uses edge-accurate server-session copy. Fix: b906989f.
- QA-FINAL-006 — FIXTURE: recorded clock/date/offset match citations across UTC/Tokyo/LA viewers. Fix: b906989f.
- QA-FINAL-007 — FIXTURE: constrained 3D view controls use the existing accessible Radix menu. Fix: b906989f.
- QA-FINAL-008 — FIXTURE: Motion/R3F read ms/s tokens correctly and refresh after an initial reduced preference without losing orbit. Fix: b906989f.
- QA-FINAL-009 — FIXTURE: chat links carry the exact event ID/time/camera. Fix: b906989f.
- QA-FINAL-010 — FIXTURE: ordinary-motion popup now animates after its portal mounts; actual opacity and live-preference draft/focus tests pass. Fix: a8329a47.
- QA-FINAL-011 — FIXTURE: persistent Radix tablist-wrapper focus has an inset tokenized ring. The earlier provisional panel diagnosis was rejected; its existing ring remains unchanged. Fix: 5cf05c57.

- QA-DOCTOR-001 — REAL logic / FIXTURE: no-Hub battery import mode no longer reports irrelevant missing camera IP prerequisites; privacy/clock checks remain. Regression failed first; fix: e018fcda.

## Owner decisions

- FONT-001: Inter selected by the owner in chat on Nov 3 after the three-font study. Default retained; decision commit recorded in docs/decisions.md.
- CAMERA-001: No Reolink Home Hub. The three battery cameras use imported clips.

- QA-CUTOVER-001 — REAL logic / FIXTURE: reviewed React now owns `/`, old consumer asset routes return404, preview alias matches byte-for-byte, actual root→visit navigation passes. Fix:060c583c. Both final UI reviews APPROVED; Both mechanical rechecks APPROVED: A9e3aa161 and Bd9a4e270.
- QA-WINDOWS-001 — REAL logic / FIXTURE: scan task invokes shared Python metadata scanner directly instead of an unavailable WSL Bash. Actual PowerShell scan passes. Fix:dd77d169.
