# Motion builder evidence

Source: `4fa2342`. This is builder verification, pending independent review.

REAL: token-driven MotionProvider, page/panel entrances, accessible inline exits,
focus recovery and shared live reduced-motion preference. Eleven new unit tests
cover initial/live preferences, cleanup, active-tween interruption, focus,
mount/unmount, route churn and rapid panel reopen. The full frontend suite passed
73 tests; TypeScript/Vite production build passed. Whole-checkout Ruff check and
format check passed (219 Python files; check emitted a nonfatal cache-write warning).

FIXTURE: actual Shell/Home/Attention/Chat/HouseView components compose supplied
state.json and twin.json, with Inter. There is no API/camera/model call. Ask-home
and unavailable media stay disabled. Household sends change actual local React
state and are labelled local.

The motion matrix covers 1470x870, 1512x895, 1728x1030, 1920x960, 1536x730,
1280x600, 1366x650, 1024x768, 1180x820, 2560x1000 and 390x844 CSS pixels,
each dark/light and ordinary/reduced: 44 cases, 4,704 captured states, no failures,
console errors, failed requests or desktop document overflow. The two shard JSON
ledgers preserve their start/end times and individual measurements. Each case
works visible hover controls, supplied Home views, visit/disclosure, notifications,
full-screen/popup chat, draft sharing, actual local send, keyboard and scroll.

The separate scene ledger covers the same 44 cases: four presets, coverage, all
available camera selectors, zoom/reset and actual R3F orbit state. All passed.
The adaptive ledger proves canvas/input identity, settled camera/target values,
draft/focus and one shared native listener across preference/route changes. An
in-flight tween starts at 8px and reaches transform none within two frames of a
reduced preference; a QA-only longer token override makes that regression observable.

Manual visual inspection opened all 56 key-state contact sheets, additional full
hover sheets, and selected full-size phone, short-screen, dialog and chat states.
Contact sheets index the original PNGs without changing them. The inspected
compositions retain visible focus, verdict words, bounded dialogs and the clear
household/outsider gate comparison. Phone document scrolling is intentional.

There are 5,364 generated UI PNGs, including inspection sheets. The hash-bound
ui-privacy.json manifest records their metadata/privacy gate result. No raw camera
assets, audio, models, credentials or identifying property details were introduced.
The ordinary demo privacy/metadata scans passed with zero media files in this checkout.
Local gitleaks is unavailable; CI remains responsible for that check.

MISSING (integration scope): Root must install the provider/page wrappers in the
final app and replace Chat/Twin preference imports with useMotionPreference. Root
also owns Twin's pulse-period token correction and scroll padding clear of the
floating Messages pill. These precise requests and examples are in the motion
README and coordination log. No cross-owned source was changed here. Other wave
pages are intentionally outside this isolated preview. Hardware performance and
real-data acceptance remain unverified. Python/E2E full suites and pre-main timing
are lead-owned; this UI-only branch did not rerun unchanged Python tests.

Review URL: http://127.0.0.1:8107/next/src/motion/preview.html

No approval verdict is issued by the builder.
