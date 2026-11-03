# Readiness checklist

**Nov 3 offline handover:** the requested cloud path, media export/player, owner UI,
Wi-Fi profile, removal handling, GLB import and `vigil doctor` are implemented with
FIXTURE evidence. See [the handover runbook](runbooks/offline-handover.md) and
[commit/progress ledger](plans/2026-11-03-offline-handover.md). No live Meta call or camera
connection was made, and nothing was upgraded to real-data Verified. The doctor currently
flags owner inputs/configuration, including missing backyard privacy. ExifTool 13.59 is
now installed (owner approved): `EXIFTOOL=... bash scripts/metadata_scan.sh demo` reports
PASS, no GPS/device metadata. The current demo contains zero media files; this is not
real-footage acceptance. Gitleaks is absent locally; CI still supplies that check.

## Consumer round in progress (Nov 3)

These are MISSING until implemented and evidenced in the consumer-round plan:

- Normalized UI state/search/chat API and shared hooks, new app entrypoint and sync:
  lead-only Phase 2 after isolated visual workers land. Frozen fixtures are authored
  synthetic data, not recordings of real Meta responses or real camera behaviour.
- Seven-camera power/Hub inventory, battery import and on-demand Hub capture, AI event
  clip closure/ring pinning/free-space retention: supersede the earlier four-camera
  session-only profile. No IPs/Hub supplied; tests must use fakes/generated media.
- Strict audio rejection at ingest, per-Duo privacy-region checklist/overlay removal,
  outer-ring counting, battery-wake gaps, full-frame 1920 Duo perception and split-half
  geometry uncertainty: requested now, pending backend items 2–4 and 10.
- New shell/pages/chat/twin visual requirements and desktop no-scroll evidence:
  pending visual workers and final browser integration.
- Real field privacy polygons, real SDK telemetry/time-sync and Hub discovery, actual
  Meta responses/credits/key and footage remain owner-dependent. No live calls allowed.

