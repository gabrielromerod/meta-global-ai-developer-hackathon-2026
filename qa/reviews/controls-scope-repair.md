# Controls round 1 scope repair

REAL: `612c9ea0` fixes the independent review P2 in Settings expected windows.
Camera scope renders actual supplied camera names. Zone scope renders the supplied IDs
with underscores changed to spaces; UIState has no zone-name catalogue, so no zone
names or scope values are invented. Both lists appear when both are supplied.
"All configured cameras" appears only when both lists are empty.
Production edits touch only Settings/index.tsx. Owner guards, token handling, server
acknowledgement, cancellation, recorded windows and time validation are unchanged.

FIXTURE reproduction preceded implementation: four new unit cases exercised zone-only,
camera-only, combined and empty scope. Three failed before the change (20 existing/new
tests passed). The browser prop probe against unchanged `8e74611a` reproduced the
zone-only false fallback in all four viewport/theme pairs; 16 of 20 explicit scope-label
checks failed. Evidence is `qa/screens/8e74611a/scope-before/`.

After the fix, all 23 controls tests passed and the full frontend suite passed all 85
tests. `npm run build` passed. No existing test or assertion was relaxed. No unchanged
Python suite was rerun, per assignment.

FIXTURE browser check: `qa/screens/612c9ea0/scope-after/` contains 24 PNGs and
scope-results.json: 20 of 20 scope checks pass, zero console/network errors, actual
innerWidth/innerHeight 1280x600 and 390x844 in both themes. All four scope rows and
affected list top/bottom states are captured. Desktop document has no scroll/overflow;
phone list scrolls vertically. The four labelled before/after inspection sheets were
opened and inspected, plus full-size phone combined-scope and desktop zone-only images.

The reproducible harness is `web-next/src/pages/settings/qa-scope.mjs`; run from
`web-next` with `node src/pages/settings/qa-scope.mjs`. It intercepts only the local Vite
preview module and supplies explicit authored window variants from the original window,
configured doorbell and observed side_alley event target. It never contacts an API,
camera or owner endpoint. The default application fixture remains unchanged.

Four lead-owned UI provenance gates passed, 52 PNGs total, zero failures. Each media
directory includes ui-privacy.json and immutable proof-fixtures JSON snapshots; those
snapshots are committed with the proof. No camera pixels, credentials, audio, Meta calls,
spending or real owner mutation are involved. Real-data acceptance remains unverified.

Round 2 independent approval is pending; this is a builder repair report, not approval.
