# Property view

`HouseView` is the React Three Fiber implementation of FR-040. It accepts the
lead-owned `HouseViewProps` contract, with an exported generic twin, positions,
shared session time, active camera and camera-selection callback. Camera coverage
is nominal; it is never displayed as measured coverage. A camera source label is
shown exactly as supplied.

The view renders the configured public boxes and ground, seven-camera fixture
inventory, nominal coverage clipped at walls and the tree barrier, hatched blind
polygons, observed paths, uncertainty rings and code-authored gap labels. It does
not render a private `glb_url`; identifying geometry must stay on the home box.
No point is interpolated inside a gap. Gap endpoints accept the existing API's
`[x,z,t]` format without treating the timestamp as a coordinate.

Pass event rows as `positions.events` for event-driven cone pulses. The preview
combines the lead-authored positions and visit fixtures; the component embeds no
visit data. Clicking a camera marker, a coverage spot, a camera row or the compact
camera menu calls the same `onCameraSelect` callback. A missing callback disables
the corresponding DOM actions.

## Library choices

[R3F Canvas](https://r3f.docs.pmnd.rs/api/canvas) owns renderer lifecycle and resize.
[drei OrbitControls](https://drei.docs.pmnd.rs/controls/introduction) supplies
damping, orbit, pan and zoom. drei Line draws evidence and hatching; Three vector
math fits every preset to the supplied generic property bounds. Radix Tabs,
DropdownMenu and Tooltip provide keyboard controls, the compact camera chooser
and blind-region descriptions. Lucide provides the icons. Motion's reduced-motion
hook disables animated presets, damping and cone pulses when requested.

Custom code is limited to Vigil geometry/evidence rules and projected label
layout. drei Html was tried first; its nested `createRoot().unmount()` emits a
React 19 console error during renderer commits. This was reproduced with a
console-failing browser test. One normal React DOM overlay, projected through
R3F, avoids nested roots. Collision placement moves annotations only, with leader
lines to their unchanged world anchors. Labels with insufficient room are
decluttered; the camera menu or camera row remains available.

The component fills its parent, including a flex parent. Below 420 CSS pixels in
height, container queries put presets and camera selection on one row, replace
the duplicate camera row with a Radix menu and omit the redundant legend. A
266-pixel panel retains over 175 pixels of actual canvas with a gap summary.
CSS requires literal media/container query thresholds; presentation properties
and overlay offsets otherwise use the frozen tokens.

## Verification

Evidence is **FIXTURE**, using authored inputs and headless Chromium on Windows.
It is not real-camera acceptance, physical Mac hardware testing or a measured
phone-GPU performance result. No cameras, Meta API or paid calls are used.

From `web-next/`:

```cmd
npm ci
npm test
npm run build
npm run dev -- --port 8102
```

Preview: `http://127.0.0.1:8102/next/src/twin/preview.html`.
In another CMD window: `node src/twin/browser-qa.mjs`.
Reviewers may set `TWIN_QA_URL` to their isolated Vite port and `QA_SHA` to the
immutable revision they are reviewing.

The 20 Vitest checks include seven-camera preservation, empty configuration,
above-ground orbit, zoom/pan bounds, each preset, full phone-frustum containment,
opaque-wall cone clipping, polygon hatching, label collisions, shared clock,
gap noninterpolation and real event pulses. They were written and observed
failing before implementation. The browser script checks all eleven requested
numeric CSS viewport sizes in both themes, desktop document bounds, actual
annotation rectangles, every visible hover control on desktop/phone, all presets,
camera actions, compact menu, keyboard focus, camera-row scrolling, reduced
motion, drag-down, pan, zoom, gap/observed time and StrictMode remounts.

Production source `4a1120e` has 109 captured state screenshots in
`qa/screens/4a1120e/`, with `twin-results.json`. Inspection sheets provide a
complete visual index; original full-resolution frames remain alongside them.
The full offline Python suite passed: 1,474 tests, 24 E2E tests deselected, one
existing Starlette deprecation warning, 202.31 seconds. Ruff check and format
check passed. The lead reruns full suites with exact timestamps before main merge.

The screenshot privacy scan uses `--allow-unmapped` because these are generated
application screenshots, not camera frames; no camera privacy polygon can map to
them. Manual inspection checks that they contain only the generic scene and
authored fixture text. ExifTool checks GPS/device metadata. Local gitleaks was not
installed; no claim is made that it ran here.
