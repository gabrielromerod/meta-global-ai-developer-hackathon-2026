# Implementation decisions

- 2026-11-03: Replace the previous Preact direction with React/TypeScript/Vite per owner instruction; reuse only contracts, authored fixtures and tokens.
- 2026-11-03: Keep the existing linked checkout for lead integration and isolate each builder/reviewer in managed worktrees, preserving existing line-ending edits.
- 2026-11-03: Use the owner's numeric viewport dimensions as reproducible CSS viewport targets; physical browser chrome and OS scaling are recorded as approximations, not claimed hardware validation.
- 2026-11-03: The UI remains fixture-labelled until field acceptance; unknown prefilter counts remain null.
