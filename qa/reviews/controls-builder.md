# Wave 2 controls builder evidence

Branch `codex/react-controls`; preview `http://127.0.0.1:8106/next/src/pages/settings/preview.html`.
CMD: `cd /d C:\Users\lords\.codex\worktrees\rx-controls\meta-global-ai-developer-hackathon-2026\web-next` then `npm run dev -- --port 8106`.
Restart with Ctrl+C and the same command. Rules adds `?route=rules`; Benchmark adds `?route=benchmark`.

REAL: Rules, Settings and Benchmark render supplied PageProps. Sandbox owner controls
stay disabled; edge token entry and owner mutations have separate callback/owner guards.
Window validation sends timezone-aware ISO and closes only when a matching new server
window arrives through props. Recorded B-prime window remains immutable and expired.
No inferred camera health, model, clock measurement, privacy approval or benchmark exists.
Privacy is Reviewed only with explicit true and non-blocked camera status. Missing review
flags are unconfirmed; false or blocked is Review required. Phone voice callbacks are
separate from camera audio. Protected objects link real supplied visit IDs when available.

Implementation commits: `1dbf554`, `c0dce4d`, `f6e05af`, `d8ba87b`.
Dependency-only `7652774` is the lead's `49d3ee4`; `715e677` is exact approved `5f717af`.
Do not duplicate those two lead changes during integration.

FIXTURE: browser proof uses authored null-media fixtures and explicit edge/empty/draft/
pending/error/review-flag states. Callback verification dialogs explicitly say no home-box
contact or state mutation. No camera, Meta, spending, microphone recording or real owner
change occurred. All real-camera review and benchmark acceptance remain unverified.

`settings.test.tsx`: 19 tests cover authorization, missing callbacks, token clearing,
exact callback payloads, reversed/over-12-hour windows, matching server acknowledgement,
immutable recorded windows, original recorded offsets, check-in expiry props, explicit
privacy review, draft/voice callbacks, protected-object evidence and honest benchmark.
Final complete frontend suite: 81 passed, build passed. Ruff check passed and format
check passed (220 files after dependency synchronization). Root owns unchanged full Python/E2E/main merge suites.

The last full frontend run before approved Chat test synchronization reproduced the
pre-existing `chat/index.test.tsx:80` immediate visibility race (80 passed, 1 failed).
After the lead-authorized independently approved `5f717af` was cherry-picked exactly,
81 passed. The same visible-state assertion is awaited; no assertion was removed or
weakened and no Chat production code changed.

FIXTURE visual evidence: `qa/screens/f6e05af/final/controls-results.json`: 198 state/layout
cases and 506 keyboard focus observations, 0 failures, 0 console/network errors, 2288
unaltered PNGs. All eleven exact CSS viewport sizes were checked in Chromium on Windows:
1470x870, 1512x895, 1728x1030, 1920x960, 1536x730, 1280x600, 1366x650, 1024x768,
1180x820, 2560x1000, 390x844. Both themes, reduced motion, native select, disabled guards,
dialogs, hover/focus, reversed/long windows, pending/error, empty and review flag states
are captured. Desktop document dimensions and scrollY are asserted; phones reflow and scroll.

Builder image inspection opened every final PNG set using all 154 labelled indexes in
`qa/screens/f6e05af/inspection/`, plus full-size sensitive/small states. Those original
images are unchanged. Contact inspection caught that tab keyboard focus automatically
activates Radix tabs, so some broad harness named scroll shots followed the last focused
tab. Layout checks preceded this helper and remained valid. The harness now explicitly
reselects the requested tab. Correct panel-specific scrolling is independently asserted
and captured for all sizes in `qa/screens/d8ba87b/panel-scroll/`: 88 cases, 176 PNGs,
0 errors. The final Backyard 2 camera is entirely visible at the bottom of each viewport.
All twelve supplemental panel indexes were opened and inspected.

`qa/screens/d8ba87b/followup/`: 22 cases, 528 natural Tab/Shift+Tab steps, ordinary motion,
modal trap/return, real mouse-wheel scrolling, 44 PNGs, 0 errors. All four indexes and
full-size date focus images were opened. Source d8ba87b changes only native datetime
focus-within ring; geometry is unchanged from f6e05af. Enabled border contrast measured
9.44:1 dark / 6.16:1 light; enabled text 17.22:1 / 14.63:1. Earlier enabled border
contrast failed at 1.89:1 / 1.62:1 and was corrected using existing tokens. A natural Tab
probe exposed the native calendar subsegment's missing host focus-visible state; whole
field focus-within now preserves the visible outer ring without relaxing the oracle.

An earlier phone capture attempt failed because Playwright fullPage capture resizes the
viewport and closes the native select popup. A controlled reproduction compared no
screenshot, viewport capture and fullPage capture. Dialog captures now use viewport-only
screenshots on phones; full-page screenshots remain for non-dialog scrolling pages.
The final matrix above passed; those draft captures are not included in the evidence commit.

Privacy: all six final media directories have hash-bound `ui-privacy.json` generated with
the lead's absolute `scripts/ui_evidence.py`, null-media fixture hashes, agent inspection
attestation, PNG decoding, audio exclusion and metadata checks: 2678 PNGs, 0 failures.
This is generated UI provenance, not real-camera polygon acceptance. `demo` privacy and
metadata scans passed (0 media files). Gitleaks is unavailable locally and was not claimed
as run; CI/lead retains its required secret scan. No data/, .env or raw media is staged.

MISSING integration: lead must wire actual API/session callbacks, shared real player and
tap-to-protect, API camera telemetry and real field benchmark. These are exclusively
lead-owned and are not simulated by this task. Independent reviewer approval is pending.
