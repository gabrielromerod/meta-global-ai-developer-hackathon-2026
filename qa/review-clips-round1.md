# Clips and Media independent review — round 1

Reviewed production source: `7c2ea321bde6ff0e753be4c855f424d983ea2efb` on
`codex/review-clips-media`. Reviewer: `r2_clips`, November 3, 2026. Production was read-only.
Preview: `http://127.0.0.1:8115/next/src/pages/clips/preview.html`.

No product findings were observed in the completed browser review.

1. Entry and layout: healthy. Both pages were tested at every exact CSS viewport:
   1470×870, 1512×895, 1728×1030, 1920×960, 1536×730, 1280×600, 1366×650,
   1024×768, 1180×820, 2560×1000 and 390×844. Actual inner dimensions were asserted.
   Desktop uses internal results scrolling with no document scroll; phone reflows to one
   column without horizontal overflow. Initial desktop verdict and full first story are
   visible, including 1280×600. Card captions retain their intrinsic height.
2. Filters and menus: healthy. Every camera, verdict and category was selected; every
   owned button, input, card and menu option was hovered. Search, camera, verdict and kind
   intersect correctly and Clear restores the full five supplied clips. The Media time
   range adds the date intersection. Camera/category/query absence shows honest empty
   results. Counts are derived from the fixture records.
3. Time range: healthy. The device-local explanation is visible. Reversed intervals show
   an error, return no results and disable Apply; clearing dates recovers. Local dates
   submit ISO timestamps with `Z`. Equal start/end at the actual `clip_v_c` timestamp
   selects that exact clip in America/Los_Angeles, UTC and Asia/Tokyo; all three submit
   `2026-11-03T02:13:06.000Z`. A valid interval containing no evidence stays empty and
   clears back to five clips. Existing passing unit tests additionally cover malformed
   dates and missing session dates without widening the search.
4. Cards and evidence: healthy. Every card calls back with its actual clip ID; opening
   visit evidence uses the corresponding actual visit ID. Supplied null thumbnails/video
   remain unavailable. No image/video elements or invented media were introduced. Clip
   results and dialog bodies were scrolled to the end. Fixture evidence stays labelled
   Demo data; this preview does not prove a production API/player integration.
5. Keyboard, appearance and motion: healthy in tested scope. Native Tab/Shift+Tab,
   Enter, Escape, select arrows and category arrow/Home navigation were exercised.
   Focus is visible and returns to menu/card/dialog openers. Both themes and reduced
   motion passed all 44 matrix cases; another 44 normal-motion, true-empty, keyboard and
   route/theme remount cases passed. No page/console errors or failed requests were
   observed. All 528 enabled-field rest/hover/focus samples meet 3:1 against both adjoining
   surfaces (minimum 5.7268:1); all 1,990 sampled enabled text pairs meet 4.5:1 (minimum
   5.7268:1). These are scoped measurements, not a full accessibility certification.

Evidence is [screens/7c2ea321](screens/7c2ea321/): 2,490 matrix PNGs, 220 additional-state
PNGs, four date-boundary/empty-interval PNGs and 44 contact indexes (2,758 PNGs total).
All 44 indexes were opened and inspected, with original short-window, phone, menu,
validation, clip, scroll and date screenshots inspected at full size. The images contain
generated UI from authored null-media fixtures, no camera pixels. This is Chromium on
Windows with CSS viewport emulation, not physical-device or native OS scale certification.

Representative originals:

- [1280×600 initial](screens/7c2ea321/1280x600/review-clips-clips-dark-000-initial.png)
- [1280×600 date error](screens/7c2ea321/1280x600/review-clips-media-dark-049-reversed-range.png)
- [1280×600 results end](screens/7c2ea321/1280x600/review-clips-clips-dark-049-results-bottom.png)
- [390×844 camera menu](screens/7c2ea321/390x844/review-clips-clips-dark-019-Camera-menu.png)
- [390×844 date dialog](screens/7c2ea321/390x844/review-clips-media-light-038-time-dialog.png)

Validation: `npm ci` passed with zero audit vulnerabilities; `npm test` passed 78/78;
`npm run build` passed. `uv run ruff check .` and `uv run ruff format --check .` passed
(248 Python files). The unchanged Python suite was not repeated; Root owns it. Gitleaks
was unavailable on PATH, so no local gitleaks result is claimed. The source-bound UI
evidence gate is recorded in `screens/7c2ea321/ui-privacy.json` after completion.

Review harness notes: early capture attempts were superseded after correcting a dynamic
Radix-tab enumeration and adding focus waits. Phone popup captures use exact viewport
screenshots because full-page capture dismissed Radix popups during capture. All four
phone cases were rerun with menu-visible assertions before and after capture. Superseded
images remain untracked in `qa/drafts/7c2ea321`; they are excluded from this evidence set.
Only QA scripts, evidence and this review are included in the review commit. Existing
Python line-ending changes remain untouched and unstaged.

Evidence gate: the lead's current absolute `scripts/ui_evidence.py` completed with
`UI screenshot provenance: 2758 named PNGs; 0 failures`. The manifest binds the reviewed
PNG hashes and frozen null-media fixture copies, and checks decode, audio absence and
metadata. It does not claim footage polygon acceptance.

APPROVED
