# Motion layer — integration and review

REAL logic; supplied scene, visits and messages are FIXTURE evidence. No camera,
Meta, spend, people-messaging backend or fake playable video is used here.

## Library choice

Motion `framer-motion@14.9.0` provides MotionConfig, motion elements,
AnimatePresence, useIsPresent, animation scheduling and exit cleanup. Sources checked:
[MotionConfig](https://motion.dev/docs/react-motion-config),
[useReducedMotion](https://motion.dev/docs/react-use-reduced-motion),
[AnimatePresence](https://motion.dev/docs/react-animate-presence).

The installed `dist/es/utils/reduced-motion/use-reduced-motion.mjs` captures
`useState(prefersReducedMotion.current)` without a state subscription. Its docstring
says it responds dynamically, but its implementation does not. Lead approved a thin
native `matchMedia` + React `useSyncExternalStore` bridge. One native listener is
shared across consumers and removed when the last consumer unmounts. The Motion hook
remains the library fallback; current native preference wins when supported.

No custom animation scheduler, easing library, timer, popup lifecycle, 3D pulse or path
implementation was added. Policy values come from frozen CSS tokens. Unknown/missing
duration or offset fails to zero movement; content remains visible if styles are missing.

## Exports

- `MotionProvider`: mount once above AppShell. It supplies token transitions and
  forces MotionConfig's current preference to always/never using the live bridge.
  Children retain identity, drafts and media state when the preference changes.
- `useMotionPreference()`: current reduced preference, including live OS changes.
- `useMotionPolicy()`: current durations, offsets and easing parsed from tokens.
- `useEntranceMotion('view'|'panel')`: props for an existing motion element.
- `PageTransition({viewKey,label,children})`: place inside the shell's main region.
  The new route is visible from its first frame; it enters by one spacing token.
  There is one route tree, no delayed outgoing interactive page. Stable navigation
  focus is preserved. If a focused outgoing control disappears programmatically,
  focus moves to the incoming labelled region with preventScroll.
- `PanelEntrance`: entrance for a newly selected evidence panel inside an existing
  Radix dialog. Do not put this outside the portal or replace Radix presence/focus.
- `PanelTransition({open,label,children})`: inline disclosure only. AnimatePresence
  manages exit; closing content is immediately inert and hidden to accessibility.

```tsx
<MotionProvider>
  <AppShell {...shellProps}>
    <PageTransition viewKey={route} label={`${pageTitle} view`}>
      {page}
    </PageTransition>
  </AppShell>
</MotionProvider>
```

Keep the floating chat outside PageTransition, so route changes retain its draft and
thread state. Do not key the provider by route, theme, preference, camera or visit.
Do not wrap a CSS grid Card in a new layout wrapper without preserving its grid area.
Prefer spreading `useEntranceMotion` on an existing motion element, or use
PanelEntrance within the dialog's content area. Do not animate layout height: the
short-screen house frame and scrollable panels must retain their approved dimensions.

## Coordinated integration requests (lead-owned)

1. Replace Chat/Twin direct `useReducedMotion` imports/calls with
   `useMotionPreference` from `../motion`. Their current initial preference behavior
   is correct, but the installed Motion hook does not adapt without a remount. Do not
   remount either component to update preference: that would lose drafts/orbit/media.
2. Keep Twin's existing observed-time path reveal, gap segmentation and event gating.
   Its CameraCone phase currently uses `clock.elapsedTime * Math.PI * 2`, a literal
   one-second cycle. Read `--v-motion-pulse / 1000` into the existing palette and use
   that as phase period (guard period > 0); reduced mode remains a steady event highlight.
   This is a token consistency change, with no geometry or association change.
3. Reserve bottom scroll padding for content behind the floating Messages pill rather
   than taking a global footer out of Home's constrained scene height.

These requests were sent to the lead; no other owner's source was edited. Final app
integration and the two fresh app reviewers must verify those coordinated changes.

## Preview and test scope

`npm run dev -- --port 8107` from web-next, then
`http://127.0.0.1:8107/next/src/motion/preview.html`.

The isolated preview composes real AppShell, Home, Attention, Chat and HouseView
components from current approved dependencies. Other page destinations are honestly
outside this task preview. Ask-home is disabled because no backend is connected.
Household messages are actual typed local messages; supplied null media stays unavailable.
The task-only `window.vigilMotionReview.seek(t)` supplies a recorded fixture clock to
the existing viewer; it is not a fake video player. Visit observation controls seek that
same clock. Root integration replaces this harness with the actual player clock.

Run `npm test` and `npm run build`. `node src/motion/qa.mjs` runs all eleven exact CSS
viewports, dark/light, ordinary/reduced motion, real controls and focus/scroll flows.
An optional `MOTION_QA_VIEWPORT=1280x600` selects a focused case. `MOTION_QA_SHA`
labels its output folder; production evidence must identify the exact source SHA.
`MOTION_QA_SHARD=0/2` and `1/2` split disjoint viewport groups across independent
browser contexts/processes; their reports are separate and every case remains required.
Output is `qa/screens/<source-sha>/<width>x<height>/` plus a JSON result ledger.

The first probe's Tab-from-last-control check reached browser chrome after correctly
restoring popup focus. Its raw output remains untracked. The final harness starts its
visible-focus traversal at a known navigation control, retains the same outline assertion
and independently requires the popup to restore its actual opener.

No unchanged Python suite is rerun in this task per lead instruction. Full Python/E2E
and exact pre-main timing remain lead-owned. Hardware GPU performance is unverified.
