# Independent final app review B — round 1

Reviewed production source: `9a8ced22c67ce734bb498d8eb8ee173f724fb045`.
All evidence is **FIXTURE**: recorded ledgers, generated media, explicit fault injections,
or labelled diagnostic crops. No camera, successful Meta inference, or physical-device
acceptance is claimed. Production was not edited. The `/` cutover/removal is correctly
gated on final review and is not a finding in this preview review.

P1 — Native video Play does not advance the shared evidence clock, and native Pause is
overridden by the timeline loop. At 1470×870, native playback reached 1.6586 s while the
shared clock stayed at 1 s and still offered Play; after shared playback, native Pause
was immediately undone. Couple native transport/time events to the shared player/3D
state and distinguish internal synchronization from user actions. Screenshots:
`qa/screens/9a8ced22/1470x870/final-b-native-play-readout.png` and
`final-b-native-pause-readout.png`; these are labelled crops of exact observed JSON,
containing no video pixels. Full generated-video captures remain untracked.

P2 — A Home group view permanently overrides subsequent manual 3D presets. At 1280×600,
select Front garden, then Top-down: Front remains selected and the rendered camera pose
does not change. Treat the group selection as an initial/requested preset, then allow
manual changes. Screenshot:
`qa/screens/9a8ced22/1280x600/final-b-front-garden-top-ignored.png`.

P2 — A failed chat-envelope request is represented as empty data. With an injected
GET `/api/ui/chat` 503 at 1470×870, Messages says “No threads available” and offers no
error or retry. Distinguish pending, failed and genuinely empty envelopes, and expose a
retry. Screenshot:
`qa/screens/9a8ced22/1470x870/final-b-chat-service-error-as-empty.png`.

P2 — Microphone acquisition is not cleaned up when audio-context setup fails. At
1470×870, an explicitly fake stream is acquired before an injected AudioContext
constructor failure; the stop counter stays zero both after the error and after closing
the dialog. Cleanup must stop acquired tracks even before recording becomes true.
Screenshot: `qa/screens/9a8ced22/1470x870/final-b-microphone-start-failure.png`;
`final-b-faults.json` records the fake counters. The initial fault harness was corrected
before this reproduction; its first attempt was denied by headless browser permissions
and obtained no recording.

P2 — Confirmed rules still appear as unconfirmed drafts. Against a real isolated
edge/cache-only API at 1470×870, r10 becomes Active in Current rules and the server,
but the draft still says Draft and its Confirm button stays enabled. Consume the
top-level confirmation response or clear the completed draft. The edge response also
incorrectly calls itself Sandbox. Screenshot:
`qa/screens/9a8ced22/1470x870/final-b-rule-still-draft-after-confirm.png`.

P2 — Built CSS time units are misread by the 3D view. At 1470×870 the production CSS
returns `.48s` and `1.6s`; `readPalette` divides their numeric values by 1000, producing
0.00048 s view motion and a 0.0016 s pulse. Presets therefore snap in one frame and the
pulse period is 1000 times too short. Use the same unit-aware token parser as Motion.
Screenshot: `qa/screens/9a8ced22/1470x870/final-b-motion-timing-no-preference-readout.png`;
the exact observed values are bound in `final-b-initial-reduced-motion.json`.

P2 — Starting with reduced motion leaves stale zero timings after the preference is
removed. At 1470×870, CSS returns `.48s` and the current media query is false, but the
3D palette still has zero duration and pulse period. Refresh timing values on the shared
preference signal without recreating the scene. Screenshot:
`qa/screens/9a8ced22/1470x870/final-b-motion-timing-reduce-readout.png`.

P2 — Chat event citations lose the cited event selection. At 1470×870, Ask your home
“side gate,” then open e17: v_c opens at 15186 s / 6:13:06 PM rather than e17 at 15245 s /
6:14:05 PM. Carry the event ID through navigation and seek its normalized event/camera
after the visit loads. Screenshot:
`qa/screens/9a8ced22/1470x870/final-b-chat-citation-wrong-time.png`.

