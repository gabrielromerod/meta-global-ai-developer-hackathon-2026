# Twin ROUND1 corrections — builder verification

Evidence: **FIXTURE**. Source `9682b68`, preview on isolated port 8102. No live
camera, Meta API, paid call or backend write. Independent ROUND1 report is commit
`fac7640`; this document does not claim independent approval.

The pre-fix actual-frame regression failed 15 of 18 desktop/phone cases, including
the review's pan/diagnostic mismatch and Top-down clipping. The new unit regression
failed because the desired Top-down polar angle was 0.019045 radians while the real
controls require at least 0.08. No prior test or diagnostic assertion was loosened.

The fix constrains the final state after drei's frame-priority -1 controls update,
consumes residual outward pan at a boundary, and does not call controls.update after
the final clamp. The renderer and diagnostics use the same actual pose. Presets
are constrained before fitting and animate in spherical coordinates, with each
intermediate legal orientation fitted to the supplied generic property bounds.

Validation began 2026-11-03T03:53:54-08:00; final matrix results were checked at
2026-11-03T03:57:40-08:00. `npm test` passed 21 tests; `npm run build` passed.
The ordinary UI browser matrix also passed all eleven viewports, both themes.

| Actual after-render validation | Cases | Sampled frames | Worst absolute NDC | Violations |
| --- | ---: | ---: | ---: | ---: |
| All eleven viewports, both themes, motion | 99 | 7748 | 0.928700 | 0 |
| All eleven viewports, both themes, reduced motion before load | 99 | 7717 | 0.925341 | 0 |

The samplers read the real R3F camera and OrbitControls after every rendered frame.
They check pan, ground clearance, distance, diagnostic consistency and full frustum
containment during preset settling. They collect at least two rendered samples in
every case. The original reviewer's framing and stress probes were copied into the
owned task directory and replayed against this builder's own server. Their logic
was retained; only source URL/output paths and the builder-replay attribution were
adapted. A separate assertion verified that no panOvershoot record remained.

All 52 focused full-resolution frames were opened and inspected through the four
inspection sheets; the dark/light phone Top-down originals and actual desktop pan
original were also inspected at full resolution. The 198-case matrices retain
their complete numeric results here. Other repeated capture frames remain local;
the focused images cover the reported failures and their reduced-motion variants.

This verifies generated geometry and recorded/generated evidence only. Physical
camera calibration, physical device GPU performance and main-branch integration
remain outside this builder verification.
