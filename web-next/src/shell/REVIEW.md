# Shell review handoff

This branch includes production Home and Twin dependency commits for the review
harness only. The lead merges their original owned commits separately.

Start from `web-next` with `npm ci` then `npm run dev -- --port YOUR_PORT`.
Open `/next/src/shell/preview.html`. Font variants use `?font=inter`, `?font=manrope`
and `?font=dm-sans`. Inter is the default. All fonts are local OFL 1.1 assets.

Run `npm test`, `npm run build`; the shell/UI DOM tests carry their own jsdom
directives. Run browser evidence with `VIGIL_UI_BASE_URL` set to your own preview URL
then `node src/shell/qa.mjs`. Never share a server port or spend/SQLite files.
The standalone harness makes no API, camera or model request.

Shell owns the navigation callbacks, responsive rail/mobile dialog, theme scope,
notification dropdown and shared UI components. Preview-only page selection and
dialog contents exist solely to exercise those callbacks using authored fixtures.
Home/Twin handle their own layouts/scene behaviors; root API/player/chat integration
belongs to the lead. Unsupported pages in this harness use clear review-only empty
states; this is not the final `/` app.

Inspect dark/light, every nav hover/click, mobile Navigation, all configured House
views, notification top/bottom and item open, Escape/focus restoration, scrollable
panels and the floating message opener. Root page must not scroll on desktop.
Screenshots use the owner's exact CSS viewport dimensions; these are not physical
hardware acceptance claims. Phone is single column with document scrolling allowed.

Domain cards compose adapted shadcn Button/CVA/Slot, Radix Dialog, Tabs, DropdownMenu
and Tooltip. Domain evidence needs its own content composition, not a separate
dropdown/focus/navigation engine. Dark/light text token combinations meet at least
4.5:1; the measured minimum in shell-contrast.json is 5.58:1.

Security evidence remains FIXTURE: no real camera, Meta API or people messaging
acceptance. gitleaks is absent locally; CI owns that scan. Privacy scans of UI PNGs
use documented --allow-unmapped (no camera imagery; audio checked) plus manual
visual review and the fail-closed metadata scanner. No raw footage is added.

Final shell evidence: qa/screens/f2ca626/ (448 PNGs); qa/fonts/ (3 variants);
qa/references/shell/ (3 public references). All 454 PNGs passed the privacy/audio
scan for unmapped UI media and the fail-closed metadata scan. Representative
small-window, phone, light overlay and font frames were opened and inspected.
No unsafe imagery or identifying home details are present. Earlier diagnostic
captures were preserved under the OS temp directory, not added to Git.

Verification observed: npm test 39 passed; tsc/Vite build passed; ruff check and
format check passed; default Python suite 1474 passed, 24 deselected, one existing
Starlette httpx deprecation warning (212.80s). Shell text contrast 44 pairs passed,
minimum 5.58:1. Human font choice is open in QA_NOTES.md with Inter default.

Dependencies used for these screenshots: original Home commits 07effdd,5674ab3,
b613fc1,4fc0631,7be158f; original Twin commits ed7f70d,90078de,58c7a7c. Later Twin
hover/gap-padding fixes do not change the no-position shell scene and are reviewed
by the Twin task separately. Lead-approved state fixture is exactly b6e2199.
