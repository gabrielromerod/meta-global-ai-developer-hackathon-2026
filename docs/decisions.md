# Implementation decisions

- 2026-11-03: Replace the previous Preact direction with React/TypeScript/Vite per owner instruction; reuse only contracts, authored fixtures and tokens.
- 2026-11-03: Keep the existing linked checkout for lead integration and isolate each builder/reviewer in managed worktrees, preserving existing line-ending edits.
- 2026-11-03: Use the owner's numeric viewport dimensions as reproducible CSS viewport targets; physical browser chrome and OS scaling are recorded as approximations, not claimed hardware validation.
- 2026-11-03: The UI remains fixture-labelled until field acceptance; unknown prefilter counts remain null.

- 2026-11-03: Use drei OrbitControls, Line and Html; custom R3F scene composition expresses the input site plan and cited paths because component libraries do not supply Vigil geometry.
- 2026-11-03: CSS media queries use 640px and 1180px literals matching the named breakpoint tokens because native media queries cannot consume CSS variables.
