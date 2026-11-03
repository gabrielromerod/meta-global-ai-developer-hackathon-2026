# React wave coordination

Lead owns contracts, tokens, fixtures, package files, integration and backend.
Builders append requests below and keep edits within their assigned paths.

- Home/Attention: lead integration must retain normalized `v_ap` reason from b6e2199, provide real API state/player slots, and route clip IDs to clip records. Camera model/status values are never inferred by pages. Task preview is FIXTURE; field/model acceptance stays open.
- Home/Attention: library-first checks used Radix Tabs and shared shadcn-style Card/Chip/VerdictBadge/VideoTile/EmptyState/Modal. Page-specific relevance-order and paired-touch selection are custom because they select Vigil evidence rather than replace a library interaction component.
- Home visual dependency to Twin: selected-camera 1024×768 frame clipped lower scene labels with full controls in a narrow ~440px parent. Home's unchanged 180px guard passed at 184px, but visual review found the clip; see qa/screens/58a6098/four-three-1024x768/home-dark-view-8-hover.png. Twin owner fixed it in d37c10f with targeted boundary evidence; integrate that correction before final approval.

- W1 twin: FR-040 implementation and fixture QA are ready at source 4a1120e; lead should add the new geometry/browser tests to requirement traceability during integration. Keep status offline/fixture, never real-data Verified. Pass actual event rows as `positions.events` for camera pulses.
- W1 twin: library exception is the single normal React projected-label overlay. drei Html's nested root cleanup produced reproducible React 19 console errors, so OrbitControls/Line stay library-provided while projection/collision layout is custom. Compact/phone preset framing and a 266 px flex parent are covered.
