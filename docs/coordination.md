# React wave coordination

Lead owns contracts, tokens, fixtures, package files, integration and backend.
Builders append requests below and keep edits within their assigned paths.

- Home/Attention: lead integration must retain normalized `v_ap` reason from b6e2199, provide real API state/player slots, and route clip IDs to clip records. Camera model/status values are never inferred by pages. Task preview is FIXTURE; field/model acceptance stays open.
- Home/Attention: library-first checks used Radix Tabs and shared shadcn-style Card/Chip/VerdictBadge/VideoTile/EmptyState/Modal. Page-specific relevance-order and paired-touch selection are custom because they select Vigil evidence rather than replace a library interaction component.
- Home visual dependency to Twin: selected-camera 1024×768 frame clipped lower scene labels with full controls in a narrow ~440px parent. Home's unchanged 180px guard passed at 184px, but visual review found the clip; see qa/screens/58a6098/four-three-1024x768/home-dark-view-8-hover.png. Twin owner fixed it in d37c10f with targeted boundary evidence; integrate that correction before final approval.

- W1 twin: FR-040 implementation and fixture QA are ready at source 4a1120e; lead should add the new geometry/browser tests to requirement traceability during integration. Keep status offline/fixture, never real-data Verified. Pass actual event rows as `positions.events` for camera pulses.
- W1 twin: library exception is the single normal React projected-label overlay. drei Html's nested root cleanup produced reproducible React 19 console errors, so OrbitControls/Line stay library-provided while projection/collision layout is custom. Compact/phone preset framing and a 266 px flex parent are covered.

- REAL: ChatPopup and MessagesPage share the same thread renderer; use lead-controlled threads/drafts/selection so popup/fullscreen remain synchronized. Root contract/token requests were resolved in 695ed91 and 5d786a4.
- REAL: callbacks gate send, evidence navigation and media actions; unavailable thread capability also blocks clip sharing. People messaging is browser-local, no backend.
- FIXTURE: standalone preview on port 8104 at /next/src/chat/preview.html; Ask-home deliberately disconnected in this component preview. Lead must supply actual cached-ledger callback during integration.
- FIXTURE: final 132 screenshots and reports in qa/screens/9cc0857; all numeric viewports and both themes. Fourteen npm tests pass; short-window regression and 44 contrast checks pass. Independent reviewer still required.
- CSS media thresholds repeat 640 px and 730 px because variables cannot be used in native media-query conditions; all other styling uses frozen tokens.
