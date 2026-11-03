# Implementation decisions

- 2026-11-03: Replace the previous Preact direction with React/TypeScript/Vite per owner instruction; reuse only contracts, authored fixtures and tokens.
- 2026-11-03: Keep the existing linked checkout for lead integration and isolate each builder/reviewer in managed worktrees, preserving existing line-ending edits.
- 2026-11-03: Use the owner's numeric viewport dimensions as reproducible CSS viewport targets; physical browser chrome and OS scaling are recorded as approximations, not claimed hardware validation.
- 2026-11-03: The UI remains fixture-labelled until field acceptance; unknown prefilter counts remain null.

- 2026-11-03: Use drei OrbitControls, Line and Html; custom R3F scene composition expresses the input site plan and cited paths because component libraries do not supply Vigil geometry.
- 2026-11-03: CSS media queries use 640px and 1180px literals matching the named breakpoint tokens because native media queries cannot consume CSS variables.

- 2026-11-03: ExifTool 13.59 was already installed. Metadata scanning now fails closed; GLB public massing uses a validated JSON-chunk scan with textures/external resources refused because ExifTool does not parse GLB.

- 2026-11-03: Owner confirmed no Home Hub. The three battery cameras use imported clips; no persistent battery stream is allowed.
- 2026-11-03: Original four-camera synthetic scenarios keep their explicit fixture config; production config contains exactly seven real cameras, unreviewed masks and unmeasured transit.
- 2026-11-03: All privacy regions are unioned independently; OpenCV's combined contour fill cut holes where watermark/sky polygons overlapped.
- 2026-11-03: Public massing uses no textures or identifying geometry; actual Duo geometry requires per-half ground homographies and declared uncertainty, never a guessed full-panorama pinhole.
- 2026-11-03: Replace only drei Html's projected label bridge with a normal React overlay because React19 browser tests reproduced nested-root synchronous-unmount console errors; keep R3F and drei orbit/line primitives.
- 2026-11-03: Event capture retains separate observed media parts across missing intervals; a partial Wi-Fi clip remains evidence and missing time is explicitly unresolved.

- 2026-11-03: Owner selected Inter after reviewing the Inter, Manrope and DM Sans Home screenshots. Inter remains the final default.

- 2026-11-03: The installed Motion hook captures the initial media preference without a subscription; a thin useSyncExternalStore/matchMedia bridge is justified for dynamic OS preference changes, with MotionConfig and Motion primitives retained.
- 2026-11-03: The default backyard policy expands into the two unique configured lawn-zone IDs; rules still solely determine attention and legacy synthetic fixtures retain their original geometry contract.
- 2026-11-03: The Duo nominal half-FOV is 90 degrees, half the manufacturer's published180-degree panorama; section homography and measured uncertainty remain required, and this nominal projection is not field verification. Source: https://business.reolink.com/us/product/reolink-duo-floodlight-wifi/ .
- 2026-11-03: A doorbell visitor push is retained as its own camera_ai event; it never invents a person track, role or position. Measured event counts retain classified sensor IDs and stay null when observation gaps prevent complete classification.

- 2026-11-03: Use React Router HashRouter for addressable pages/visits and browser history on both FastAPI static mounts; it avoids reinventing navigation or requiring catch-all server routes. Official API: https://reactrouter.com/api/declarative-routers/HashRouter .

- 2026-11-03: CI/container use Node24.15.0 because installed jsdom30 requires at least that Node24 patch. The existing host Node24.14.0 was left unchanged; local tests passed there, and container tests provide supported-runtime evidence.

- 2026-11-03: Gitleaks ignores only complete PNG SHA-256 JSON entries in tracked QA privacy manifests (generic-api-key, path AND line match); token-named screenshots caused 22 false positives. The provenance gate independently recomputes these hashes. Scope probe still detects a credential field in the same manifest and the same digest-shaped token outside it.

