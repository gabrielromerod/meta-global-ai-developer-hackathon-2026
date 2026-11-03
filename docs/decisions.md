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
