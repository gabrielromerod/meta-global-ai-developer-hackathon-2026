# Independent controls review, round 2

Reviewer `/root/r2_controls`, 2026-11-03. Reviewed frontend source snapshot
`5f6f88934f907780d5559b6d60c40c5e13540e0f`, composed from the exact builder scope
repair and its proof. Final preparation HEAD `ed4fe857f540742269d54ed67ea52c086cbbf932`
changes only documentation encoding; the frontend source snapshot is unchanged.
Reviewer production edits: none. Own preview remained on port 8116.

No remaining findings. Round 1's P2 expected-window zone-scope finding is resolved.

1. **Scope display — healthy.** Zone-only rows show `Zones: Side alley`; camera-only
   rows show `Cameras: Doorbell`; combined rows show both; only rows with both arrays
   empty show `All configured cameras`. Fresh independent prop probes exercised all
   four combinations at 1280×600 and 390×844 in both themes. These row variants also
   appeared throughout the eleven-viewport affected-list sweep. The original recorded
   deliveries row still shows its original timestamp offset and remains immutable.
2. **Wrapping and scrolling — healthy.** Long multi-zone and combined scopes, long
   window labels, multiple IDs, and an unbroken identifier wrap within each row.
   All eleven exact CSS viewports were checked in light/dark with actual innerWidth/
   innerHeight: 1470×870, 1512×895, 1728×1030, 1920×960, 1536×730, 1280×600,
   1366×650, 1024×768, 1180×820, 2560×1000 and 390×844. No horizontal overflow,
   overlap or content clipping was found. Desktop retains internal scrolling and
   stable gutters with no document scroll; phone scrolls vertically to the last row.
   Each affected row was brought into view and its Cancel control hovered. Fresh
   top/bottom and row captures are in `qa/screens/5f6f8893/<viewport>/`.
3. **Guards and validation — healthy.** All four mutable scope combinations pass their
   actual IDs to the cancellation callback. Pending/revoked-owner states disable them;
   recorded rows remain disabled. The independent regression prop harness additionally
   rechecked missing callbacks, token clearing and storage/URL exclusion, countdown,
   valid/empty and exact-12-hour timezone payloads, unrelated/recorded versus matching
   server-owned acknowledgements, pending/error props, privacy flags, rule callback IDs,
   owner confirmation, separate phone voice callbacks and benchmark measurement guards.

Fresh affected-list sweep: **22 cases, 936 assertions passed**, zero console/request
errors. Independent regression harness: **100 assertions passed**, including the
previously failing zone-scope assertion in all four viewport/theme combinations.
All 13 labelled contact sheets were opened and inspected; desktop combined scope and
phone zone/camera/unrestricted/long multi-zone rows were also inspected at full size.
Total evidence: **242 original PNGs + 13 inspection sheets = 255 PNGs**. The unchanged
whole-app matrix was not replayed, as directed; round 1 retains that broader evidence.

Validation: full `npm test` **85 passed**; `npm run build` passed. `uv run ruff check .`
and `uv run ruff format --check .` passed on final preparation HEAD (249 files formatted).
The first format check on `5f6f8893` failed because prepared `docs/coordination.md` was
not UTF-8 (decode error at byte 804, 0xD7). This was reported without a reviewer source
edit. The lead normalized that documentation in `ed4fe857`; both Ruff checks were then
rerun and passed. No unchanged Python full suite was rerun, per assignment.

The current lead-owned immutable-fixture provenance gate passed: **255 named PNGs,
zero failures**. Manifest and committed snapshot fixtures are under
`qa/screens/5f6f8893/ui-privacy.json` and `proof-fixtures/`. These are authored null-media
UI probes, not real-camera acceptance. No Meta, camera, microphone, spend or real owner
mutation occurred. Source fixtures, production code and original Python line-ending
changes were untouched by the reviewer.

APPROVED