- 2026-11-03: Production React uses HashRouter for static FastAPI deep links and TanStack Query for server state. Page components keep the complete session snapshot; server search verifies intersections without replacing that snapshot, so Clear can recover every record.
- 2026-11-03: Messages shares one thread renderer and lead-controlled drafts between popup/fullscreen. Household notes/cards use localStorage scoped to the exported session and are never posted. Ask-home uses the cached cited ledger endpoint only.
- 2026-11-03: Playback uses native HTML video controls and a shared session clock. No synthetic camera canvas stands in for missing video. SAM overlays select actual observed samples within 0.25 seconds and do not interpolate sparse detections or gaps; Vigil timing/geometry code is domain-specific and has no suitable UI-library replacement.
- 2026-11-03: Snapshot captures a decoded frame from an already exported video into an in-memory PNG. Native canvas drops source metadata; no stream is opened or upload made. Recording stays disabled because the contract has no recording capability.
- 2026-11-03: Reuse the existing Web Audio/PCM16 phone-speech path in TypeScript rather than add another recorder implementation. It emits exactly the server-required 16 kHz mono WAV, caps at 30 seconds and keeps speech only in RAM. Transcription and rule drafting explicitly request cached mode; no live-model control is exposed during this authorized offline rebuild.
- 2026-11-03: Radix owns dialog/menu/tab/focus lifecycles, Motion owns animation scheduling, and the independently reviewed native preference bridge supplies current OS state. Chat stops active entrances; R3F uses the shared preference and tokenized event pulse period.
- 2026-11-03: Full Attention includes every supplied visit, with urgent IDs first and normal history available through its real filter. Home alone limits its preview. Server urgent IDs are not truncated.

- 2026-11-03: Day/Night tabs change only tokenized schematic illumination. A visible note says recorded clips keep their original lighting; the app does not infer sunrise, weather or relabel recorded events. Camera/view selection retains the same scene and orbit.

- 2026-11-03: Preserve a native SVG map when WebGL is unavailable or `?twin=2d` is requested. It reuses the existing generic geometry, occlusion, observed-path and gap selectors; domain SVG drawing has no suitable component-library substitute. The schematic faces its front downward and keeps the tree barrier on the right, without compass orientation or private geometry.

- 2026-11-03: Export an actual masked PNG from each camera's first observed window for point selection. The same PNG is loaded by MetaLiveBackend, and the owner-only frame catalogue rechecks privacy and metadata before offering it. No synthetic canvas is substituted for a frame.
- 2026-11-03: Native image pointer coordinates plus native number fields cover point selection; Radix Dialog and existing shadcn inputs own interaction/focus. These coordinates are Vigil domain data, not a replacement for a library component. Recorded examples are not drawn over an unbound current frame. A future owner point-model action has a separate cost-confirmation dialog and service-defined availability; all tests inject a fake backend, never Meta.

- 2026-11-03: Native video Play/Pause controls own the same transport state as the shared timeline; video time is the playback clock when media exists, while metadata-only timelines use an explicit evidence clock. Seeking and transport effects are separate so a clock tick cannot restart a user-paused video. The original 0.2-second multicamera drift bound is retained on two genuine generated MP4s.
- 2026-11-03: Preserve the ISO offset declared in session_start for player clocks, matching server citation formatting; show the recorded date and offset. Viewer timezone never silently relabels recorded evidence. Intl handles formatting without another date library.
- 2026-11-03: External area selection is a preset request, not a permanent override of manual R3F controls. At constrained widths, the existing Radix camera menu also exposes view controls, retaining scene height and keyboard access.
- 2026-11-03: Share one unit-aware time-token parser between Motion and R3F because production CSS minification normalizes milliseconds to seconds. Palette timing refreshes on the shared reduced-motion preference without resetting orbit state.

- 2026-11-03: CI hands the exact frontend build artifact to backend/API tests; compiled files remain uncommitted. The model-ID guard scans TypeScript and fails on scanner errors. POSIX shell wrappers must have LF bytes in working copies as well as Git; the Linux verifier snapshots committed blobs to match CI checkout rather than copying Windows line endings.

- 2026-11-03: At the reviewed cutover, remove the legacy consumer bundle and retain its standalone LAN calibration worksheet as a maintenance utility outside web-next. This preserves the existing owner-coordinate API workflow without serving the old consumer UI; sandbox access remains404. The utility is not claimed field-accepted.

- 2026-11-03: Import-only battery cameras do not require network hosts in doctor. AC/Hub access still requires its configured host, and privacy/clock reviews remain independent blockers. This matches the owner-confirmed no-Hub workflow without encouraging a battery connection.
