# Mechanical cutover review B

**FIXTURE - APPROVED.** Reviewed Root commit `060c583c0e11cd2cf8fdc0bfd8e6a16b18012f61`
in the isolated branch at `73cdef6f1540a4d5132dcb38d4dd78331c374bdd`.

The application factory serves the same dist at `/` and `/next/`, with unchanged
`/next/assets/` URLs. API/media mounts precede the root static mount. Docker copies the
standalone calibration utility to its new path. Its sandbox block remains in front of
the mount. The legacy consumer files and vendor script are removed. The calibration
JavaScript is unchanged and its HTML uses the new local stylesheet. No React UI source
changed relative to the fully approved `5cf05c57` tree.

Six focused route/build-input/calibration tests passed (one existing deprecation
warning). The actual restarted isolated port 8119 server was asserted sandbox,
cache-only, invalid-key and closed-loopback before serving. Actual `/` and `/next/`
return byte-identical HTML, all referenced built assets return 200, and legacy JS/CSS
and sandbox calibration paths return 404. Real browser checks of `/` and
`/#/visit/v_c` pass at 1470x870 and 390x844 with no page/network errors.

The two actual root screenshots were opened and inspected. The unchanged screenshot
provenance/decode/metadata gate passed both, bound to the observed null-media API state
in `qa/screens/060c583c/final-b-cutover.json`. No model, camera or microphone operation
was performed. Evidence is fixture-based browser acceptance, not hardware acceptance.

Applying the integrator's commit encountered README/decisions conflicts from intervening
Root documentation. Those two files were taken exactly from `060c583c`; no independent
source repair was made. Runtime/removal/container/test paths match the reviewed commit.

APPROVED
