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

- Clips/Media: library-first check uses Radix Select and shared shadcn-style UI/Modal/Tabs; native datetime-local inputs keep browser editing/date picking. Exact intersection selection joins supplied Clip/Visit ledger fields, so it stays deterministic domain code rather than adding a table/fuzzy-search library. Please add this one-line rationale to lead-owned docs/decisions.md.
- Clips/Media integration: onOpenClip emits actual clip IDs. onSearch sends q/camera/verdict/kind plus ISO timezone-aware start/end. Preserve a complete current-session state snapshot for local filtering; replacing it with an old server query subset prevents Clear/new queries from recovering unloaded records. Missing callback disables Apply with an honest local-filter explanation.
- Clips/Media: short-height browser regression requires both the first verdict and supplied story above the fold. Time range uses the shared Radix Modal; absent-image placeholders are compact, actual images retain their shared ratio. No shared component/style paths were edited.

- Wave 2 controls: REAL presentation/authorization logic consumes typed ownerActions/ruleActions and exact privacy_reviewed flag; FIXTURE browser proof and unit callbacks only. Library choices: reuse shared Radix Tabs/Dialog, shared Button/Card/VerdictBadge and shadcn native input pattern; native datetime/select avoids custom calendar behavior. Custom code is only Vigil-specific authorization, validation and real data presentation. Lead can copy this reasoning to its exclusively owned docs/decisions.md.
- Wave 2 controls integration: supply real callbacks/server notices and returned windows; UI never assumes callback success. Protected-object catalogue is intentionally read-only (lead-approved shared player integration owns tap-to-protect). Benchmark stays empty until measured true. Human confirmed no Hub/import mode and Inter. Independent review pending; qa/reviews/controls-builder.md records exact sources, evidence and remaining integration responsibility.
- Controls round 1 P2 fixed in 612c9ea0: ExpectedWindow row renders both supplied camera and zone lists; all-configured fallback only for two empty arrays. Camera names use actual camera data, zones humanize only supplied IDs because UIState has no zone-name catalogue. Unit/browser RED then GREEN recorded in qa/reviews/controls-scope-repair.md. Awaiting independent round 2.
## Wave 2 motion — source 4fa2342

- REAL: reusable motion exports and integration instructions live in `web-next/src/motion/README.md`. Root should place one MotionProvider above AppShell and PageTransition inside its main region; keep floating Chat outside the keyed route. Preserve page grid areas and media/draft/orbit identity.
- REAL: lead approved the native matchMedia/useSyncExternalStore bridge because installed framer-motion 14.9.0 useReducedMotion captures initial state without a subscription. Root should replace Chat/Twin preference imports centrally after independent motion review. Do not remount on preference changes.
- Request: Twin CameraCone phase uses a literal one-second period. Read existing `--v-motion-pulse` into the current palette and use it as a guarded period, keeping observed event gating, gaps and geometry unchanged. Builder did not edit Twin.
- Request: reserve internal bottom scroll padding clear of the floating Messages pill; do not reduce Home's constrained scene height with a global footer. Builder did not edit page or shell source.
- FIXTURE: isolated integrated preview runs on port 8107 with no data store/ledger. All 11 numeric viewports passed both themes/preferences, including scene presets, chat, dialogs, keyboard and scroll. Final screenshots/manifests are under `qa/screens/4fa2342/`; builder findings are in motion-review.md, pending independent review.

### Motion round-two correction — 47dddac6 / ebc421a9

- REAL: reviewer isolated the exported hook's initial-only library fallback registering an extra permanent bare-query listener. New unit and actual-browser tests first reproduced 0→2→1 across both query forms; fix 47dddac6 removes the library fallback hook and retains the native conservative snapshot, giving 0→1→0. Unsupported-native fallback is now explicitly tested.
- FIXTURE: final focused evidence is `qa/screens/ebc421a9/`; f61680ed/ebc421a9 add only QA waits for the first WebGL draw and mounted annotations. All eleven sizes and both themes exercise live preference changes, with the existing adaptive state/focus/draft, 20-route churn and active-tween regression retained. Full frontend suite now passes 75 tests. No Chat/Twin source edited; their listener/tween integration remains root-owned.


## Root resolution, Nov3 reviewed cutover060c583c

All seven tasks are independently APPROVED and integrated; final A/B R2 are APPROVED (cde38c03/80e217f0). Shared motion/provider, live preference hook, event-gated token pulse, scroll clearance and canonical camera owner validation are integrated and covered by final interaction matrices. Root owns all API/shared-state/transport/chat/point work; no builder is waiting on an outside-path request. See docs/react-review-ledger.md, QA_NOTES.md and docs/readiness.md for exact fixes and genuine field prerequisites.
