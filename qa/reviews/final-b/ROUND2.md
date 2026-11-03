# Independent final app review B - round 2

Reviewed production source: `c965bedfd1649bc781e0ae211bd7848885f51b1f`, composed by
cherry-picking exactly `b906989f`, `a8329a47`, then `5cf05c57` atop the R1 evidence branch.
`git diff --exit-code 5cf05c57 HEAD -- . ':!qa'` is clean: the complete non-QA tree matches
Root's frozen production target. This review changes QA evidence/scripts only.

All acceptance evidence is **FIXTURE**: recorded ledgers, generated MP4/still inputs,
explicit service/microphone faults, or labelled diagnostic crops. It is not real-camera,
Meta inference, hardware microphone, or physical-device acceptance. The root cutover is
correctly gated on review; it was not treated as an outstanding preview defect.

The complete independent matrix exercised 8,518 states across all eleven exact CSS
viewports in both themes, including every route, visible hover control, keyboard focus,
internal panel top/bottom, selectors, popups, dialogs, camera selection and all presets.
No document overflow, healthy-flow console errors, failed requests or harness failures
were recorded. Desktop scrolling remains internal; phone content reflows and scrolls.
All 154 state indexes and 22 larger page summaries were opened and inspected, with
supplemental originals inspected individually. Matrix and screenshots are under
`qa/screens/c965bedf/`; the source is fixed throughout the run.

R1 findings are resolved. `1470x870/final-b-r2-native-*.png` and
`final-b-r2-native.json` show real native mouse Play/Pause and keyboard transport on two
genuine generated MP4s driving the shared clock. Maximum observed video drift is
0.0225 seconds, below the unchanged 0.2-second requirement; paused clocks remain still.
These opaque labelled crops contain no video/still pixels.

`1470x870/final-b-r2-repairs.json` records all 16 group-view/manual-preset combinations,
correct e17 navigation to 15245 seconds / 6:14:05 PM, visible chat 503 failure and real
local retry recovery, and a fake acquired microphone track stopped exactly once on
AudioContext setup failure. The ordinary floating popup reaches opacity 1 and transform
none; both live preference changes retain the same input, draft and focus. Initial
reduced motion changes to 0.48-second view motion and 1.6-second pulse timing without
moving the camera. Panned camera/target state is also preserved.

Confirmed rules clear the draft and read "Active for this server session."
`1470x870/final-b-r2-rule-confirmed.png` and `final-b-owner-rule.json` bind the actual
isolated edge/cache-only response. UTC, Tokyo and Los Angeles browser contexts all show
the same recorded clock, Nov 2, 2026 date and UTC-08:00 offset, with separate screenshots.

All eleven toolbar bounds pass. The phone camera/view-controls menu scrolls smoothly to
Reset, gives it visible keyboard focus, and returns focus on Escape in both themes;
`390x844/final-b-r2-menu-bottom-*.png` and `final-b-r2-menu-scroll.json` include the
stable scrollbar gutter. Both theme wrapper focus rings remain visible when Radix leaves
entry focus on the wrapper with inline outline:none. All 18 computed text/surface pairs
pass AA; their minimum contrast is 6.5623.

The actual exported-still mouse picker and keyboard pixel fields were exercised against
an explicit asserted FakeBackend. Its calls stay empty until future-cost approval and
become exactly ["protect"] afterward; the protected object appears with server-session
copy. Committed point evidence crops include coordinates, cost approval and session text
only, excluding still pixels. API-backed E2E additionally verify owner-token session
storage, check-in countdown, window create/cancel persistence, actual playback/overlays,
voice editable transcript/server scope, local household sharing and shared thread drafts.

Independent validation: npm ci (237 packages, no reported vulnerabilities), 134 frontend
tests, production build, 21 API-backed/generated-video E2E (58.95 seconds, two existing
deprecation warnings), Ruff check and format check (293 files) passed. The existing Vite
large-bundle warning remains. Root owns the full pre-main backend suite. No production
test was edited, skipped or loosened.

Review harness corrections addressed selector ambiguity, the corrected server-session
copy, minified three-digit CSS hex colors and fractional mouse-to-source-pixel rounding.
The point probe now records actual MouseEvent coordinates and verifies the exact source
pixel mapping, then independently enters 160/600 by keyboard. No production behavior was
changed to accommodate the harness.

The main port 8119 server uses its isolated data, DB, ledger and cache. Actual settings
were asserted sandbox/cache-only/closed-loopback/invalid sentinel before serving; its
ledger still has zero model-call rows. Auxiliary model-positive work uses the explicit
FakeBackend; generated pipeline calls are intercepted by recorded model mocks. No
camera, vendor request, paid operation or physical microphone stream was used.

The unchanged screenshot gate passed all 8,720 base PNGs with zero failures. A small
addendum contains actual sidebar/mobile navigation and all notification-item clicks in
both themes (52 actions), with four inspected action indexes. These captures explicitly
wait for the expected visit ID after Radix closes before recording the settled screen.
The addendum provenance and staged-secret results follow below.
No new blocking finding remains in the inspected source.

The addendum's 56 PNGs passed the same unchanged gate with zero failures. The union
contains 8,776 exact reviewed PNGs; a final hash check confirms every staged PNG equals
one of those manifest entries. Four additional action indexes were inspected. Gitleaks
v8.30.1 scanned the complete staged text diff (19.64 MB) and found no secrets. The demo
privacy/metadata checks passed with zero media files; they are not a footage claim.
The production-source comparison remains clean and the original ten newline-only
tracked modifications remain unstaged. Full R1 generated-media captures remain untracked.

No new blocking findings. All ten independent R1 findings are resolved on this source.

APPROVED
