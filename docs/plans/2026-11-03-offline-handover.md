# Offline handover implementation and progress

User's November 3 numbered request is the execution specification, alongside
`docs/spec/vigil-spec.md` and `CLAUDE.md`. Execute in the existing checkout so the human's
QA server reloads each small change. No Meta calls, cameras, paid settings, or real media.
No requirement becomes Verified from generated media or fakes.

For each numbered task: check QA_NOTES.md, add and observe the failing regression tests,
implement, run ruff check/format-check and the default pytest suite, run relevant browser
tests, then commit and report SHA plus REAL / FIXTURE / STUB evidence. Commit IDs below
are the durable progress record. Existing recorded-input contracts remain supported.

| Task | Implementation boundary and acceptance | Progress |
| --- | --- | --- |
| 0 | Sandbox reload server, invalid key, cache only, QA_NOTES.md, CMD commands | HTTP 200; server started |
| 1 | .gitignore, local three runtime, WebGL-required judge-path E2E | Complete: 94f6786; 1419 default tests and WebGL E2E passed |
| 2 | sam/spark upload guards; CameraCfg explicit none_needed; ingest preflight | Complete: 4dab0a6; 1425 default tests passed |
| 3 | pipeline/process cloud orchestration, split cutter, tagged media, SQLite, estimate/confirm; respx generated MP4 integration | Complete: 5abbbc7; 1428 default tests passed |
| 4 | export clips/overlay/twin and actual video playback E2E | Complete: a55aed9; 1430 default and 19 browser tests passed |
| 5 | time-ordered session watch feedback; next-window phrase regression | Complete: 377363c; 1431 default tests passed |
| 6 | main owner UI, session token, checkin countdown, Expected Windows CRUD, sandbox example; undo | Complete: 645ea2b; 1434 default and 21 browser tests passed; fake Undo removed |
| 7 | MetaClient timeout billing classification and 20 s read deadline | Complete: 59b48b1; 1442 default tests passed |
| 8 | smoke script upload/schema/voice contract tests; never run live | Complete: 52942d0; 1445 default tests passed; no live smoke run |
| 9 | Wi-Fi source profile, stream/filter, probe telemetry and battery refusal; pinned reolink-aio and fake tests | Complete: 3a87d55; 1452 default tests passed |
| 10 | removal absence/containment/cross-window state; three regressions | Complete: 83a677c; 1455 default tests passed |
| 11 | Only after 1–10: GLB locate/coverage, world_frame, export, errors/limit, generated GLB tests | Complete: 4b03858; 1461 default and 24 browser tests passed |
| doctor | CLI offline READY/MISSING key/window/ledger/privacy/dependency/hosts/ffmpeg | Complete offline; test_doctor.py; final suite 1471 default + 24 browser tests passed |

Final independent review findings were fixed in `078c740`: omitted upload context,
temporal watch eligibility, lawful same-session check-in replay, and calibrated twin
poses/coverage export. New regressions were observed failing before their fixes.

Review focus: omitted privacy must fail before any upload; split/tag transforms must retain
black polygons; fixture data must never be called a live recording; new watches must not
affect earlier windows; missing camera secrets must not trigger network or leak values.
