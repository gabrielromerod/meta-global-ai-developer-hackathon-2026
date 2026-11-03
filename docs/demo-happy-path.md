# Demo happy path

Condensed from [spec section 4](spec/vigil-spec.md#4-demo-happy-path). A judge can verify Vigil's claims in about 4 minutes: the sandbox opens on one recorded evening and walks from the summary to the evidence, then 3 live actions prove the models really run. Live calls stay on through judging (Nov 5–10 PT) under a $25 hard cap; past it, every live button serves the recorded result with a notice. The video (under 3:00) follows the same path and is recorded from the deployed sandbox.

## The recorded evening: 5 scenarios

One evening on the 4 home Reolink cameras (front entrance, left side, right side, backyard), recorded through Vigil's capture service and placed in the LiDAR model of the house. Daylight takes are filmed in T-07a (before 16:55 PT sunset), night takes in T-07b (after about 17:55, cameras in IR). Details: [spec, The recorded evening](spec/vigil-spec.md#the-recorded-evening).

| Scenario | What happens | Expected verdict | Expected evidence |
| --- | --- | --- | --- |
| A Routine (daylight) | A household member walks **out of the front door** (`front_door_egress`), gets in the car and drives off | Normal, no alert | Role `household_insider` (basis `egress:front_door_egress`); templated story; escalated: no |
| A′ Household at the gate (night) | Inside r7's 17:30–06:00 window, before C: a household member walks out of the front door, straight to the side gate (front → side_left within 2–20 s), touches it and goes back inside | Normal, no alert | Role `household_insider`; r7 in force but not fired because it applies to `non_household`; the trace shows the exclusion |
| B Delivery (daylight) | A courier arrives from the street (`driveway_entry`) and leaves a box on the porch | Noteworthy | Role `external_visitor`; Wonder story; watch "package on porch" activated by the loop |
| B′ Expected delivery (daylight) | The same, inside an owner-set delivery window | Normal or Noteworthy, depending on the loop | Role `expected_visitor` (basis `window:<id>`); the card names the window |
| C After dark (night, about 18:00 PT) | A person enters from the **side alley** (`side_alley`), touches the protected side gate, goes behind the shed, reappears 41 s later and leaves | Needs your attention | Role `external_visitor` (basis `perimeter:side_alley`), carried across the gap because the re-link was unambiguous; rule r7 "Side gate after dark" (17:30–06:00, `non_household`) fired; gap g4 of 41 s; validator log |

**A′ versus C carries the Impact claim.** The same touch of the same gate, after dark and inside r7's window, has opposite outcomes, decided only by where each person came from. Each card's trace shows the `role_basis`. Vigil identifies no one: a household member who arrives from the street without checking in counts as non-household and can trigger r7.

**Timestamps are never altered.** C is filmed at about 18:00 PT, so r7's window is 17:30–06:00 and the card shows the real recorded time (the earlier "22:14" label is retired).

People filmed are consenting adults from the team; vehicles show plates covered by paper signs reading "VIGIL-01"; privacy polygons cover the street and neighbouring houses.

## Judge sequence (8 steps)

Full table with AI processing per step: [spec, Judge sequence](spec/vigil-spec.md#judge-sequence).

| Step | Time | Judge does | System responds | Visible proof |
| --- | --- | --- | --- | --- |
| 1 | 0:00 | Opens the URL | 3D house, 4 camera cones, coverage; summary "N motion triggers → V visits → 1 alert", with N and V measured | Real home cameras; measured blind regions; Cached badge |
| 2 | 0:20 | Opens red card C | 3D view moves to the side yard: solid path, discs with rings, dotted "Not observed · 41 s"; story with citation chips | Gap drawn as a gap; gap sentence written by code |
| 3 | 0:50 | Clicks a citation chip | Players seek; side camera highlighted with the SAM outline; the matching disc lights up "Estimated ±\<r95> m from Side camera" (r95 measured by the audit harness) | Seen versus estimated side by side; model and call IDs |
| 4 | 1:15 | Opens "How this was decided" | Rule r7 fired, triage forced, `role_basis` per subject, Wonder draft, validator results (incl. check 7), verdict inputs, calibration figures | Code decides; any rejected sentence visible |
| 5 | 1:45 | Taps the recycling bin, clicks Run live | Mask on the still and its footprint in 3D, with latency and cost | Live badge, measured ms, $ cost |
| 6 | 2:15 | Holds the mic and says *"Tell me if anyone except family touches the bin after 9 PM"*, or taps one of the **3 sample-audio buttons**, or types it | Editable transcript → draft rule card: the bin, touch, 21:00–06:00, **applies to: non-household**, with the plain-words basis note → confirm → active rule | Transcript and rule JSON side by side; model and call IDs; latency and cost; "no face, voice or body templates" note. Offline: cached transcript and compile, labelled "recorded result" |
| 7 | 2:45 | On card C clicks Re-run story live | New wording, same verdict, citations still valid | Cached and live side by side; validator result |
| 8 | 3:15 | Opens the Benchmark tab | EVAL table (incl. role miss rate), calibration and audit-harness accuracy, Reolink-versus-SAM agreement, naive baseline, cost per scenario | Pre-registration commit date and link |

Step 6 uses two live calls: Muse Voice Transcribe 1.0 (16 kHz mono WAV, encoded in the browser), then Muse Spark 1.3 compiling the edited text. The 3 sample-audio buttons (`vf_family_bin`, `vf_strangers_gate`, `vf_named_gate`) need the consented WAVs from T-07a; until they are listed in `config/audio_fixtures.json`, each button serves its cached transcript.

The live home mode (UC-11) cannot be offered to judges without exposing the house, so it appears only in the video, with the measured lag on screen.

## Fallbacks

The first three notices are the spec's wording and are the strings in `vigil/api/guards.py`.

| Failure | Fallback the judge sees |
| --- | --- |
| Meta API down, slow (over 20 s) or 429 | "Live call failed; recorded result from \<date> shown" with the cached output; telemetry shows the error |
| Spend cap reached (daily, or the $25 judging cap) | "Live budget for today used; recorded result shown", with the cached output; buttons stay active |
| No key configured on the server | "Live calls are not configured on this server; recorded result shown" |
| No microphone, or transcription fails | 3 sample-audio buttons with cached transcripts; the editable transcript; typing. A button whose WAV is not recorded yet shows "This sample's audio is not in this build yet; recorded result shown" |
| Mask wrong on a live tap | "Try another point" plus 3 preset points known to work |
| Wonder re-run fails validation twice | Templated story plus the validator log, itself proof of the design |
| 3D view too slow or WebGL unavailable | Top-down 2D map from the same data (cones, discs, gaps) |
| Video fails to load on a slow connection | Still frames with overlays, plus a 480p version |
| Host down during judging | README links a 90-second screen recording of the same sequence plus local `make demo` instructions |

## Evidence per criterion

| Criterion (weight) | Evidence in the demo | Steps |
| --- | --- | --- |
| Impact (30%) | Real home cameras; summary counts; one alert instead of many; A′ versus C decided by spatial origin; a quiet Normal card; the house in 3D | 1, 2, cards A′ and C |
| Use of Meta AI tooling (25%) | 5-model loop: SAM outlines turned into 3D positions and calibration landmarks; Spark referring to SAM's tags and compiling rules; Wonder story and SAM watch; Voice Transcribe rules; Glimmer triage badges (if H-03 passes) | 3, 5, 6; card B |
| Technical depth (20%) | Audit-harness calibration error; truthful uncertainty radii; gaps from measured coverage; fail-closed roles with `role_basis`; validator log incl. check 7; benchmark with baseline | 2, 4, 7, 8 |
| Demo (25%) | Works with no setup; live calls through judging under the $25 cap; graceful fallbacks; voice with 1-click audio fixtures; live home mode in the video | Whole sequence and video |

## Rehearsal checklist

Run this before each gate from G3 onward, and once more before recording the video. Log the date and result of each run in the PR or commit message, and any measured number in [EVAL.md](../EVAL.md).

**Environment**

- [ ] Fresh private browser window on a laptop, and separately on a phone (390 px wide)
- [ ] Sandbox URL loads; Cached badge visible; `GET /api/health` shows mode, spend today and the cap in force (the $10 credit cap before the window ends, the $25 / $5-per-day judging cap after)
- [ ] Spend today leaves headroom for steps 5 to 7
- [ ] Offline E2E suite (`MODEL_API_KEY=invalid`) is green on the current build

**Walk the 8 steps with a stopwatch**

- [ ] Step 1: cones, coverage and blind regions render; summary shows measured N and V
- [ ] Step 2: card C opens; dotted "Not observed · 41 s" visible; no positions drawn inside the gap
- [ ] Step 3: every citation chip seeks all players (within 0.2 s) and lights the matching disc with a measured r95
- [ ] Step 4: trace shows rule r7, forced triage, `role_basis`, validator results and calibration figures
- [ ] Cards A′ and C: same gate touch, opposite outcomes; A′ shows r7 excluded by `applies_to`
- [ ] Step 5: live tap on the recycling bin returns a mask with latency and cost; preset points work if it misses
- [ ] Step 6: mic, each of the 3 sample-audio buttons, and typing all give an editable transcript and a draft with `applies_to`; the named-person phrasing shows "Vigil can't recognise individuals"
- [ ] Step 7: live re-run gives the same verdict with valid citations
- [ ] Step 8: Benchmark tab shows the EVAL table with the pre-registration commit link
- [ ] Total time about 4 minutes

**Fallback drills**

- [ ] Invalid key: each live button shows the recorded result with its notice
- [ ] Cap forced low: live buttons stay active and show "Live budget for today used; recorded result shown"
- [ ] No microphone permission: sample-audio buttons and typing still work
- [ ] WebGL disabled: the 2D map appears with the same data
- [ ] Throttled network: still frames and the 480p video load
- [ ] 90-second screen recording link in the README works in a private window

**Privacy before any recording or export**

- [ ] Privacy scan, metadata scan, repository-wide audio check and gitleaks clean
- [ ] No house number, street-facing frame, plate or neighbour visible; plates show "VIGIL-01"
- [ ] Live LAN mode off on the edge machine after recording (cellular port check passed)