**Date: 2026-11-02** (Mon Nov 2, after the Nov 2 spec revision). Spec: [section 13](spec/vigil-spec.md#13-final-readiness). Vigil is ready to submit when every row of the [traceability matrix](requirements/functional.md#traceability-matrix-spec-131) has a green test and the demo evidence it names, on real data.

Everything below is evidenced by a command run on this date, or by a file in the repo. **Nothing has been verified on real data yet**: no footage, scan, calibration, voice fixture or billed Meta API call exists.

## Requirement status

| Set | Total | Offline-verified | Partial (offline) | Blocked | Not verified | Verified |
| --- | --- | --- | --- | --- | --- | --- |
| Functional ([checklist](requirements/functional.md)) | 44 | 36 | 7 | 1 | 0 | 0 |
| Non-functional ([checklist](requirements/non-functional.md)) | 37 | 18 | 8 | 9 | 2 | 0 |

Every change in the [Nov 2 change set](spec/changes/2026-11-02-business-corrections.md) now has passing offline tests: spatial-origin roles (FR-044), origin tagging (FR-008), subject chains and the group rule (FR-010), `applies_to` and the r7 window at 17:30–06:00 (FR-012), the case-2 triage exemption (FR-013), role phrasings (FR-021), voice rules with 3 sample-audio buttons (FR-022), 5 scenarios (FR-027), expected windows and check-in (FR-029), nominal-FOV intrinsics and lens profiles (FR-036), landmark proposals and the audit harness (FR-037, NFR-024), validator check 7, the $25 judging cap with `VIGIL_JUDGING_END` and the `credit`/`paid` tag (FR-043, NFR-036, NFR-037), and the repository-wide audio allowlist (NFR-002).

## Evidence

| Item | Evidence |
| --- | --- |
| CI | [Run 41587853241](https://github.com/gabrielromerod/meta-global-ai-developer-hackathon-2026/actions/runs/41587853241): every job green on commit `46c5b68` ("fix(scan): limit metadata scan to media and scan exports"): ruff and the NFR-004 grep, gitleaks, the blocking P0 suites 1–4, the report-only suite and determinism run, the privacy, metadata and repository-wide audio scans, and the Docker sandbox with the blocking judge-path E2E. Latest: [run 41604381135](https://github.com/gabrielromerod/meta-global-ai-developer-hackathon-2026/actions/runs/41604381135) (every job and every step green, report-only steps included, on `6dee3bf`; 1418 passed locally, 18 E2E) |
| Fix round (Nov 3) | `uv run pytest -q` after the defect fixes (durable ledger, reservations, owner token, trusted hosts, check 7 cues, removed events, NFR-003 schema test): **1394 passed, 18 deselected**, 0 failed, in 139 s |
| Unit and integration suite | `uv run pytest -q` on the working tree: **1275 passed, 18 deselected** (e2e), 0 failed, in 105 s. 1043 unit tests in 31 files under `tests/unit/`, 232 integration tests in 8 files under `tests/integration/` (counts include parametrised cases) |
| Browser E2E | `uv run pytest -m e2e tests/e2e -q`: **18 passed** in 13.7 s (Chromium), invalid key and unreachable live backend. One `PytestRemovedIn10Warning` about the session-scoped `base_url` fixture |
| Lint | `uv run ruff check .`: all checks passed; `uv run ruff format --check .`: 168 files already formatted |
| Phase 0 audit | [audit/2026-11-02-repo-audit.md](audit/2026-11-02-repo-audit.md) |
| Foundation and CI | Commit `3d53d05`; [.github/workflows/ci.yml](../.github/workflows/ci.yml) runs the blocking and report-only lanes of [spec 12.2](spec/vigil-spec.md#122-ci-pipeline-githubworkflowsciyml) |
| Offline core | All modules in [spec 9.1](spec/vigil-spec.md#91-repository-structure) exist under `vigil/`, plus `vigil/api/owner.py` (windows, check-in, feedback), `vigil/api/voice.py`, `vigil/spatial/landmarks.py`, `web/voice.js`, `web/calibrate/`, `web/twin/`, `config/role_phrases.json`, `config/role_banned_words.json`, `config/audio_fixtures.json` (empty list) and `demo/synthetic/` (5 scenarios A, A′, B, B′, C; the bundle regenerates byte-identical) |
| CLI | `uv run vigil --help` lists `version ingest process eval export serve spatial reolink cost demo`; commands that need field data or credits exit with a "blocked:" reason (`tests/unit/test_cli.py`) |
| H-01 GPU probe | [eval/hardware/3090.json](../eval/hardware/3090.json): RTX 3090 Ready, probed 2026-11-02T20:50:57Z (torch 2.14.1 built for CUDA 13.0, driver 617.42 reporting CUDA 13.4; 63.9 TFLOPS burn, 67 °C peak, about 48 W idle and 349 W under load, GPU board power). `torch` is **not** installed in the project environment (`uv run python -c "import torch"` fails) |
| GitHub backlog | Issues [#1–#80](https://github.com/gabrielromerod/meta-global-ai-developer-hackathon-2026/issues) created by `scripts/backlog/backlog.py`; T-02 (#46) and H-01 (#76) are closed; see [backlog.md](backlog.md) |
| Pre-registered artefacts | [EVAL.md](../EVAL.md) targets, including the role miss rate and the 11.9 Tier 0 / Tier 1 measurement registered on 2026-11-02; [eval/labels/README.md](../eval/labels/README.md) and `_template.json` (no scenario labels yet); [eval/budget.md](../eval/budget.md) |

## Remaining gaps (no credits or hardware needed to start)

- **FR-035 3D build.** `vigil/spatial/scan.py` `build_model` raises `SpatialBuildBlockedError`: registration, ground mesh and height grid are not implemented (Open3D is an optional extra).
- **FR-037 landmark wiring.** `POST /api/spatial/landmarks` answers `blocked` with the default edge backend (only a backend that implements `propose_landmarks` returns proposals); `web/calibrate/` has no browser test.
- **FR-042 / NFR-035 local SAM.** `vigil/meta/sam_local.py` `track_concept_local` is a stub; backend selection has no tests.
- **FR-028 Glimmer server.** Only the client is tested; no llama.cpp server or H-03 run.
- **FR-033 / FR-034 live paths.** No in-order, once-only window loop (`test_live_loop.py` missing); no WebRTC view test.
- **Performance.** `tests/e2e/test_perf.py` does not exist (NFR-005, NFR-030, FR-040 frame rate and load time).
- **NFR-022.** Mask badges are untested (sentence badges pass).
- **NFR-021.** Timed clean-clone run not done.
- **Single replica only.** Budget reservations are held in memory per process, so the race-free cap check (FR-043) holds only with one sandbox replica on one ledger file. Several replicas would need SQLite-level reservations.
- **Owner UI.** Only `web/calibrate/` sends the owner token; the main app (`web/app.js`) has no owner UI for check-in or windows yet. `GET /api/live/stream` stays LAN-only without the token (EventSource cannot send an `Authorization` header).

- **Residual review risks (low, accepted for the hackathon; second review round, Nov 3).**
  - Check 7 role cues are a denylist (`config/role_banned_words.json` `cues`). Two rounds of paraphrases are covered by tests, but a new wording can still state an origin the ledger does not back. Mitigation: the card shows each subject's role and `role_basis` from code beside the story, and verdicts never read the story.
  - A read timeout or a mid-stream transport error after a request is sent is recorded as unbilled, so a retry can under-count spend by one estimate.
  - Compiled rules with other impossible trigger and target pairs (touch on a zone or line, enter or dwell on a protected object, cross on a zone) get a limits note, not a refusal, so a confirmed rule can silently never fire. Only removed-on-object is refused or mapped to a watch.
  - Check 7 name detection skips the sentence's first word and matches ASCII capitals only ("Sam touched…", "…with Élodie").

## Deployment settings added on Nov 3 (fix round)

| Setting | Effect | Where |
| --- | --- | --- |
| `VIGIL_LEDGER_PATH` | Durable SQLite (WAL) spend ledger; the single source of truth for every cap, rebuilt on restart. Unset or unwritable: the app still starts, the ledger stays in memory and **paid calls are refused** (credit-window calls still work) | Docker image sets `/data/ledger.db` on `VOLUME /data`; run **one replica** with a named volume mounted at `/data` |
| `VIGIL_OWNER_TOKEN` | Required for the owner endpoints: `POST /api/checkin`, `POST`/`DELETE /api/windows`, `POST /api/spatial/pairs`, `POST /api/spatial/landmarks` (Bearer or `X-Vigil-Owner`). Unset: those endpoints answer 403 "owner endpoints disabled". They also stay LAN-only, JSON-only and same-origin | Edge box `.env` |
| `VIGIL_TRUSTED_HOSTS` | Edge and dev only: Host-header allowlist against DNS rebinding (default `127.0.0.1`, `localhost`, `testserver`); private and loopback IP literals are always allowed, so a phone can open the box by LAN IP. Any other host name gets 400. The public sandbox has no owner or LAN route and skips the check | Edge: add the mDNS name if you use one (e.g. `["vigil.local"]`) |
| `VIGIL_JUDGING_END` | Defaults to **Nov 10, 23:59 PT**; no live call of any funding after it, even without `VIGIL_CREDIT_WINDOW_END` | Sandbox env (leave unset for the default) |

Since `judging_end` defaults to Nov 10, an offline test that uses the real clock and makes a live client or guard call without setting `judging_end` will fail after that date; the current suites use fixed clocks.

## Blocked by Meta API credits

Needs claimed credits, the $140 limit and the budget guard on ([credits runbook](runbooks/credits-billing.md), `budget-check` skill). Nothing here runs without explicit owner approval.

- T-03 smoke tests (`scripts/smoke_meta.py --live`): one recorded response per model, and the 3 open API questions in [spec 5.14](spec/vigil-spec.md#514-verified-meta-api-facts-this-design-depends-on) (Wonder strict schema, Voice Transcribe batch endpoint with WAV input, Spark video with a strict schema). No live Meta call has ever run; all Meta fixtures are authored.
- Real-data acceptance of FR-004, FR-006, FR-007, FR-009, FR-013 (Spark path), FR-014, FR-019, FR-020, FR-021 (10 reference phrasings), FR-022 (5 spoken phrasings), FR-023, FR-025, FR-037 (SAM landmark proposals, unless local), FR-043 (estimate within 10% of the Billing page).
- NFR-006, NFR-007, NFR-012, NFR-020, NFR-035 (API side), NFR-036.

## Blocked by field hardware

Needs the 4 Reolink cameras, the iPhone Pro LiDAR, filming with consent, the RTX 3090 with open weights, or a phone ([runbooks](README.md#index), `field-runbook` skill).

- **Reolink cameras (T-04, T-05, T-26):** FR-030 to FR-034; NFR-027 to NFR-029, NFR-031 (cellular port check), NFR-033.
- **LiDAR scan, landmarks and audit markers (T-06, T-10, T-12, T-14, T-15, T-17):** FR-035 to FR-040; NFR-024 to NFR-026, NFR-030, NFR-032.
- **Daylight filming (T-07a: A, B, B′) and night filming (T-07b: A′, C), labels first:** FR-002, FR-003, FR-005, FR-008, FR-010, FR-011, FR-017, FR-018, FR-024, FR-027 (real bundle), FR-029 (B′), FR-044; NFR-001, NFR-003 (12-story scan), NFR-008, NFR-019, NFR-023 (incl. the role miss rate, day and night).
- **3 consented voice WAV fixtures (T-07a):** FR-022 and NFR-002; `config/audio_fixtures.json` lists none yet, so the sample-audio buttons serve cached transcripts.
- **RTX 3090 with open weights (H-02 to H-04):** FR-028, FR-042, NFR-035.
- **ESP32 boards:** FR-041 (deferred past Nov 4).

## Blocked by DGX Spark (D-1, conditional)

Off by default ([runbook](runbooks/dgx-spark-d1.md), [spec 10.4](spec/vigil-spec.md#104-advance-notice-dgx-spark-phase-d-1-conditional-not-yet-triggered)). It runs **only if gate H-02 fails at Mon 22:00 PT**, Tue 08:00 to 12:00 PT. If triggered: NFR-034 needs a probe report for the Spark, and FR-042's `VIGIL_SAM_BACKEND=remote` needs building.

## Needs owner action

### Blockers to clear today

From [spec 13.4](spec/vigil-spec.md#134-blockers-to-clear-today), with the extra owner actions found in the bootstrap. Tick here, with the date. The agents cannot do any of these.

- [x] Repo access and audit (Nov 2)
- [x] H-01 on the RTX 3090: Ready (Nov 2)
- [x] **Live calls during judging: ON with a $25 hard cap** ($5/day, until Nov 10 23:59 PT; owner decision, Nov 2). Implemented and tested (FR-043, NFR-037)
- [ ] **Claim the Meta API credits** (deadline Nov 4, 9 PM ET = 6 PM PT; needed now for T-03)
- [ ] **Read the Credit Terms**: exact expiry (sets `VIGIL_CREDIT_WINDOW_END` before Nov 4, 9 PM ET), per-model coverage, what happens at zero balance
- [ ] **Set the $140 Billing limit**; check the Billing page for spend since Oct 26; separate dev and sandbox keys. At window end, the second stop ([credits runbook](runbooks/credits-billing.md#8-live-calls-during-judging-decided-on-nov-2))
- [ ] **Consent** from everyone who will appear on camera or in a voice fixture ([HACKATHON.md](../HACKATHON.md))
- [ ] **Reolink models** for the 4 cameras, firmware, NVR or Home Hub ([reolink runbook](runbooks/reolink.md))
- [ ] An iPhone Pro with LiDAR before sunset (4:55 PM PT) ([lidar runbook](runbooks/lidar-scan.md))
- [ ] **Track** (Indie or Startup) and **team members** ([HACKATHON.md](../HACKATHON.md))
- [ ] **`MODEL_API_KEY` GitHub secret** for the sandbox key (CI never makes live calls; needed for T-28)
- [ ] **Hosting account** for the sandbox deploy (T-28, Tue 23:00) and its judging env: `VIGIL_ALLOW_PAID=1` from window end, `VIGIL_JUDGING_CAP_USD=25`, `VIGIL_JUDGING_END` (default Nov 10, 23:59 PT)
- [ ] **Sandbox ledger volume:** a named volume mounted at `/data` (`VIGIL_LEDGER_PATH=/data/ledger.db`), **one replica** only. Without a writable ledger, paid judging calls are refused
- [ ] **Edge `VIGIL_OWNER_TOKEN`** (a long random secret, never committed) and, if the LAN app is opened by IP or mDNS name, `VIGIL_TRUSTED_HOSTS`. Without the token, check-in, windows and the calibration tool answer 403
- [ ] **Make the repository public** before submission ([submission runbook](runbooks/submission.md))
- [ ] **Accept the SAM 3.1 licence on Hugging Face** (H-02, H-04, FR-042)
- [ ] **Approve the torch / GPU install** in the project environment for H-02 to H-04 ([GPU runbook](runbooks/gpu-h01-h04.md))
- [ ] **Approve the Muse Glimmer 4-bit GGUF download** and the llama.cpp server for H-03 (FR-028)

## Next executable steps

From the revised [spec 9.7](spec/vigil-spec.md#97-tasks-in-order-times-pt-tracks-a-pipeline-b-models-and-reasoning-c-app-and-3d-d-field-work-and-evidence) timeline; full calendar in the [schedule](plans/schedule.md). Sunset Mon Nov 2 is 4:55 PM PT.

### Monday Nov 2

1. ~~Integrator: commit the working tree and record the CI run~~ Done Nov 3: [run 41604381135](https://github.com/gabrielromerod/meta-global-ai-developer-hackathon-2026/actions/runs/41604381135) (every job and every step green, report-only steps included, on `6dee3bf`; 1418 passed locally, 18 E2E).
2. **Owner, overdue (13:00):** T-01 remainder: claim credits, set the $140 limit, pick the track.
3. **Daylight block (13:00–16:55):** **13:45** T-04 Reolink probe, privacy masks, audio off, zone `kind`s drawn (egress, perimeter); **14:30** T-05 capture running, T-03 smoke tests (credits); **15:45** T-06 LiDAR loops, 6 landmark pairs per camera, 6 audit markers per camera surveyed, 2 scale distances; **16:50** T-07a daytime A, B, B′ with consent, labels first, 3 consented WAV fixtures.
4. **Night block (17:15 setup; filming after about 17:55 in IR, until 19:00):** T-07b A′ and C, labels first; optional take of a household member returning from the street without a check-in.
5. **20:00** T-08 on real footage; T-10 3D build (the FR-035 gap must close first). **21:00** T-09 SAM tracks for A, A′, B, B′, C. **22:00** H-02 gate; T-11. **23:00** T-12 landmark tool and solver; **G1**. Overnight: 2 h capture endurance.

### Tuesday Nov 3

6. **08:00–12:00** D-1 only if H-02 failed. **09:00** T-13 origin tagging on real tracks. **10:00** T-14 extrinsics accepted or the site-plan fallback (**cut-off**); T-16 appearance notes. **10:30** T-15 audit-harness marker walk. **11:00** T-17 coverage.
7. **12:00** T-18 visits, gaps, roles; T-19 positions; H-03, H-04. **13:00** T-20 rules, story, check 7, verdict; **G2**.
8. **15:00** T-21; **16:00** T-22 voice and typed rules, windows, check-in; **17:00** T-23; **17:30** T-24; **18:00** T-25 guards incl. the judging cap; **G3**: the 5 blocking P0 suites green.
9. **21:00** T-26 live loop; **22:00** T-27 benchmark, audit harness, baseline, Tier 0 / Tier 1 rates; **23:00** T-28 sandbox with the judging config; **G4**.

### Wednesday Nov 4

10. **12:00** T-29 video, README, HACKATHON.md. **14:00** T-30 submission ([runbook](runbooks/submission.md)).
11. **Before 18:00 PT (9 PM ET):** credits claimed; `VIGIL_CREDIT_WINDOW_END` set; Billing second stop checked.

## Critical risks

Tracked in [spec 13.3](spec/vigil-spec.md#133-critical-risks), including the High-likelihood false alert (a household member arriving from the street without a check-in counts as non-household) and the Low-likelihood missed alert (an unobserved entry, then a door). Decision points are in the [schedule](plans/schedule.md#gates).
