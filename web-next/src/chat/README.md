# Messages surfaces

`ChatPopup` and `MessagesPage` use one thread workspace and one message renderer.
Both accept the frozen `ChatProps`. Keep `threads`, `selectedThreadId`, `drafts`
and `onDraftChange` in the lead-owned shared state when switching layouts.

The popup is a non-modal Radix Dialog: other pages stay usable, Escape closes it,
and focus returns to the control that opened it. Radix Tabs handle thread selection,
DropdownMenu handles evidence actions, and Tooltip explains unavailable controls.
The relevant library-first checks were the official [Dialog](https://www.radix-ui.com/primitives/docs/components/dialog),
[Tabs](https://www.radix-ui.com/primitives/docs/components/tabs) and
[Dropdown Menu](https://www.radix-ui.com/primitives/docs/components/dropdown-menu) documentation.
All presentation values use the frozen tokens; CSS media queries repeat the
640 px phone threshold and 730 px short-window threshold because native CSS custom
properties cannot be substituted into media-query conditions.

`onSend` may return a promise at runtime. Failed sends keep the draft; in-flight
sends block duplicate submissions. The assistant capability and local household
capability gate sending and clip sharing. Snapshot/record controls need both a
capability and a callback. Citations and shared clips call the lead-owned player
and visit handlers. This module creates no incoming messages and makes no network
requests. People-to-people messaging has no backend and is visibly local.

## Standalone QA

Run `npm ci` and `npm run dev -- --port 8104` in `web-next/`, then open
`http://127.0.0.1:8104/next/src/chat/preview.html`.
The preview starts with the empty authored fixture threads. Ask-home is explicitly
disconnected there. Household sends only the text actually typed in that browser;
the preview clip picker reads existing authored evidence and appends a local share.
The integrated app supplies the actual backend callbacks and shared state.

Validation commands:

```text
npm test
npm run build
node src/chat/qa-layout.mjs
node src/chat/qa-contrast.mjs
node src/chat/qa.mjs
node src/chat/qa-final.mjs
```

REAL: 14 component behavior tests exercise send normalization, pending states,
keyboard thread selection, multiline composition, missing capabilities, errors,
citations, Escape/focus restoration, cross-layout drafts, rejected sends, clip
navigation, empty threads and unavailable sharing. The short-window browser
regression failed with text bottom 440.19 beyond history bottom 408; after the
spacing fix the text bottom is 376.19.

FIXTURE: `qa/screens/9cc0857/` contains the final 132 screenshots, six states for
each of 11 numeric CSS viewports in both themes. All were opened and inspected in
contact sheets, with phone and short-window views also inspected at full size.
The full interaction run captured 638 states on `cc76686`, including every control,
hover/focus, menus, clip-picker scrolling, message scrolling and popup dismissal.
Its report is preserved alongside the final report; duplicate intermediate images
are not committed. The later token substitution retained the same visual values;
the sharing capability correction is covered by the fourteenth test.

Both browser runs reported no console errors, failed requests, document overflow,
or off-screen controls. The 44 rendered text contrast checks passed AA with a
minimum ratio of 5.73:1. Reduced-motion and ordinary-motion popup runtimes were
checked. Numeric viewport tests do not claim physical Mac/Windows scaling hardware
acceptance. Parent shell integration still needs its own final app-wide review.

The final screenshots are generated UI, without camera pixels, identifiers, audio
or metadata. The privacy scanner checked 132 frames using `--allow-unmapped`
(appropriate for UI screenshots, checking media validity/audio without camera masks),
and the lead's fail-closed metadata scanner passed. `demo/` scans also passed but
contained zero media in this checkout. Gitleaks is not installed locally; CI owns
that check. No camera or Meta API was contacted.
