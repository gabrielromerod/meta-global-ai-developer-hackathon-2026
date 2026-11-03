# Motion round-two builder evidence

REAL fix: `47dddac6` removes the unconditional initial-only library preference hook.
The exported native bridge now owns its sole subscription and uses a conservative
reduced snapshot when matchMedia is unavailable. It follows React's hook rules
without conditional hooks. No animation, geometry, route, chat or theme source changed.
`f61680ed` and `ebc421a9` only make the focused QA harness wait for an actual WebGL
draw and mounted scene annotations before capturing geometry. Final screenshots and
focused ledgers identify `ebc421a9`; production code is unchanged after `47dddac6`.

The new isolated unit test failed before implementation with listener lifecycle
0→2→1 across both `(prefers-reduced-motion)` and `(prefers-reduced-motion: reduce)`.
Its browser counterpart reproduced the same lifecycle without Chat/Twin imports;
the original failing JSON is retained as motion-isolated-listener-before-fix.json.
The unsupported-native unit test also failed before the fix because the library's
stale false value overrode the conservative fallback. Both now pass. Neither test
was weakened. Modern and legacy listener APIs are counted.

FIXTURE browser evidence: motion-isolated-listener-results.json now proves 0→1→0,
live reduce/ordinary preference updates, shared listeners for multiple consumers,
the same input node, retained draft and retained focus, with zero console errors or
failed requests. This probes the exported hook alone in the blank scaffold; the
context screenshot is diagnostic test UI, not a product design screenshot.

The focused affected-state matrix covers all eleven requested CSS viewports and
both themes. Each case changes ordinary→reduced→ordinary, checks zero reduced
durations/offsets/transform, restores ordinary durations, keeps the canvas identity
and one page tree, and checks document overflow. It has 22 themed cases/66 captures.
All cases passed with zero console errors, failed requests or desktop overflow.
The unchanged adaptive browser regression separately verifies the same actual R3F
camera pose and canvas, focused draft/input, 20 route changes without accumulated
bridge listeners, and an active 8px tween becoming transform none within two frames.

Frontend suite on f61680ed: 75 tests passed (13 motion tests), TypeScript/Vite build passed,
whole-checkout Ruff check and format check passed. No unchanged Python suite was
rerun; root owns final Python/E2E and pre-main validation. The round-one full visual
and scene matrices remain in qa/screens/4fa2342; this listener-only correction uses
focused evidence rather than repeating unchanged 5,000-state captures.

MISSING (root integration): Chat/Twin still own their existing library-hook imports
and their in-flight animation behavior. This correction makes no claim that their
process-global library subscriptions disappear. Root coordinates those source
changes and full-app review. No cross-owned source was edited.

All seven contact sheets were opened and inspected, including the isolated-hook
context, short screens, phone and ultrawide states. The root UI privacy/provenance
gate passed all 82 PNGs with zero failures. These are generated UI pixels with no
camera footage or external media. No screenshots or assertions were removed.

Builder verification only, pending independent round-two review.
