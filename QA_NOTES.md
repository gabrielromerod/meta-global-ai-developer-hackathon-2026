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

## Owner decisions

- FONT-001: Inter selected by the owner in chat on Nov 3 after the three-font study. Default retained; decision commit recorded in docs/decisions.md.
- CAMERA-001: No Reolink Home Hub. The three battery cameras use imported clips.



- QA-INTEGRATION-001 — FIXTURE: snapshot stayed disabled after a metadata seek. Ready/can-play/seek events now update decoded-frame availability; actual MP4 decode/seek/overlay/snapshot E2E passes. Fix: 49782952.
- QA-INTEGRATION-002 — REAL logic / FIXTURE: full Attention no longer loses normal-history filters or urgent items beyond five. Frontend and API tests failed first, then passed. Fix: 49782952.
