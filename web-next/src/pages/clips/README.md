# Clips and Media library — builder handoff

Exports: `ClipsPage(PageProps)` and `MediaPage(PageProps)` from `../media`.
Both compose the single `EvidenceBrowser`; filters/model, menus, grid and unavailable
states have one implementation. All data comes from `state` and callbacks. No API fetch,
model call, camera connection or invented evidence exists in these pages.

## Library choices

- [Radix Select](https://www.radix-ui.com/primitives/docs/components/select) owns camera
  and verdict menus, keyboard navigation and focus. Shared shadcn-style Button, Card,
  Chip, Tabs, ClipCard, Modal and EmptyState are reused.
- [shadcn Input](https://ui.shadcn.com/docs/components/base/input) follows native input
  semantics. Labelled native search and datetime-local inputs keep browser editing and
  date picking; the shared Radix Modal owns the Time range disclosure. No custom calendar
  or dropdown interaction is implemented.
- The deterministic exact-text/intersection selection is domain code: it joins supplied
  clip records to supplied visit stories and keeps recorded times/verdicts intact.
  A table or fuzzy-search library would not supply that ledger relationship.
- The grid composes shared ClipCard without a second card implementation. Rows preserve
  intrinsic content. Absent-image frames use a compact token-sized empty area; actual
  images retain the shared aspect ratio. This keeps verdict and story visible initially
  in short windows without inventing thumbnails or trimming source text.

## Lead integration

`onOpenClip` receives the actual clip ID, including when its media URL is null. Open its
real visit/evidence with an unavailable-media state; never treat a camera ID as a clip ID.
`onSearch`, when provided, receives all six filters: q, camera, verdict, kind, start, end.
Date inputs explicitly use the browser/device's local time and submit timezone-aware
ISO strings. They never change recorded `clock` or session-relative `t0` values.
Reversed/invalid dates block submission visibly. Time filtering with an unavailable
session date is rejected rather than widened. Without `onSearch`, local filtering still
works, the Apply action is disabled and its explanation says filters update as typed.

Keep the complete current-session `state.clips`/`state.visits` as the local filter source.
Do not replace that source with an earlier query subset: Clear/new queries need the whole
loaded collection. Lead-owned TanStack Query can revalidate the server state/search.

## Isolated preview

```cmd
cd web-next
npm ci
npm run dev -- --port 8105 --strictPort
```

Open `http://127.0.0.1:8105/next/src/pages/clips/preview.html`.
`?route=media`, `?theme=light`, and `?empty=1` select real alternate fixture states.
The harness uses only frozen authored fixtures; all media/avatar URLs are null. Callback
effects are exposed only for review in `window.clipsReview`; no people or clips are faked.
Production API/player/detail state remains lead-owned.

## Evidence and verification

Source checkpoint: `c820bb4`. Initial short-window regressions failed at 1280×600:
first verdict bottoms were 659/715 px, and first story bottom was 653 px. The fixed browser
regression retains the 600 px boundary and checks actual rendered card contents.
Tests cover intersections, story search, inclusive timestamps, newest-first order,
unavailable categories/media, missing dates, ISO callback values, actual clip IDs, reset,
invalid ranges and disabled callbacks. Frontend suite: 56 tests passed at checkpoint.
`npm run build`, Ruff check and Ruff format check passed. The optional Python rerun was
stopped on the lead's request after partial progress; no passing result is claimed.
Root owns the full Python/E2E runs before main merge.

FIXTURE: the browser matrix passed 44 cases: both pages, both themes and all eleven exact
CSS viewports listed by the owner. Additional normal-motion, true-empty and keyboard
checks passed 12 cases. No console errors, failed network requests, desktop document
scroll, horizontal overflow or clipped card contents were observed. The first supplied
story and verdict are visible at every initial desktop size. All menus, controls, clip
callbacks, internal scrolling, dialogs, hover and visible keyboard focus were exercised.
240 sampled text/background contrast pairs measured at least 6.16:1.

The source-bound evidence is `qa/screens/c820bb4/`: 3,398 matrix PNGs, 24 additional PNGs
and 45 read-only contact sheets (3,467 PNGs total). All 44 matrix sheets and the additional
sheet were opened and inspected, with representative short-window and phone originals
opened at full size. This is CSS-viewport testing in Chromium on Windows, not certification
on physical Mac or phone hardware. It does not prove camera privacy polygons or live APIs.
An independent reviewer must return APPROVED; the builder makes no approval claim.


## Field boundary correction

FIXTURE, source `8f4ca05`: the actual rendered enabled search, Camera, Verdict and date
fields reproduced a non-text contrast regression against their inside surfaces
(1.52:1 dark and 1.50:1 light; 64 failures in 96 rest/hover/focus measurements).
The owned `.evidence-control` border now uses existing `--v-muted`; decorative cards
keep their original borders. The unchanged >=3:1 browser assertion passes all 96
measurements against both adjoining surfaces; minimum is 5.73:1. All measured field
widths and heights match the pre-fix run. This supplements the original matrix;
the earlier 6.16:1 text measurements did not test field boundaries.

Targeted evidence: `qa/screens/8f4ca05/field-boundaries/` contains 96 screenshots,
four inspected contact sheets and results.json. Both pages and themes were checked
at 1280×600 and 390×844, including date-dialog fields. Full frontend suite (56 tests)
and TypeScript/Vite build passed again. Run from web-next with
`set VIGIL_QA_SHA=8f4ca05` then `node src/pages/clips/boundary-qa.mjs`.
