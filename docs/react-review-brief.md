# Independent React wave review

Read-only production review. Do not repair source. Use your assigned isolated checkout,
branch and Vite port. Never share data directories, DBs or ledgers. No Meta/camera calls.
Read CLAUDE.md, web-next/README.md, contracts.ts and the task's README/REVIEW.md.
The user explicitly replaces the old Preact direction with React. Source dependencies in
your review checkout were composed by the lead from exact current builder revisions.

## Requirements

Use React/TypeScript/Vite, shadcn patterns/Radix, Tailwind, Lucide, Motion,
TanStack Query integration slots, R3F/drei. Library-first; custom exceptions documented.
No invented data/actions/metrics/people. Fixtures are labelled Demo data. Every verdict
has icon plus word. Unknown roles fail closed; no identity inference. Owner controls in
sandbox disabled. UI-only fixture previews may expose callbacks to demonstrate actual
local interactions, but cannot pretend a missing backend exists.

Use all named tokens for presentation; no duplicate component implementations. Both
themes AA contrast, visible keyboard focus, reduced motion, solid base surfaces,
translucency only overlays. Desktop fills 100dvh with no document scroll; internal
panels scroll with stable gutters. Phone reflows to a single column and may scroll.

## Exact CSS viewport matrix

1470x870, 1512x895, 1728x1030, 1920x960, 1536x730, 1280x600,
1366x650, 1024x768, 1180x820, 2560x1000, 390x844.
These are the owner's browser viewport approximations, not physical-device certification.
Confirm actual innerWidth/innerHeight in each run. Do not claim native Windows scale or
macOS rendering from a Linux/Windows headless browser emulation.

## Browser work

Run npm ci, npm test, npm run build. Start own Vite server on the assigned port using
the existing task preview HTML. Do not use another worker's running server.
Playwright: hover every interactive element and capture hover states; click every
control; tab through visible focus; scroll every panel fully; open every menu/dialog.
Twin: drag down aggressively (never below ground), zoom/pan bounds, all presets,
camera selection, blind hover labels, event/path/gap evidence, short constrained parent
and narrow aspect. No geometry underground or through walls, no right-side route.
Test light/dark and reduced motion, transitions/remount, empty and unavailable states.
Confirm no console errors, failed requests, overflow, overlaps or clipping. Inspect the
actual PNGs (contact sheets may help indexing, but inspect suspicious states individually).
Do not trust only builder scripts or numerical layout guards: assess whether it feels right.

Capture own evidence under qa/screens/<reviewed-short-sha>/<viewport>/review-<task>-*.
Report one short paragraph per finding: wrong behavior, location, viewport, screenshot
path, severity and concrete fix. End exactly APPROVED or CHANGES REQUESTED.
No findings means explicitly state tested scope and evidence location, then APPROVED.
At most three review rounds per task. Never weaken tests or assertions to produce approval.

## Evidence gate

For generated UI PNGs only, use the lead's current utility by absolute path:
`uv run python C:/Users/lords/.codex/worktrees/ad9e/meta-global-ai-developer-hackathon-2026/scripts/ui_evidence.py <your-screenshot-root> --source <your-local-preview-url> --reviewer <agent-id> --fixture web-next/src/fixtures/state.json --fixture web-next/src/fixtures/twin.json --reviewed`
This binds manually reviewed PNG hashes, null-media fixture hashes, decode/audio and
metadata checks; it makes no footage polygon claim. Normal camera footage remains on
the strict privacy scanner. Commit only review findings/evidence/manifests in your branch,
not production changes. Keep original Python line-ending edits untouched. If cleanup is
blocked, leave drafts untracked; no reason to delete them or request user approval.
