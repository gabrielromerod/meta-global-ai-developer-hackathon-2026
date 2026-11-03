# Rules, Settings and Benchmark review

These pages consume `PageProps` and the lead-owned `ownerActions` / `ruleActions`.
No API, camera, model, token persistence or optimistic server mutation lives here.
Callbacks without implementations remain disabled. Token entry requires edge mode;
check-in, window mutation and rule confirmation additionally require `owner.enabled`.
Recorded windows remain immutable. Draft compilation is distinct from confirmation
and always displays the supplied server/cache notice. Phone voice callbacks never
request camera audio. Protected objects are a read-only catalogue with real visit links.

Settings sections use the existing [Radix Tabs](https://www.radix-ui.com/primitives/docs/components/tabs)
wrapper. Expected-window creation uses the existing Radix Dialog wrapper. Forms follow
the [shadcn Input](https://ui.shadcn.com/docs/components/input) pattern over native labelled
inputs/selects. The browser's [datetime-local picker](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/datetime-local)
is used instead of a custom calendar: it provides keyboard and platform date entry,
then the callback receives timezone-aware ISO values. New-time timezone is explicit;
recorded windows display their original offset rather than shifting recorded clocks.
Custom code is limited to Vigil's owner authorization and data/form presentation.

Benchmark ignores metrics unless `benchmark.measured` is true. Synthetic model-call
telemetry is never promoted to field accuracy, latency or cost measurements.

## Preview

From Windows CMD in `web-next`: `npm ci`, then `npm run dev -- --port 8106`.
Open `http://127.0.0.1:8106/next/src/pages/settings/preview.html`.
Use `?route=rules` or `?route=benchmark`, and `&theme=light` for the other theme.
Default is the authored sandbox fixture. `context=edge` and `context=edge-owner` are
explicit UI test states: callbacks only show a verification dialog and never pretend
to save to a server. `draft=1`, `notice=1`, `pending=1`, `error=1` exercise supplied props.
`context=empty` tests empty camera, rule, protected-object and window lists.
`review=1` is an explicit authored review-flag test state, not real-camera acceptance.
Only an explicit successful flag shows Reviewed; a blocked status overrides it.

Enabled form borders use the existing muted token to meet non-text contrast. A real
rendered check failed at 1.89:1 dark / 1.62:1 light before the correction, then passed
at 9.44:1 / 6.16:1. Disabled controls retain their disabled presentation.
Window creation closes only after a matching new, non-recorded window arrives through
props; firing a callback alone never simulates a save.

## Tests

`npm test -- src/pages/settings/settings.test.tsx` covers owner guards, exact callback
IDs/payloads, window validation, immutable recorded windows, expiry props, original
recorded offsets, absence of inferred telemetry, draft confirmation, voice callback
separation and honest benchmark states. `npm run build` validates all TypeScript.
The lead owns unchanged Python and final full-app suites. No test was loosened.

Initial full frontend run observed an existing Chat animation-timing failure at
`chat/index.test.tsx:80` (immediate visibility while Framer still had opacity zero).
It was reported to the lead without editing the Chat source or assertion. A later
unchanged full suite passed 79 tests; the lead retains the timing issue for integration.
