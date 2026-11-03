# Spec change set — Nov 2, 2026: six business, product and schedule corrections

Applies to [`docs/spec/vigil-spec.md`](../vigil-spec.md). Each block below replaces the block of the same name in the spec, and every block has already been applied there. The blocks were refreshed after the adversarial review of the same afternoon (see [Review corrections (Nov 2)](#review-corrections-nov-2)), so each one equals the final spec text. The architecture, the deterministic validator, code-owned verdicts and FR→module→test traceability are unchanged.

## Summary of spec diffs

- [x] **1. Spatial origin roles, with no identification.**
  - FR-008 tags each track's origin zone (majority foot point in the first 10 frames, voided after an observation break or a non-egress track near the door) and FR-010 propagates `actor_role`.
  - FR-012 and FR-021 extend `applies_to` to `anyone | external_visitor_only | non_household`.
  - FR-029 becomes a pre-set Expected Guest / Delivery Window and owner check-in (P2 → P1). Windows apply only to perimeter arrivals in their scope.
  - UC-03, section 4 (A′ vs C, both at night) and the 9.4 contracts are updated.
  - Unknown origin **fails closed**: it is treated as non-household. Household and expected roles never carry across a blind spot on transit time alone.
  - LAN presence counts only as an **explicit owner check-in**, never as passive Wi-Fi association. A check-in is single-use, never retroactive, and binds at most one chain in the 120 s after the tap.
  - Validator check 7 stops the story from asserting a role that the ledger does not hold (role phrase list, banned role words, name test).
  - The claim is narrow: Vigil does not identify anyone and creates no face, voice or body templates.
- [x] **2. Muse Voice Transcribe back to P0.**
  - FR-022 is P2 → P0.
  - Judge step 6 and T-22 offer hold-to-speak, 3 pre-recorded audio fixture buttons, or typing. Transcribe and compile are separate calls, so the transcript is editable.
  - Section 0 states the 5-model loop. Glimmer's part depends on gate H-03, and this is stated rather than assumed.
- [x] **3. Product onboarding separated from the benchmark protocol.**
  - FR-036 makes nominal-FOV intrinsics the primary path; the checkerboard is optional, done once per camera *model*.
  - FR-037 uses 6-landmark PnP; in UC-10, SAM 3.1 proposes the landmarks.
  - Section 7 and diagram 5.12 are reframed, and NFR-024 to NFR-026 become the ground-truth audit harness.
  - The ±0.4 m figure is now something to **measure**, not to promise.
- [x] **4. Section 11 renamed and 11.9 Commercial Unit Economics added.**
  - The three-tier funnel is priced from the 11.3 table, with formulas.
  - Two figures in the change request are corrected and the arithmetic is shown: "$0.06/day" only holds at about 2.7 escalations/day with a compact ledger, and the margin is about 78–83% including payment fees (83–88% excluding them) before edge-box power, not ">85%".
  - The edge box's own power cost is listed ($15–26 per month).
- [x] **5. Live calls stay on during judging.**
  - Nov 5–10 PT: `VIGIL_ALLOW_PAID=1`, a **$25 hard cap** (`VIGIL_JUDGING_CAP_USD`), $5/day and 10 requests/min/IP, and no paid call after `VIGIL_JUDGING_END` (Nov 10, 23:59 PT). The $25 total binds before the daily caps.
  - Hitting the cap or a timeout falls back to cached results with a notice.
  - FR-043, NFR-036, NFR-037, 11.6 and 11.8 are updated, and the decision is recorded as made by the owner on Nov 2.
- [x] **6. Re-baselined schedule and CI triage.**
  - Daylight block 13:00–16:55 PT: T-04, T-06, T-07a (scenarios A, B, B′). Night block 17:15 setup, filming after about 17:55 (cameras in IR) to 19:00 PT: T-07b (scenarios A′ and C).
  - Spec 12.1 is split into **5 blocking P0 suites** and non-blocking P1/P2 suites. The non-blocking suites still run in CI, report only, so regressions stay visible.
  - **Consequence:** rule r7 moves to **17:30–06:00 ("side gate after dark")**, because scenario C is now filmed at about 18:00. Recorded timestamps are never relabeled.

**Status at the time of this change (Nov 2, 12:52 PM PT):**
- T-01's audit part is done.
- T-02 is done (commit `3d53d05`, CI green).
- H-01 is done: the 3090 is Ready (`eval/hardware/3090.json`: CUDA 13.0, torch 2.14.1, 30 s burn at about 64 TFLOPS, peak 67 °C, about 48 W idle and 349 W under load, GPU board power from nvidia-smi).
- The bootstrap offline core is in integration; see `docs/readiness.md`.

---

## Section 0 — Baseline and scoring logic (replaces the intro paragraph, "Scope change" and the scoring table)

This plan defines 44 functional requirements (FR-001 to FR-044), 34 of them P0 for the MVP. Every one can be built, tested and demoed by **Wed Nov 4, 2:00 PM PT**, and each traces to a module, a test and a piece of demo evidence. The section 0 audit was run on Nov 2: the repository was empty, so there is no prior work to disclose (`docs/audit/2026-11-02-repo-audit.md`).

**Scope change (Nov 2, revised).** Core additions:

- The 4 home Reolink cameras become the testing environment (section 6).
- A phone LiDAR scan becomes a 3D model of the house (section 7).
- Each camera is placed in that model by **SAM 3.1-assisted landmark alignment**: nominal lens FOV plus 6 fixed landmarks such as door frames, gate posts and shed corners. Checkerboards and surveyed tape markers are kept only as the benchmark's ground-truth audit harness (section 7, EVAL).
- A 3D viewer becomes the main view, replacing the 2D yard map.
- **Spatial origin roles (no identification).** A person who walks out of the house's own doors and is followed without an unresolved break is treated as `household_insider`. A person who arrives from the perimeter, on a camera or zone inside an owner-set guest or delivery window's scope, while the window is active, is `expected_visitor`. A person entering from the street, the driveway entry or the side alley is `external_visitor`. Rules can then say "anyone except household", and Vigil does not identify anyone and creates no face, voice or body templates (FR-008, FR-010, FR-012, FR-021, FR-029, FR-044).
- **Voice rules are back in the MVP (FR-022, P0).** "Tap and speak" completes a **5-model Meta AI loop**:

  | Model | Role | File |
  | --- | --- | --- |
  | SAM 3.1 | perceives: masks, tracks and landmark proposals | `meta/sam.py` |
  | Muse Glimmer 30B on the local 3090 | triages routine visits at $0 API cost | `meta/glimmer.py` |
  | Muse Spark 1.3 | describes appearance and compiles rules | `meta/spark.py` |
  | Muse Wonder 1.0 | writes the cited story and steers SAM through watch proposals | `meta/wonder.py` |
  | Muse Voice Transcribe 1.0 | turns spoken rules into text | `meta/asr.py` |

  Glimmer's part depends on gate H-03 and runs only on the home edge and in the benchmark; the hosted sandbox's live triage uses Spark, and Glimmer appears there as recorded trace badges. If H-03 fails, triage falls back to Spark and the loop is 4 models (SAM 3.1, Spark, Wonder, Voice Transcribe), with SAM 3.1 on open weights locally only if H-02 passes. The README must say which configuration was used.

Wi-Fi sensing was evaluated and stays out of the submission (section 8). The spatial work keeps its hard cut-off: if landmark PnP has not passed by **Tue 10:00 AM PT**, switch to the measured site-plan fallback (section 7) and keep going.

### Scoring logic behind every choice
| Criterion (weight) | What earns the score | Where this plan delivers it |
| --- | --- | --- |
| Impact (30%) | A real, relatable problem; a usable product; theme fit | Alert fatigue solved without identifying anyone: the same walk across the yard reads as household (quiet) or external visitor (alert) from spatial origin alone (FR-008, FR-012). Measured alert reduction (FR-024). A homeowner setup in minutes with SAM-assisted alignment (UC-10). Unit economics that support a consumer subscription, with the arithmetic shown (11.9) |
| Use of Meta AI tooling (25%) | Beyond basic integration; unexpected capabilities | Five models in distinct roles in one closed loop (above): Spark citing SAM's own track tags; Wonder steering SAM (FR-020); SAM proposing calibration landmarks; voice rules (FR-022); local Glimmer triage |
| Technical depth (20%) | Sound engineering, refinement, craft | Code-owned verdicts and roles, a validator that also checks role claims, topology linking, gaps as data, fail-closed role propagation, a ground-truth audit harness, a pre-registered benchmark, 5 blocking CI suites |
| Demo (25%) | Works, impressive, holds up live, good video | Hosted sandbox **with live calls kept on through judging** under a $25 hard cap (11.8); cached fallback with a notice; voice with 1-click audio fixtures; telemetry panel |

**A 10/10 cannot be promised.** The plan instead removes every known reason to lose points, and makes each claim checkable by a judge in one click.

---

## Section 1 — FR deltas (each row replaces the row with the same ID; FR-044 is new; FR-013 and FR-027 changed in review)

| ID | Pri | Requirement and expected behavior | Depends on | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- |
| FR-008 | P0 | **Event builder with origin tagging.** Emits `enter`, `exit`, `cross`, `touch` (person mask overlaps a protected object), `removed` (watched object disappears while a person overlaps it) and `dwell`. When more than one person mask overlaps a protected or watched object, one `touch` (or `removed`) event is emitted per overlapping track, each carrying its own subject's `actor_role`; rules are evaluated per event. Each event has an ID, camera, times, track, clip range and the `actor_role` of its subject (filled in after visit assembly, FR-044). Each track also gets an `origin_zone`: the zone, by `kind` (`egress`, `perimeter`, `interior_yard`), that contains the track's foot point in the majority of its first 10 frames (1 s); no zone or a tie gives `null`. The origin is `null` unless that camera observed without interruption for the 2 s before the track's first frame: no outage, no skipped or unprocessed window, and not the first frame of a window whose predecessor was skipped. An `egress` origin is also `null` when any person track on that camera that did not itself originate in that egress zone was last seen overlapping the egress polygon, dilated by 50%, within the preceding 10 min | FR-007, FR-019 | Synthetic-track unit tests pass for every event type. A track born inside `front_door_egress` gets that origin; a track born mid-yard gets `null`; a track re-born in `front_door_egress` 5 s after a courier's track ended there gets `null`; a track whose first frame follows a skipped window gets `null`. Two overlapping tracks on `po_side_gate` give two touch events. Each demo scenario yields its labelled events and origins | Not verified |
| FR-010 | P0 | **Visit assembly.** Tracks are linked across cameras only when the gap fits a topology edge and the notes agree; two or more candidates means no link. *(Unchanged, plus:)* the visit records one **subject chain** per linked set of tracks, which carries the role (FR-044). When a link on a non-blind edge is ambiguous only because 2 or more candidates entered the edge together, every candidate holds the same role, and the same number of tracks emerge, each emerging chain takes that role with basis `group:<role>` while the tracks stay unlinked. This never applies across a blind-spot edge | FR-008, FR-009 | Link precision at least 90% on the labelled set | Not verified |
| FR-012 | P0 | **Rules engine.** Rule JSON with target, trigger, time window (crossing midnight), severity and **`applies_to`** (`anyone` \| `external_visitor_only` \| `non_household`). A rule fires only when the event's `actor_role` is in the set its `applies_to` covers (table in 9.4). Two default rules: watched package removed (`non_household`), and a non-household person in the backyard 23:00 to 05:00 (`non_household`) | FR-008, FR-044 | Truth-table tests pass, including windows across midnight and every `applies_to` × `actor_role` pair. `unknown` is always treated as non-household | Not verified |
| FR-013 | P1 | **Triage.** Code forces escalation when a rule fired, a protected object was touched (except a 9.4 case-2 touch by a `household_insider`), or a gap is unresolved; otherwise Spark decides. Visits not escalated get a story built from a template | FR-012 | Forced cases always escalate; the escalation rate is reported in EVAL | Not verified |
| FR-021 | P0 | **Typed rules.** Spark compiles text into rule JSON whose targets are limited to existing objects and zones. Identity phrases map to roles, never to people: "anyone except family", "except us" and "not the household" → `non_household`; "strangers only" and "not guests or deliveries" → `external_visitor_only`; a named person ("except Sam") → `non_household` plus the notice "Vigil can't recognise individuals. It treats someone as household only if they came out of the house's own doors or checked in on the app, so Sam is exempt only in those cases." The draft card states the basis: *"Vigil treats someone as household only when it saw them come out of the house's own doors, or when a household member checked in on the app just before coming into view. Household members arriving from the street without checking in, and anyone Vigil loses track of, count as non-household and can trigger this rule. Vigil places people by where they came from; it does not identify anyone and creates no face, voice or body templates."* The owner confirms | FR-012, FR-019, FR-044 | At least 9 of 10 reference phrasings compile to the expected JSON, including 3 role phrasings. An unresolvable target asks a question. No compiled rule ever names a person | Not verified |
| FR-022 | **P0** | **Voice rules ("tap and speak").** The browser records up to 30 s, downsamples to 16 kHz mono and encodes 16-bit PCM WAV in the client (30 s ≈ 0.96 MB; WAV input ⚠️ to be confirmed in T-03; the sandbox image has no ffmpeg). Muse Voice Transcribe 1.0 (batch endpoint, ⚠️ confirmed in T-03) returns text the owner can edit before compiling (FR-021). For judges without a microphone, **3 pre-recorded audio fixture buttons** each send a short consented WAV (`demo/voice/`, NFR-002), and each has a cached transcript for the offline fallback | FR-021 | 5 of 5 spoken reference phrasings compile correctly live. All 3 fixture buttons work live and in cached mode, and with `MODEL_API_KEY=invalid`. A 30 s recording is under 2 MB | Not verified |
| FR-027 | P0 | **Export and scenario switcher.** `vigil export` writes a demo bundle (masked clips, overlays, DB); the sandbox switches between scenarios A, A′, B, B′ and C | FR-017 | A clean clone plus `make demo` serves all 5 | Not verified |
| FR-029 | **P1** | **Expected Guest / Delivery Window and owner check-in** (was "owner label"). The owner sets a time window before it starts (start and end, optional cameras or zones, optional label such as "plumber" or "deliveries"). Subjects whose first track starts in a `perimeter` zone in the window's scope while it is active are `expected_visitor` (FR-044 step 3). Windows are capped at 12 h, show on the cards, and can be cancelled. The post-hoc "This was expected" button stays as feedback only and never changes a verdict retroactively. Also: an "I'm outside" check-in (LAN app, `POST /api/checkin`), single-use and never retroactive, which binds at most one subject chain in the 120 s after the tap (FR-044 step 2); an unused check-in expires after 30 min | FR-044 | A subject arriving inside an active window is `expected_visitor`, and one arriving from a perimeter zone 1 s after it ends, or on a camera outside its scope, is `external_visitor`; one with a `null` origin is `unknown`. Windows persist and expire. A check-in binds at most one chain | Not verified |
| FR-036 | P0 | **Intrinsics.** The primary path is **nominal lens FOV** from the camera model's datasheet: focal length from the horizontal FOV at the processed resolution, principal point at the centre, no distortion. It is flagged `fov_nominal`. Optional lab refinement: one checkerboard session (about 20 views) **per camera model**, stored as a lens profile and reused for identical units; RMS under 1.0 px | FR-030 | Every camera has intrinsics: nominal, flagged, or a model lens profile with RMS under 1.0 px. The source is shown in the calibration report | Not verified |
| FR-037 | P0 | **Extrinsics from landmarks.** In the calibration tool, SAM 3.1 proposes fixed-landmark masks on each camera still (concept prompts `door`, `gate`, `fence post`, `window`, plus the corners of masks). The installer accepts 6 landmark points per camera and clicks the same points on the mesh (one click each). PnP with RANSAC runs on the 6, saved to `calibration.json`. Accuracy is **not** asserted from the 6 points; it is measured by the audit harness (NFR-024 to NFR-026) | FR-035, FR-036, FR-019 | Mean reprojection on the 6 landmarks under 6 px at 1280 px (nominal FOV) or under 4 px (lens profile). The audit-harness held-out ground error is reported per camera, target under 0.25 m | Not verified |
| FR-043 | P0 | **Budget guard.** Prices every call before sending. Enforces the credit cap ($140, `credit`-tagged spend only), feature and daily caps, plus the **judging cap** (`VIGIL_JUDGING_CAP_USD=25`, $5 per day) on spend after the credit window ends. Warns at 50, 75 and 90%. Gives pre-flight estimates for batch commands. After the credit window, paid calls are allowed only while `VIGIL_ALLOW_PAID=1`, before `VIGIL_JUDGING_END` (Nov 10, 23:59 PT), and the judging cap has room. The ledger tags each call `credit` or `paid` (9.3) | FR-023 | Unit tests: refusal at each cap; refusal at the judging cap; window-end switch with and without `VIGIL_ALLOW_PAID`; refusal after `VIGIL_JUDGING_END`; estimate within 10% of the Billing page after T-03 | Not verified |
| FR-044 | **P0** | **Spatial origin roles (new; no identification).** `visits.py` assigns each subject chain an `actor_role` from evidence only, in this order: (1) its first track's `origin_zone` is an `egress` zone of the house → `household_insider`, basis `egress:<zone>`; (2) an **explicit check-in** binds it: a household member tapped "I'm outside" in the LAN app (passive Wi-Fi presence never counts). A check-in is single-use and never retroactive. When the 120 s interval after the tap closes, it binds the one subject chain whose first track started in that interval with `origin_zone` `null`, `interior_yard` or `perimeter` (never `egress`), but only if exactly one such chain started and no subject other than `household_insider` was in view on any camera at that chain's first frame; otherwise it binds nothing. A bound chain is `household_insider` with basis `checkin:<id>`. An unused check-in expires after 30 min; (3) its first track's `origin_zone` is a `perimeter` zone on a camera (or zone) in the scope of an Expected Window (FR-029) that is active at that track's first frame → `expected_visitor`, basis `window:<id>`. A window with no listed cameras or zones covers every perimeter zone. A `null` origin never becomes `expected_visitor`; (4) its origin is a `perimeter` zone → `external_visitor`, basis `perimeter:<zone>`; (5) otherwise → `unknown`, basis `ambiguous_link:<track_id>` when its first track followed an ambiguous link, else `origin_null:<track_id>` (origin `null` or an `interior_yard` zone); the same-role group rule in FR-010 (basis `group:<role>`) is the only exception. Roles carry across a link only when the link is unambiguous. Across a blind-spot gap, `external_visitor` carries on any unambiguous re-link (it can only make rules fire). `household_insider` and `expected_visitor` carry only when both tracks' appearance notes agree on at least one attribute that is not `unknown` (upper colour, lower colour or a carried item). A re-link on transit time alone, as at night under IR, makes the chain `unknown` with basis `gap_unresolved:<gap_id>`. Every role has a stored `role_basis` shown in the trace. If FR-029 is not built, step (3) never matches and FR-044 still passes | FR-008, FR-010 (FR-029 and the check-in only supply inputs; without them, rules (2) and (3) never apply) | Truth table over origin × check-in × window × link outcome. Scenario A subject = `household_insider` (basis `egress:front_door_egress`); scenario C subject = `external_visitor` (basis `perimeter:side_alley`). An ambiguous re-link gives `unknown`. A household subject enters `shed_back`; a never-seen person with `unknown` colours emerges inside 5–180 s → `unknown`. Two household members leave the front door together and two tracks emerge on `side_left` → both `household_insider` (basis `group:household_insider`). Two chains starting in one check-in's 120 s interval → neither is bound. No face, voice, body or name field exists in any person-related schema (NFR-003). EVAL reports assigned vs labelled role per subject, day and night separately, including the share of household subjects not assigned `household_insider` (role miss rate) and the alerts it caused | Not verified |

### NFR deltas (NFR-002, NFR-003, NFR-012, NFR-013, NFR-036 and NFR-037 changed in review)

| ID | Area | Requirement | Target | Validation method |
| --- | --- | --- | --- | --- |
| NFR-002 | Privacy | No camera audio leaves the house or enters the repo. Voice-rule speech (FR-022) is sent only to Muse Voice Transcribe and is never written to disk or the response cache (only the transcript is cached, keyed by the audio hash). The only audio files in the repo are the 3 consented voice-rule fixtures under `demo/voice/`, listed by SHA-256 in `config/audio_fixtures.json` | 0 camera audio streams in any video; 0 audio files outside the fixture list | ffprobe check in the same scan; a repository-wide check (`git ls-files`) fails on any .wav, .mp3, .m4a, .ogg or .webm file not on the fixture list |
| NFR-003 | Privacy, fairness | The appearance, track, subject, event and position schemas have no face, age, gender, skin, ethnicity, height, gait, body-measurement, voice-feature or name fields, and the UI never shows such words. Vigil does not identify anyone and creates no face, voice or body templates | 0 such fields; 0 such words in the 12 stories | Schema unit test checks every field of those schemas against an allowlist; word-list scan over generated stories |
| NFR-012 | Cost | Full benchmark (12 scenarios) within the API credit | Under $25 with local SAM; under $40 including the baseline if API SAM is needed (H-02 fails) | Ledger sum, published in EVAL.md |
| NFR-013 | Cost | Sandbox spend is capped per day | $10 per day from credits before the window ends; after it, $5 per day and $25 in total (NFR-037). At a cap, live requests return the cached result with "Live budget for today used; recorded result shown" | Unit test on both caps; manual check on the deployed site |
| NFR-024 | Spatial accuracy | Calibration quality, measured by the **ground-truth audit harness** (surveyed markers never used for calibration) | Landmark reprojection under 6 px (nominal FOV) or 4 px (lens profile) at 1280 px; held-out ground error under 0.25 m; lens-profile RMS under 1.0 px where a profile exists | Calibration report from `vigil spatial calibrate` plus the audit-harness report, both committed |
| NFR-036 | Cost | Credit-funded Meta API spend (ledger tag `credit`) | Under $140 in `credit`-tagged calls; no single feature over its budget in section 11.4. Post-window `paid` spend is governed by NFR-037 (≤ $25) and does not count toward the $140 | Ledger (by `funding` tag) plus Billing page, reconciled daily |
| NFR-037 | Cost | No charges after the credit window except the approved judging allowance | 0 paid calls after the window unless `VIGIL_ALLOW_PAID=1`; with it, all post-window spend (from `VIGIL_CREDIT_WINDOW_END` to `VIGIL_JUDGING_END` = Nov 10 23:59 PT) is ≤ $25 in total and ≤ $5 per PT calendar day. The total binds first: 6 days × $5 = $30 > $25, so if every day is used fully, Nov 10 serves cached results. No paid call after `VIGIL_JUDGING_END` | Unit tests on the window-end switch, the judging cap and the end date; ledger check daily Nov 5–10 |

---

## Section 3 — UC-03 and UC-10 (replace both)

### UC-03 Create a rule (owner)
- **Trigger:** owner taps the mic and speaks, taps one of the 3 sample-audio buttons, or types a rule. **Preconditions:** the target object or zone exists.
- **Main flow:**
  1. (Voice) the browser records up to 30 s and encodes 16 kHz mono WAV; Muse Voice Transcribe returns a transcript, which stays editable.
  2. Muse Spark compiles rule JSON, with targets limited to existing objects and zones and identity phrases mapped to roles.
  3. A draft card states the rule in plain words, including whom it applies to.
  4. The owner confirms and the rule becomes active.
- **Role phrasing:** "Tell me if anyone except family opens this gate after dark" compiles to `applies_to: "non_household"`. The draft card says: *"Applies to everyone except household members. Vigil treats someone as household only when it saw them come out of the house's own doors, or when a household member checked in on the app just before coming into view. Household members arriving from the street without checking in, and anyone Vigil loses track of, count as non-household and can trigger this rule. Vigil places people by where they came from; it does not identify anyone and creates no face, voice or body templates."*
- **Alternatives:** a named person ("except Sam") compiles to `non_household` with the notice "Vigil can't recognise individuals". "Strangers only, not deliveries" compiles to `external_visitor_only`.
- **Errors:**
  - Target not found → "Which object do you mean?" with the list.
  - No microphone or permission denied → the sample-audio buttons and typing.
  - Transcription fails → the editable empty transcript plus typing.
  - Compile fails twice → the owner fills the form fields directly, including an `applies_to` selector.
- **Outcome:** active rule `rN`, visible in the rules list with its `applies_to` badge.

### UC-10 Place the cameras in the 3D model (installer or homeowner)

There are two flows: the product flow every home uses, and the audit protocol only the benchmark uses.

**A. Commercial onboarding: "SAM 3.1-assisted spatial alignment" (target under 5 minutes per camera; ⚠️ a target, timed in the benchmark, not yet measured)**
- **Trigger:** first run, or a camera has moved. **Preconditions:** phone with LiDAR; camera model known.
- **Main flow:**
  1. Walk a short LiDAR loop around each side of the house (about 2 minutes per side) → `vigil spatial build`.
  2. Intrinsics come from the camera model's nominal FOV, or its lens profile if one exists.
  3. On each camera still, SAM 3.1 proposes fixed landmarks (doors, gate posts, shed corners, window corners). The homeowner accepts 6 and taps the same 6 on the 3D model.
  4. PnP places the camera → `vigil spatial coverage` → blind regions are written to the config.
- **Alternatives:** too few landmarks visible → add a temporary landmark (any box or chair, scanned once). Registration fails → align each segment to a tape-measured site plan. Scan unusable → site-plan model.
- **Errors:** landmark reprojection over threshold → SAM proposes more landmarks and the worst point is dropped. A landmark is hidden → pick another.
- **Outcome:** `calibration.json` and the GLB pass their tests (FR-035 to FR-038).

**B. Scientific verification protocol (benchmark only, never required of a homeowner)**
- 6 surveyed ground markers per camera (24 in total), tape-measured to the world frame and **never used for calibration**. They provide the held-out ground error (NFR-024) and the marker walk for position accuracy and r95 truthfulness (NFR-025, NFR-026).
- 2 tape-measured distances check the scan scale (under 2%).
- An optional checkerboard session per camera *model* builds a lens profile.
- This is the evidence behind any "±0.4 m" claim. The demo only shows radii that this harness has measured.

---

## Section 4 — Scenario rows and judge steps 1, 3 and 6 (replace the "recorded evening" table and those steps)

| Scenario | What happens | Expected verdict | Expected evidence |
| --- | --- | --- | --- |
| A Routine (daylight, T-07a; variant A′ at night, T-07b) | A household member walks **out of the front door** (`front_door_egress`), gets in the car and drives off. Variant A′ (night block, inside r7's 17:30–06:00 window, before C): a household member walks out of the front door again and straight to the side gate (front → side_left link within 2–20 s), touches it and goes back inside; no alert fires because r7 applies to non-household | Normal, no alert | Role `household_insider` (basis `egress:front_door_egress`); templated story; escalated: no; A′: inside r7's window, r7 not fired because of `applies_to` (the trace shows the exclusion) |
| B Delivery (daylight, T-07a) | A courier arrives from the street (`driveway_entry`) and leaves a box on the porch. Variant B′: inside an owner-set delivery window | Noteworthy (B′: Normal or Noteworthy, depending on the loop) | Role `external_visitor` (B′: `expected_visitor`); Wonder story; watch "package on porch" activated by the loop |
| C After dark (night, T-07b, about 18:00 PT) | A person enters from the **side alley** (`side_alley`), touches the protected side gate, goes behind the shed, reappears 41 s later and leaves | Needs your attention | Role `external_visitor` (basis `perimeter:side_alley`); rule r7 "Side gate after dark" (17:30–06:00, `non_household`) fired; gap g4 of 41 s; the role carried across the gap because the re-link was unambiguous; validator log |

**Contrast that carries the Impact claim.** Scenarios A′ and C show the same touch of the same gate, after dark and inside r7's window, with opposite outcomes, decided only by where each person came from. The card's trace shows the `role_basis` for each.

**Timestamps are never altered.** Scenario C is filmed at about 18:00 PT because of the night block (section 9.7), so r7's window is 17:30–06:00. The card shows the real recorded time. (The earlier "22:14" label is retired.)

| Step | Judge does | System responds | AI processing | Visible proof |
| --- | --- | --- | --- | --- |
| 1 (0:00) | Opens the URL | 3D model of the house with 4 camera cones and coverage; evening summary "N motion triggers → V visits → 1 alert", with N and V measured | None (cached) | Real home cameras; coverage and blind regions from measured geometry; Cached badge |
| 3 (0:50) | Clicks a citation chip | Video players seek; side camera highlighted with the SAM outline; the matching disc lights up, labelled "Estimated ±\<r95> m from Side camera" (r95 from the audit-harness-calibrated locate()) | Overlays from cached SAM 3.1; positions from `locate.py` | Seen versus estimated shown side by side; model and call IDs |
| 6 (2:15) | Holds the mic and says *"Tell me if anyone except family touches the bin after 9 PM"*. Or taps one of the **3 sample-audio buttons**, or types it | Editable transcript → draft rule card: target the bin, trigger touch, 21:00–06:00, **applies to: non-household**, with the plain-words basis note → confirm → active rule | Live Muse Voice Transcribe 1.0 (WAV) → live Muse Spark 1.3 compile | Transcript and rule JSON side by side; model and call IDs; latency and cost; the "no face, voice or body templates" note. Offline: cached transcript and compile, labelled "recorded result" |

---

## Section 7 — Camera calibration (replaces the "Camera calibration" subsection)

### Camera calibration
Two separate protocols. The **product path** is what a homeowner does. The **audit harness** is how the benchmark proves the product path's accuracy. The demo never claims an accuracy figure that the audit harness has not measured.

| Step | Product path (every home) | Accept when | Fallback |
| --- | --- | --- | --- |
| Intrinsics | **Nominal FOV** from the camera model's datasheet: focal length from the horizontal FOV at 1280 px, centred principal point, no distortion, flagged `fov_nominal`. If a **lens profile** exists for the model (one checkerboard session of about 20 views on any unit of that model), use it instead | Profile RMS under 1.0 px; nominal FOV is always accepted, but flagged | Nominal FOV |
| Extrinsics | **SAM 3.1-assisted landmarks:** SAM proposes fixed-landmark masks on the camera still (`door`, `gate`, `fence post`, `window`, then mask corners); the installer accepts 6 points and clicks each once on the mesh; PnP with RANSAC on the 6 | Landmark reprojection under 6 px (nominal FOV) or under 4 px (lens profile) at 1280 px | Planar homography from 4 or more ground-level landmarks if the mesh is unusable |
| Record | `config/calibration.json`: camera matrix, distortion, model, `intrinsics_source` (`fov_nominal` or `lens_profile`), rotation, translation, image size, landmark error, audit errors (when measured), date | Loads and passes `test_calibrate.py` | none |

| Audit harness (benchmark only) | Method | Target |
| --- | --- | --- |
| Held-out ground error (NFR-024) | 6 surveyed markers per camera, tape-measured into the world frame and never used for calibration; their projections are compared with their surveyed positions | Under 0.25 m |
| Position accuracy and r95 honesty (NFR-025, NFR-026) | A person stands on the same 6 markers; locate() estimates are compared with the surveyed positions | ⚠️ Median under 0.5 m within 10 m of the camera; at least 90% inside the stated r95 |
| Scale (FR-035) | 2 tape-measured distances | Under 2% |

**Expected accuracy trade-off.** Reolink lenses are wide (about 80° to 110° horizontal). With nominal-FOV intrinsics and no distortion model, image-edge error grows. r95 must widen accordingly: `locate()` adds the camera's audit-harness error where it was measured (otherwise its landmark reprojection error, which is all a product home has), and adds a per-pixel radial term when `intrinsics_source = fov_nominal`, so stated radii stay truthful (NFR-026) even where they are larger. If the audit shows a camera misses NFR-024, record a lens profile for that model (about 15 minutes, once per model) and re-solve. The "±0.4 m" label in the demo is used only where the audit measured it.

Re-calibrate a camera if it is moved; `vigil spatial check` compares a reference still against the current view (P2).

---

## Section 9.4 — Contracts (replace the `cameras.yaml` excerpt, the Rule contract, the verdict note and the validator checks; add the role, window and check-in contracts)

**`config/cameras.yaml` (excerpt)** — zones now carry a `kind`, which drives FR-008 origin tagging:

```yaml
timezone: America/Los_Angeles
cameras:
  - id: front
    name: Front entrance
    zones:
      front_door_egress: {kind: egress,    polygon: [[560, 300], [700, 300], [700, 560], [560, 560]]}
      porch:             {kind: interior_yard, polygon: [[420, 380], [860, 380], [860, 720], [420, 720]]}
      driveway_entry:    {kind: perimeter, polygon: [[0, 300], [180, 300], [180, 720], [0, 720]]}
  - id: side_left
    name: Left side
    zones:
      side_alley: {kind: perimeter, polygon: [[200, 300], [420, 300], [420, 720], [200, 720]]}
    lines: {side_gate: [[812, 410], [870, 655]]}
    exits: {to_shed_back: [[1100, 380], [1280, 380], [1280, 720], [1100, 720]]}
  - id: backyard
    name: Backyard
    zones:
      back_door_egress: {kind: egress, polygon: [[600, 260], [760, 260], [760, 520], [600, 520]]}
blind_regions:
  - {id: shed_back, name: behind the shed, polygon_m: [[4.1, 9.0], [7.3, 9.0], [7.3, 11.2], [4.1, 11.2]]}
topology:
  - {from: side_left, exit: to_shed_back, to: shed_back, blind: true}
  - {from: shed_back, to: side_left, min_s: 5, max_s: 180, blind: true}
  - {from: front, to: side_left, min_s: 2, max_s: 20}
```

Zone `kind`s are `egress` (a door of the house itself), `perimeter` (where outsiders enter: street, driveway entry, side alley) and `interior_yard` (everything else). A plain polygon list is still accepted as `interior_yard`. A garage door, or any opening an outsider can reach without first appearing on a camera, is `interior_yard`, never `egress`.

**Rule**

```json
{"id": "r7", "name": "Side gate after dark",
 "target": {"kind": "protected_object", "id": "po_side_gate"},
 "trigger": "touch", "min_dwell_s": null,
 "active": {"start": "17:30", "end": "06:00"},
 "severity": "needs_attention", "applies_to": "non_household", "state": "active"}
```

`applies_to` is one of `anyone`, `external_visitor_only`, `non_household` (default `anyone`). Which roles each one fires on — `unknown` always fails closed:

| `applies_to` \ `actor_role` | `household_insider` | `expected_visitor` | `external_visitor` | `unknown` |
| --- | --- | --- | --- | --- |
| `anyone` | fires | fires | fires | fires |
| `non_household` | — | fires | fires | fires |
| `external_visitor_only` | — | — | fires | fires |

**Role, window and event additions**

```json
{"event": {"id": "e7c1a2b3d4", "type": "touch", "camera_id": "side_left", "track_id": "side_left-person-1",
           "target": "po_side_gate", "actor_role": "external_visitor"},
 "track": {"id": "side_left-person-1", "origin_zone": "side_alley"},
 "subject": {"id": "s1", "track_ids": ["side_left-person-1", "side_left-person-2"],
             "actor_role": "external_visitor", "role_basis": "perimeter:side_alley"},
 "expected_window": {"id": "w3", "label": "deliveries", "start": "2026-11-03T13:00:00-08:00",
                     "end": "2026-11-03T17:00:00-08:00", "cameras": ["front"], "state": "active"},
 "checkin": {"id": "c1", "by": "owner_session", "start": "...", "expires": "... +30 min", "bound_subject": "s4"}}
```

`actor_role` is one of `household_insider`, `expected_visitor`, `external_visitor`, `unknown`. `role_basis` is one of `egress:<zone>`, `checkin:<id>`, `window:<id>`, `perimeter:<zone>`, `group:<role>`, `gap_unresolved:<gap_id>`, `ambiguous_link:<track_id>`, `origin_null:<track_id>`. A check-in's `bound_subject` is `null` until it binds a chain. Vigil does not identify anyone and creates no face, voice or body templates: no person-related schema (appearance, tracks, subjects, events, positions) has any field NFR-003 bans (face, age, gender, skin, ethnicity, height, gait, body-measurement, voice-feature or name). Camera and object metadata such as `cameras.name` are not about people.

**Verdict function.** `compose()` is unchanged. Roles act earlier, when the floor is set:

```python
ORDER = {"normal": 0, "noteworthy": 1, "needs_attention": 2}

def compose(floor: str, unresolved_gap: bool, proposal: str | None, proposal_cited: bool) -> str:
    if floor == "needs_attention":          # only rules can set this
        return "needs_attention"
    if unresolved_gap:                      # no rule fired, subject vanished
        return "cant_confirm"
    if proposal == "noteworthy" and proposal_cited:
        return max(floor, "noteworthy", key=ORDER.get)
    return floor                            # Wonder can never lower the floor
```

How a protected-object event (`touch` or `removed`) sets the floor. A rule is *in force* for an event when its state is `active` and the event time is inside its time window.
1. A rule in force whose `applies_to` covers the event's `actor_role` fires: its severity sets the floor.
2. Rules are in force on the object, every one of them excludes the actor's role, and the role is `household_insider`: the floor stays **normal**, because the owner scoped the rule.
3. Otherwise (no rule in force on the object, or a rule in force excludes an `expected_visitor`): the floor is **noteworthy**.

The visit floor is the maximum over all its events.

**Validator checks** (`validator.py`; any failure rejects the draft)

1. Schema valid; 1 to 6 sentences.
2. Every sentence cites at least 1 event, and every cited event belongs to this visit.
3. Every clock time in a sentence is within 60 s of a cited event and outside every gap.
4. Every camera name in a sentence belongs to a cited event.
5. No banned words: gender, age, ethnicity, or judgements such as "suspicious", "intruder" or "thief". The subject is always "a person", "they", or a phrase from the role phrase list (check 7).
6. Every `gap_id` exists in this visit.
7. Role claims are backed by the ledger. `config/role_phrases.json` maps each allowed phrase to one role: "someone who came out of the house" → `household_insider` with basis `egress:<zone>` only (check-in and group subjects get no role phrase); "an expected visitor" → `expected_visitor`; "someone who arrived from outside the property" → `external_visitor`. `unknown` has no phrase. Matching is case-insensitive on whole words. A sentence containing a role phrase must cite at least one event, and every event it cites must belong to a subject holding the mapped role; a sentence about subjects with different roles fails. After the allowed phrases are removed, a sentence containing any word in `config/role_banned_words.json` (household, family, resident, owner, guest, visitor, courier, delivery, stranger, neighbour, neighbor, dad, mum, mom, son, daughter, wife, husband, ...) fails. The ledger sent to Wonder contains no person names; any capitalised token that is not sentence-initial and is not a camera, zone or object name in the ledger, a weekday, a month, or `AM`/`PM` fails.

---

## Section 9.7 — Revised timeline (Mon Nov 2 to Wed Nov 4, PT; replaces the task table)

Sunset Mon Nov 2 is **4:55 PM PT** (owner-supplied; about 4:59 PM if the house is in Los Angeles). Field tasks that need daylight come first. Software tasks whose offline code already landed in the bootstrap (Nov 2) keep their slot for **real-data acceptance only**.

| Task | Track | Done by | Depends on | Files | Done when |
| --- | --- | --- | --- | --- | --- |
| T-01 Audit repo ✓; claim credits and set the spend limit; pick track; commit EVAL.md targets | D | Mon 13:00 | none | `EVAL.md`, `HACKATHON.md` | Audit done (`docs/audit/2026-11-02-repo-audit.md`); credits claimed; $140 limit set |
| T-02 Scaffold and CI ✓ | A | done | T-01 | `pyproject.toml`, `Makefile`, `ci.yml` | CI green (commit `3d53d05`) |
| H-01 GPU probe ✓ | B | done | none | `eval/hardware/3090.json` | Ready: CUDA 13.0, about 64 TFLOPS burn, 67 °C peak |
| **Daylight block (13:00 – 16:55)** |  |  |  |  |  |
| T-04 Reolink probe; on-camera privacy masks; audio off | D | **Mon 13:45** | T-01 | `reolink/probe.py`, `config/cameras.yaml` | FR-030 passes; mask confirmed in the RTSP stream; zone `kind`s drawn (egress, perimeter) |
| T-05 Restreamer and capture service | A | Mon 14:30 | T-04 | `reolink/capture.py`, `infra/go2rtc.yaml` | Capturing before T-07a starts; 2 h test runs overnight. Fallback: NVR or camera recording export |
| T-03 Meta smoke tests; resolve the 3 open API questions (incl. Voice WAV) | B | Mon 14:30 | T-01 (credits) | `scripts/smoke_meta.py` | One recorded response per model |
| T-06 LiDAR loops; **6 landmark pairs per camera** (nominal FOV); place and survey **6 audit markers per camera**; 2 scale distances | D | **Mon 15:45** | T-04 | `data/scan/`, `data/calib/` | Exports on disk; landmarks visible in each still; marker survey sheet written |
| T-07a Film **daytime** scenarios A, B, B′ (and the other daytime benchmark scenarios) with consent; labels written before processing; audio fixtures for FR-022 recorded | D | **Mon 16:50** | T-05 | `eval/labels/` | Daytime scenarios recorded and labelled before sunset; A is filmed before B and B′, and nobody, the A actor included, crosses the front-door egress polygon from outside in the 10 min before the take: the A actor goes into the house another way, or waits 10 min (FR-008 egress voiding); 3 consented WAV fixtures in `demo/voice/`, their SHA-256 in `config/audio_fixtures.json` |
| **Night block (17:15 setup; filming after about 17:55, nautical dusk, once the cameras are in IR – 19:00)** |  |  |  |  |  |
| T-07b Film **night** scenarios A′ (front-door egress, side-gate touch after 17:30) and C (side-alley entry, gate touch, 41 s shed gap), and the other night scenarios, after dark; optional labelled take of a household member returning through the side alley without a check-in (the documented false-alert case) | D | **Mon 19:00** | T-07a | `eval/labels/` | Night scenarios recorded and labelled; r7 window 17:30–06:00 covers both A′ and C; for at least 10 min before A′, no person who did not come out of the front door is seen on the front door zone (FR-008 egress voiding), so the A′ actor goes inside at least 10 min before the take |
| T-08 Privacy, windows, motion gate on real footage | A | Mon 20:00 | T-07a | `ingest/*.py` | Offline code landed in the bootstrap; FR-003 to FR-005 pass on real footage |
| T-09 SAM concept tracking on the 5 demo scenarios | B | Mon 21:00 | T-03, T-07b | `meta/sam.py` | Real SAM tracks for A, A′, B, B′, C (API or local) |
| T-10 3D model build | C | Mon 20:00 | T-06 | `spatial/scan.py` | FR-035 passes |
| T-11 Track stitching and overlays on real tracks | A | Mon 22:00 | T-09 | `perception/*.py` | FR-007 passes on real tracks |
| T-12 Landmark tool (SAM proposals + mesh clicks) and solver | C | Mon 23:00 | T-10 | `spatial/calibrate.py`, `web/calibrate/` | FR-036 (nominal or profile) for 4 cameras |
| H-02 Local SAM 3.1 benchmark (**gate**) | B | Mon 22:00 | H-01 | `scripts/bench_sam_local.py` | Chunk settings chosen, or API fallback |
| **G1** | all | **Mon 23:00** |  |  | Footage and labels committed; SAM tracks for A, A′, B, B′, C; GLB built |
| T-13 Event builder with origin tagging (real tracks) | A | Tue 09:00 | T-11 | `perception/events.py` | FR-008 on real tracks; origins match labels |
| T-15 Audit-harness marker walk (daylight) | D | Tue 10:30 | T-06 | `eval/spatial/` | Person on 6 markers per camera, recorded |
| T-14 Extrinsics from landmarks accepted, or switch to the fallback | C | **Tue 10:00 cut-off** | T-12 | `config/calibration.json` | FR-037 passes, or the site-plan fallback is active |
| T-16 Appearance notes | B | Tue 10:00 | T-11 | `meta/spark.py` | FR-009 passes |
| T-17 Coverage and blind regions | C | Tue 11:00 | T-14 | `spatial/coverage.py` | FR-038 passes |
| T-18 Topology, visits, gaps, **roles** | B | Tue 12:00 | T-13, T-16, T-17 | `reasoning/visits.py` | FR-010, FR-011, FR-044 pass on real data |
| T-19 Position estimates | C | Tue 12:00 | T-14 | `spatial/locate.py` | FR-039 unit tests pass; audit radii applied |
| T-20 Rules (with `applies_to`), story, validator (check 7), verdict | B | Tue 13:00 | T-18 | `reasoning/*.py`, `meta/wonder.py` | FR-012, FR-014 to FR-016 pass |
| **G2** | all | **Tue 13:00** |  |  | Scenario C end to end, including 3D positions, the gap and its role |
| T-21 API, export, cards, synced player | C | Tue 15:00 | G2 | `api/`, `store/export.py`, `web/*.js` | FR-017, FR-018, FR-027 pass |
| T-22 Tap-to-protect; **voice and typed rules** (mic, 3 audio fixture buttons, typing); expected windows and owner check-in | B | Tue 16:00 | G2 | `api/routes.py`, `meta/spark.py`, `meta/asr.py` | FR-019, FR-021, FR-022, FR-029 pass |
| T-23 Triage and closed loop | B | Tue 17:00 | T-20 | `triage.py`, `loop.py` | FR-013, FR-020 pass |
| T-24 3D viewer | C | Tue 17:30 | T-21, T-19 | `web/twin/` | FR-040 passes |
| T-25 Guards (incl. judging cap) and telemetry panel | C | Tue 18:00 | T-21 | `api/guards.py`, `web/cards.js` | FR-023 UI, FR-026, FR-043 pass |
| **G3 MVP freeze** | all | **Tue 18:00** |  |  | The 5 blocking P0 CI suites (12.1) pass |
| T-26 Reolink events, live loop, LAN live view | A | Tue 21:00 | G3 | `reolink/ai_events.py`, `api/live.py` | FR-032 to FR-034 pass |
| T-27 Benchmark, audit harness, baseline, unit-economics measurements (11.9) | D | Tue 22:00 | G3, T-15 | `eval/*.py`, `EVAL.md` | Results committed, misses included; Tier 0/1 rates measured |
| T-28 Deploy sandbox with judging config (`VIGIL_ALLOW_PAID=1` from window end, `VIGIL_JUDGING_CAP_USD=25`, `VIGIL_JUDGING_END`); E2E in CI | C | Tue 23:00 | G3 | `Dockerfile`, `tests/e2e/` | Live URL passes E2E from CI; the judging cap is verified by test |
| **G4** | all | **Tue 23:00** |  |  | Evidence complete; sandbox opened on a phone |
| T-29 Record live home clip; edit video; README; HACKATHON.md | D | Wed 12:00 | G4 | `README.md`, `HACKATHON.md`, video | Video under 3:00, link tested privately |
| T-30 Final scans and submission | D | Wed 14:00 | T-29 | none | Section 13 checklist all ticked; submitted |

---

## Section 11 — renamed: "11. Meta API Credit Plan & Commercial Unit Economics"

### Section 11 intro (replace both paragraphs)

The plan spends about **$55 to $95** of the $150 credits, depending on whether local SAM passes gate H-02. That leaves at least $55 of the credits unspent (at least $45 below the **$140** hard cap on credit spend enforced in code), plus a separate $25 cap on card-paid spend during judging (11.8).

The largest risk is timing, not the amount. The Official Rules say the credits are "valid for a 10-day development window", and judging (Nov 5 to 10 PT) probably falls after it. **Decided by the owner on Nov 2: live calls stay on during judging.** `VIGIL_ALLOW_PAID=1` is set from the window end, with a hard `VIGIL_JUDGING_CAP_USD=25` ($5 per day) on post-window spend, charged to the card on file, and no paid call after `VIGIL_JUDGING_END` (Nov 10, 23:59 PT) (11.6, 11.8). Without `VIGIL_ALLOW_PAID=1`, Vigil switches to cached-only when the window ends. Before Nov 4, 9 PM ET, set `VIGIL_CREDIT_WINDOW_END` to the exact end of the credit window.

### 11.6 Safeguards

1. **Billing-page spend limit at $140**, set before T-03 and reset when the credit window ends (11.8). ⚠️ Confirm with a test whether it hard-stops calls.
2. **Budget guard in `meta/client.py`.** Every call is priced from the 11.3 table before it is sent. A call is refused if it would cross the credit cap ($140, `credit`-tagged spend only), its feature budget (11.4), or the daily cap; after the window, the judging cap (item 6) applies instead. Warnings show at 50%, 75% and 90%.
3. **Pre-flight estimate.** Batch commands (`vigil process`, `vigil eval`) print frames, tokens and cost first, and require `--confirm` above $5.
4. **Cache first.** Identical requests are never paid for twice; benchmark re-runs read the cache unless told otherwise.
5. **Model allowlist.** Only the 4 Standard-mode IDs are allowed: no `-contributor`, no web-search tool, no Muse Image.
6. **Sandbox and judging limits.**
   - **Before the credit window ends:** 10 live requests per minute per IP and $10 per day, both from the credits.
   - **During judging (Nov 5–10 PT):** live calls stay **ON**, with `VIGIL_ALLOW_PAID=1` set by the owner (approved Nov 2). A dedicated `VIGIL_JUDGING_CAP_USD=25.00` hard cap applies to post-window spend: $5 per day, still 10 requests per minute per IP. The $25 total binds before the daily caps (6 days × $5 = $30). No paid call after `VIGIL_JUDGING_END` (Nov 10, 23:59 PT).
   - **Fallback:** if a cap is reached, or a call times out after 20 s or fails, the request degrades to the cached result with the telemetry notice. A judge never sees a blank or disabled screen; they see "Live budget for today used; recorded result shown" or "Live call failed; recorded result from \<date> shown".
7. **Daily reconciliation.** Compare the ledger total with the Billing page and log both in `eval/budget.md`. A drift over 10% means updating the price table before spending more.
8. **Separate keys.** One key for development and one for the sandbox, so the public one can be revoked alone. ⚠️ Check whether per-project limits exist (the billing URL suggests projects).

### 11.7 If credits run out or expire

- **Credits expired (window ended):** with `VIGIL_ALLOW_PAID=1`, live calls continue on the card up to $5 per day and $25 in total (NFR-037); at either cap, after `VIGIL_JUDGING_END`, or with the flag unset, the sandbox serves cached results with the notice, and every flow still works (NFR-009).
- **Credits exhausted ($140 reached before the window ends):** cached results only.
- Perception runs on local SAM; triage runs on Glimmer; non-escalated stories use templates; Wonder stories for the 3 demo scenarios are already cached.
- Voice rules fall back to the 3 fixture buttons with cached transcripts, then typing.

### 11.8 Notice: decisions that could cost beyond the $150
- **Live calls during judging (Nov 5–10 PT): decided ON by the owner (Nov 2).** Calls after the credit window are charged to the card on file, up to a **hard $25 in total** ($5 per day) and never after `VIGIL_JUDGING_END` (Nov 10, 23:59 PT); the $25 total binds before the daily caps (6 days × $5 = $30). The budget guard counts this spend separately from the $140 credit cap: the ledger tags each call `credit` or `paid`, and the post-window check refuses any call that would cross $25 or the day's $5. Worst-case exposure: **$25**.
- **Before Nov 4, 9 PM ET:** confirm the credit window's exact end time in the Credit Terms and set `VIGIL_CREDIT_WINDOW_END` to it. Confirm the card on file. At the moment the credit window ends, set the Billing-page spend limit to (credit spend shown on the Billing page at window end) + $25, or to $25 if the limit counts only card charges. ⚠️ Check which one the Billing page measures before Nov 4, 9 PM ET.
- **Nothing else in this plan exceeds $150.** If T-03 shows video tokens far above the assumption, so that the projected total passes $140, this is flagged before the benchmark runs. The fallback is notes at 2 fps and 480 px, or on keyframes.

### 11.9 Commercial unit economics (new): why the edge-plus-cloud cascade wins

**Unit:** one home with 4 cameras recording 24/7, per month (30.4 days). Prices are the spec 11.3 Standard-mode prices. Token counts are the plan's assumptions until T-03 measures them, and `vigil cost estimate` recomputes this table from the measured values. **Everything below is an estimate, not a measurement.** T-27 measures the Tier 0 and Tier 1 rates on the recorded evening and publishes them in EVAL.md.

**Per-call costs (from 11.3):**
- One Spark video clip (about 30k tokens in, 0.4k out): $0.0375 + $0.0017 ≈ **$0.039**.
- One Wonder story at spec size (6k in, 0.8k out): $0.024 + $0.016 = **$0.040**.
- One Wonder story with a compact ledger (3k in, 0.5k out): $0.012 + $0.010 = **$0.022**.

| Approach | How it works | Cost per home per month | Notes |
| --- | --- | --- | --- |
| Naive continuous cloud VLM (the FR-025 baseline) | One Spark video call per motion window (W windows per day) | W × $0.039 × 30.4: **$59 at W = 50; $119 at W = 100; $356 at W = 300** | A figure of about $65–110 corresponds to W ≈ 55–93. Busier homes cost more. Not viable for a consumer subscription |
| Human-in-the-loop guard service (for example, SimpliSafe Active Guard outdoor monitoring) | Monitoring agents review outdoor camera events | **≈ $50 per month overnight only (Pro, 8 PM–6 AM); ≈ $80 per month for 24/7 (Pro Plus)**, plus the vendor's outdoor cameras (third-party reviews, Nov 2026; ⚠️ confirm on simplisafe.com before quoting) | Labour-bound, so margins are low; outdoor only |
| **Vigil three-tier cascade** | Tier 0 discards idle windows; Tier 1 resolves routine visits on the local GPU; Tier 2 calls the cloud only for escalated visits | Tier 2 at E escalated visits per day:<br>(a) compact Wonder story only: E × $0.022 → **$1.34–$2.68 at E = 2–4**<br>(b) spec-size story: **$2.43–$4.86**<br>(c) story plus 2 Spark appearance clips per visit: **$7.2–$14.3** | **(a) and (b) need Tier 1 to produce the appearance notes locally** (Glimmer on keyframes). A "~$0.06 per day" Tier 2 cost holds for (a) at E ≈ 2.7 |

**The three tiers:**
1. **Tier 0: motion gate and Reolink edge trigger ($0).** Hypothesis: about 85% of windows are idle and skipped. Measured in T-27 as the skipped-window share.
2. **Tier 1: local SAM 3.1 plus Muse Glimmer 30B on the edge GPU ($0 API).** Hypothesis: about 90% of the remaining visits resolve without the cloud. Measured as 1 − the escalation rate (FR-013).
3. **Tier 2: cloud Muse Spark and Muse Wonder.** Called only on escalated visits; the hypothesis is 2–4 per day.

**Reduction against the naive baseline at W = 100 ($119 per month):**
- Case (a): **97.7–98.9%**.
- Case (b): **95.9–98.0%**.
- Case (c): 87.9–94.0%.

The **"about 96% cloud inference cost reduction" claim holds only at W ≈ 100 or more and only when appearance notes run locally** (cases a and b; at W = 50 case b falls to about 92%). It does not hold if Spark annotates every escalated visit (case c).

**Gross margin at $14.99 per month:**

Formula: GM = 1 − (Tier 2 API + cloud hosting + payment fees) / $14.99. The cost assumptions are:
- Cloud hosting: ≈ $0.50 per home per month for cards, escalated masked clips with 30-day retention, and egress (⚠️ estimate).
- Payment fees: 2.9% + $0.30 ≈ $0.73.

| Tier 2 per month | GM including payment fees | GM excluding payment fees |
| --- | --- | --- |
| $1.01 | **85.0%** (break-even point for 85%) | 89.9% |
| $1.80 (the "$0.06 per day" case) | 79.8% | 84.7% |
| $2.68 | 73.9% | 78.8% |
| $4.86 | 59.3% | 64.2% |

**Business verdict.**
- A $14.99 per month subscription gives about **78–83% gross margin including payment fees (83–88% excluding them)** at 2–3 escalations per day, with Wonder on a compact ledger and appearance notes kept local.
- Reaching **over 85% including fees** needs Tier 2 at or below about $1.01 per month (about 1.5 escalations per day). Otherwise the price must rise: about $17.69 at E = 2, $21.49 at the "$0.06 per day" case ($1.80) and $23.19 at E = 3 (compact ledger, local notes).

**Edge-cost caveat.** These margins **exclude the edge hardware**, which the homeowner owns and powers.
- The team's RTX 3090 GPU measured about 48 W idle and 349 W under load (nvidia-smi, H-01; the whole box draws more). A 3090-class box running 24/7 costs the homeowner roughly **$15–26 per month in electricity** (80–120 W average at $0.25–0.30 per kWh; ⚠️ the average is an estimate, not measured).
- A 3090 is a development box, not the product. The commercial path assumes a low-power edge accelerator (⚠️ a hypothesis, not tested) running a smaller local triage model.
- This is the main open risk in the business case, and the README must say so.

---

## Section 12.1 — Prioritized test suites (replaces the table's framing; adds the tier column)

**Prioritized lanes (Nov 2 correction).** CI runs two lanes.
- **Blocking lane:** lint, secret scan and the 5 P0 suites. They must pass on every push from now on, and by G3 at the latest. A red P0 suite blocks the merge.
- **Report-only lane:** every other suite still runs in CI, with `continue-on-error`. Failures are visible in the run summary and EVAL, but they never block the 3D viewer, the demo bundle export or the video.

Run time stays cheap, and nothing silently rots. Field and live checks run by hand before each gate.

| Tier | Suite | Files | What it proves | Requirements |
| --- | --- | --- | --- | --- |
| **P0 blocking 1** | Privacy | `tests/unit/test_privacy.py` + `scripts/privacy_scan.py demo` + metadata scan | 0 pixels inside polygons; no audio stream in any video; no audio file anywhere in the repo except the allowlisted voice fixtures under `demo/voice/`; no GPS or device metadata | FR-003, NFR-001, NFR-002, NFR-032 |
| **P0 blocking 2** | Citation validator | `tests/unit/test_validator.py` | Planted failures caught, incl. role claims (check 7) | FR-015, NFR-003 |
| **P0 blocking 3** | Verdict and rules (with roles) | `tests/unit/test_verdict.py`, `tests/unit/test_rules.py` | Every floor × gap × proposal combination; every `applies_to` × `actor_role` pair, `household_insider` vs `external_visitor`, `unknown` fails closed; midnight windows | FR-012, FR-016, FR-044 |
| **P0 blocking 4** | Guards and budget | `tests/integration/test_guards.py` (+ `tests/unit/test_budget.py`) | Spend caps, the $25 judging cap, rate limit 429, size limit 413, no contributor IDs, key never served | FR-026, FR-043, NFR-004, NFR-013 to NFR-015, NFR-037 |
| **P0 blocking 5** | Judge path E2E | `tests/e2e/test_judge_path.py` against the Docker sandbox | The 8 judge steps incl. voice fixture buttons and the cached fallback with an invalid key | FR-017, FR-018, FR-022, FR-027, FR-040, NFR-009, NFR-018, NFR-022 |
| P1 report-only | Config, ingest, perception, Meta client faults, visits/gaps/roles, story, loop, spatial, golden pipeline, determinism, Reolink, mobile E2E, eval metrics | all other files under `tests/` | As listed in the original 12.1 table | FR-001 to FR-044 (others), NFR-010, NFR-011, NFR-017 |
| P2 report-only | Performance | `tests/e2e/test_perf.py` | First card under 2.5 s; GLB load | NFR-005, NFR-030 |
| Manual (by gate) | Live smoke, live latency, field calibration and audit harness, capture endurance, exposure check, benchmark | as in the original 12.1 table | Real-data acceptance | as listed |

Definition of done (12.3) is unchanged, except that "CI green" means the blocking lane is green. Any report-only red has an open issue.

## Section 12.2 — CI pipeline (replaces the step list)

1. ruff lint and format check (blocking).
2. gitleaks secret scan (blocking; NFR-014).
3. Blocking P0 suites 1–4: `pytest -m "not live" tests/unit/test_privacy.py tests/unit/test_validator.py tests/unit/test_verdict.py tests/unit/test_rules.py tests/unit/test_budget.py tests/integration/test_guards.py`.
4. Privacy scan and exiftool metadata scan over `demo/`, plus a repository-wide audio check over `git ls-files` against `config/audio_fixtures.json` (blocking; part of P0 suite 1).
5. Report-only: every other unit, property and integration test (`pytest -m "not live"` minus the files in step 3), `continue-on-error: true`.
6. Report-only: determinism check (pipeline twice, diff).
7. Build the Docker image; start it with `VIGIL_MODE=sandbox` and an invalid key (blocking).
8. Blocking P0 suite 5: `tests/e2e/test_judge_path.py` against the container, offline. Report-only: `test_mobile.py`, `test_perf.py`.
9. Upload Playwright traces and screenshots as artifacts. These double as demo evidence.

---

## Review corrections (Nov 2)

After the six corrections were applied, three adversarial reviews read the spec: economics (18 findings), consistency (33) and role logic (16). Every finding was accepted. Where findings overlapped, one resolution was chosen and applied once. The blocks above already contain the results; this section lists what changed.

### Economics

- **Gross margin at $14.99:** about **78–83% including payment fees (83–88% excluding them)** at 2–3 escalations per day, compact ledger, local notes (was "80–85%").
- **Over 85% including fees** needs Tier 2 ≤ about **$1.01 per month** (E ≈ 1.5), or a price of about **$17.69** at E = 2, **$21.49** at $1.80 per month and **$23.19** at E = 3 (was "$1.00 or $17.99").
- **Break-even row** for 85% is **$1.01** (85.0%, 89.9% excluding fees); $1.02 gives 84.96%.
- **Rounding:** $65–110 maps to W ≈ 55–93; case (c) reduction is 87.9–94.0%; the $4.86 row is 59.3% / 64.2%.
- **"About 96%" reduction** holds only at W ≈ 100 or more with local notes; at W = 50, case (b) is about 92%.
- **Electricity:** **$15–26 per month** (80–120 W at $0.25–0.30 per kWh; average estimated). The 48 W / 349 W figures are GPU board power from nvidia-smi, not the whole box.
- **SimpliSafe row:** ≈ $50 per month overnight only (Pro, 8 PM–6 AM), ≈ $80 per month 24/7 (Pro Plus), plus the vendor's outdoor cameras. ⚠️ Confirm on simplisafe.com before quoting.
- **Credit cap vs judging spend:** NFR-036 and safeguard 2 now count `credit`-tagged spend only; post-window `paid` spend falls under NFR-037. 9.3 `model_calls` gains `funding` (`credit` | `paid`) next to `backend`, `gpu_s` and `feature`.
- **Judging end:** `VIGIL_JUDGING_END` = Nov 10, 23:59 PT. No paid call after it. Post-window spend ≤ $25 in total and ≤ $5 per PT day; 6 days × $5 = $30, so the $25 total binds first. FR-043 adds the end date and a refusal test.
- **Billing-page second stop:** at window end, set the limit to (credit spend at window end) + $25, or $25 if it counts card charges only. ⚠️ Check which before Nov 4, 9 PM ET. Replaces the "$165" suggestion.
- **Budget tables:** 11.4 adds rows for judging spend (up to $25, card) and live home testing through the API (up to $15); voice is FR-022 P0 at under $0.20. 11.5 adds the judging row; worst-case out of pocket is $25. The 108,000-frame line shows its assumption (75 s active per scenario).
- **NFR-012** allows under $40 including the baseline if API SAM is needed (H-02 fails). **NFR-013** names both caps. The section 11 intro states the decision, Nov 5–10, and a reserve of at least $55 of credits.
- **Sunset:** kept at 4:55 PM PT (owner-supplied; about 4:59 PM if the house is in Los Angeles). Night filming starts after about 17:55 (nautical dusk, cameras in IR).

### Consistency

- **A′ moved to the night block (T-07b):** front-door egress straight to the side gate inside r7's window, touch, back inside. T-07a films A, B, B′. The A′ vs C contrast is now decided by `applies_to`, not by r7's time window.
- **Diagrams:** 5.6 shows transcribe, then edit, then compile, with the fixture buttons and a non-household 17:30–06:00 draft; 5.12 shows the product path (nominal FOV, SAM landmarks, 6-landmark PnP) and the separate audit harness; 5.2 lists 4 kinds of live call; 5.11 names the judging settings; the section 10 diagram shows credits then card; 5.1 adds spoken-rule audio to what reaches Meta; 5.5 exempts the case-2 household touch from forced escalation. `docs/architecture/` matches.
- **Audio (NFR-002):** camera audio never leaves the house or enters the repo; voice-rule speech goes only to Voice Transcribe and is never stored (only the transcript is cached, keyed by the audio hash); the only repo audio is the 3 consented fixtures in `demo/voice/`, listed by SHA-256 in `config/audio_fixtures.json`; a repository-wide check (`git ls-files`) fails on any other audio file, and P0 suite 1 proves it.
- **HTTP API (9.6):** adds `POST /api/voice/transcribe`, `GET /api/voice/fixtures`, expected-window CRUD, `POST /api/checkin`, visit feedback and `POST /api/spatial/landmarks`; compile takes edited text and has a cached preset; health reports the judging cap.
- **Schema (9.3):** `tracks.origin_zone`, a `subjects` table, `events.subject_id` and `actor_role`, `expected_windows`, `checkins` (with `bound_subject`), `rules.applies_to`, `model_calls.funding`.
- **Interfaces (9.5):** `transcribe`, `propose_landmarks`, `origin_zone`, `intrinsics_from_fov`, `audit_error`, `assign_roles`.
- **Traceability (13.1):** rows for FR-044, FR-029, FR-022 and FR-037; FR-043 row names the judging cap.
- **CI (12.2):** steps line up with the lanes; the blocking lane is lint, secret scan and the 5 P0 suites. 12.1's catalogue covers origins, roles, check 7, nominal-FOV intrinsics, the judging cap, voice fixtures and expected windows.
- **Cap behaviour:** one notice everywhere ("Live budget for today used; recorded result shown"); buttons stay active and serve the cached result. 11.7 distinguishes expired from exhausted credits.
- **Smaller fixes:** FR-022 downsamples to 16 kHz mono WAV (30 s ≈ 0.96 MB) and no longer states the endpoint as fact; 5.14 reports FR-022 as missed (not "typed rules") if neither transcribe path works; section 0 counts 4 models if H-03 fails and says the sandbox triages with Spark; FR-027 and step 1 cover 5 scenarios; demo labels show measured r95, not "±0.4 m"; step 4 of positioning uses the audit error where measured, otherwise the landmark error, plus the `fov_nominal` radial term; 10.3 calibration row; 9.1 adds `demo/voice/` and the role config files; stale 13 / 13.2 summaries; FR-012's default rule wording; UC-09 and the fallbacks table cover voice; 13.5 checks the judging env and the README limits.

### Role logic

- **Check-in (FR-044 step 2, FR-029, T-22):** single-use and never retroactive. When the 120 s after the tap closes, it binds the one chain that started in that interval with origin `null` or `perimeter`, only if exactly one started and nobody but `household_insider` was in view; otherwise nothing. Basis `checkin:<id>`; an unused check-in expires after 30 min.
- **Carry across blind spots:** `external_visitor` carries on any unambiguous re-link; `household_insider` and `expected_visitor` carry only when at least one non-`unknown` appearance attribute matches. A transit-time-only re-link gives `unknown` (basis `gap_unresolved:<gap_id>`). Section 0 no longer says "stays in continuous view".
- **Egress origin (FR-008):** majority foot point in the first 10 frames; `null` unless the camera observed without interruption for the 2 s before; voided if a non-egress person track was last seen on the dilated egress polygon within 10 min. Garage doors are `interior_yard`, never `egress`.
- **Expected windows (FR-044 step 3):** scoped by cameras or zones; only perimeter origins qualify; a `null` origin is never `expected_visitor`. FR-044 still passes if FR-029 is not built.
- **Group rule:** household members walking together on a non-blind edge keep their shared role (basis `group:<role>`).
- **`role_basis` values:** `egress:<zone>`, `checkin:<id>`, `window:<id>`, `perimeter:<zone>`, `group:<role>`, `gap_unresolved:<gap_id>`, `ambiguous_link:<track_id>`, `origin_null:<track_id>`.
- **Touch floor (9.4):** a rule is *in force* when active and inside its time window; case 2 (normal) applies only to `household_insider`; an `expected_visitor` excluded by a scoped rule gets noteworthy; covers `touch` and `removed`; the visit floor is the maximum over its events. FR-013 no longer forces escalation for a case-2 household touch. FR-008 emits one event per overlapping track.
- **Validator checks 5 and 7:** `config/role_phrases.json` maps "someone who came out of the house", "an expected visitor" and "someone who arrived from outside the property" to their roles (`unknown` has none); every cited event must hold the mapped role; `config/role_banned_words.json` and a capitalised-token test reject other role words and names.
- **Draft card and notices:** household only when seen coming out of the house's own doors or checked in just before coming into view; household members arriving from the street without a check-in, and anyone Vigil loses track of, count as non-household. The named-person notice says the same.
- **Biometrics wording:** everywhere the claim is "Vigil does not identify anyone and creates no face, voice or body templates"; no statute is cited. NFR-003 covers the appearance, track, subject, event and position schemas (face, age, gender, skin, ethnicity, height, gait, body-measurement, voice-feature, name).
- **Risks and measurement:** 13.3 lists the High-likelihood false alert (household member home from the street without a check-in) and the Low-likelihood missed alert (unobserved entry, then a door). FR-044 acceptance and the 12.1 benchmark row pre-register the **role miss rate** (assigned vs labelled role per subject, day and night separately, and the alerts it caused) for EVAL.md. T-07b adds an optional labelled take of that false-alert case.

### Second review pass

A verifier re-read the result and found 12 open or new problems; all were fixed in the spec and in the blocks above.

- **Economics:** the "~$0.06 per day" Tier 2 cost corresponds to E ≈ 2.7 escalations per day ($0.06 × 30.4 = $1.82 per month; $1.82 / 30.4 / $0.022 ≈ 2.7), not E ≈ 3 ($2.01 per month).
- **Consistency:** 5.1 text and diagram add spoken-rule audio (FR-022, transcribed and never stored) to what reaches Meta; diagram 5.5 exempts a 9.4 case-2 household touch from forced escalation (spec, `.mmd` and README copies); T-09 and G1 produce SAM tracks for all 5 scenarios (A, A′, B, B′, C); the two-camera label shows the measured r95 instead of ±0.2 m; the fallbacks table uses the same live-failure notice as UC-09 and 11.6 ("Live call failed; recorded result from \<date> shown"); FR-022 marks WAV input as to be confirmed in T-03; NFR-002 and P0 suite 1 check audio repository-wide (`git ls-files`), and T-07a records the fixture hashes in `config/audio_fixtures.json`.
- **Role logic:** validator check 7's name test also allows `AM`/`PM`, so a story with a clock time is not rejected; T-07a and T-07b keep the front door zone clear of non-egress people for 10 min before A and A′ (FR-008 egress voiding), with A filmed before B and B′; FR-044 step 5's `origin_null` basis also covers an `interior_yard` origin; the 9.4 note lists every field NFR-003 bans.