P1 — Floating Messages is invisible in ordinary motion. At 1470×870, clicking its pill
and waiting 700 ms leaves the portaled dialog at opacity zero and y=16 px. The pill
disappears, and the dialog is only present in the DOM. Reduced motion displays it.
Mount its entrance controller with the portaled content and assert actual computed
opacity/transform in browser tests. Screenshot:
`qa/screens/9a8ced22/1470x870/final-b-floating-popup-no-preference.png`;
`final-b-floating-popup.json` includes the reduced-motion comparison.

P2 — Phone 3D tools are clipped rather than reflowed. At 390×844, the house panel ends
at x=365, while Zoom in ends at x=403.25, Zoom out at x=443.25 and Reset at x=483.25.
Provide an accessible compact tools menu or wrapping layout. Screenshot:
`qa/screens/9a8ced22/390x844/final-b-phone-toolbar-clipped.png` and measured bounds in
`final-b-phone-toolbar.json`. Playwright can auto-scroll the hidden overflow to click these controls, which does not make them visually accessible.

## Validation

Independent `npm ci`, 128 frontend tests and production build passed. All seven
API-backed/generated-media React E2E tests passed in 26.62 seconds, with two existing
deprecation warnings. These tests do not invalidate the independent findings above.
No production test assertion was changed. Whole-checkout Ruff check and format check
passed (280 files). The final matrix has 8,490 captured states covering all eleven
exact CSS viewports in both themes, with no document overflow, healthy-flow console
errors, failed requests or harness failures. The final matrix includes hover, keyboard,
scroll, menus, dialogs, camera selection, presets and live reduced-motion changes.
Playwright DOM visibility and successful clicks are not substitutes for computed
opacity or unclipped controls: the findings above remain blocking.

All 154 inspection indexes and 22 larger page summaries were opened and inspected;
finding originals and selected full-resolution states were inspected separately.
`final-b-contrast.json` records 18 computed text/surface pairs, all above WCAG AA,
with a minimum ratio of 6.5623. The matrix is browser viewport emulation, not physical
Windows or Apple-device acceptance. Phone navigation was additionally worked through
all eight destinations and twelve keyboard steps.

The screenshot provenance manifest is `qa/screens/9a8ced22/final-b-privacy.json`.
All 8,701 named PNGs passed the unchanged decode/audio and metadata gate with zero
failures. Nine pinned fixtures bind exact null-media API states and explicitly labelled diagnostic JSON to the
named reviewed PNGs. Full generated-video captures are excluded. `demo/` privacy and
metadata checks passed with zero media files; that result is not a footage claim.
Fresh frontend verification repeated 128 passing tests (4.86 seconds) and a successful
production build; the existing large-bundle warning remains.
Gitleaks v8.30.1 found no secrets in the QA scripts or the complete staged text diff
(22.66 MB). A containerized git-history scan
could not follow Windows worktree metadata and scanned zero commits; no history-scan
pass is claimed. The root integrator owns the full pre-merge backend suite; this
independent review ran the seven React integration E2E.

Harness corrections are confined to review scripts: hidden native select helpers were
excluded from visible targets, camera selection uses the actual responsive menu/rows,
and phone screenshots capture the viewport to avoid disturbing an open Radix menu.
Completed frozen-source cases were resumed without changing their assertions.

The main server uses its own port 8119, data, DB, ledger and cache. The corrected
VIGIL-prefixed settings were asserted as sandbox, cache-only and closed-loopback before
serving; the durable ledger had zero model-call rows. Auxiliary owner/video tests use
distinct temporary roots and explicit fakes or recorded model mocks. Media-bearing full
screens remain untracked; only pixel-free, explicitly labelled diagnostic crops are
eligible for this evidence commit.

CHANGES REQUESTED
