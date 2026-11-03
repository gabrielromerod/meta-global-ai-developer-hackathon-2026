# Demo happy path

Condensed from [spec section 4](spec/vigil-spec.md#4-demo-happy-path). A judge can verify Vigil's claims in about 4 minutes: the sandbox opens on one recorded evening and walks from the summary to the evidence, then 3 live actions prove the models really run. The video (under 3:00) follows the same path and is recorded from the deployed sandbox, so the video and the product match.

## The recorded evening

One evening on the 4 home Reolink cameras (front entrance, left side, right side, backyard), recorded through Vigil's capture service and placed in the LiDAR model of the house. Details: [spec, The recorded evening](spec/vigil-spec.md#the-recorded-evening).

| Scenario | What happens | Expected verdict | Expected evidence |
| --- | --- | --- | --- |
| A Routine | A household member leaves by the front door, gets in the car, drives off | Normal, no alert | Templated story; escalated: no |
| B Delivery | A courier leaves a box on the porch | Noteworthy | Wonder story; watch "package on porch" activated by the loop |
| C Night | 22:14, a person touches the protected side gate, goes behind the shed, reappears 41 s later, leaves | Needs your attention | Rule r7 fired; gap g4 of 41 s; validator log shows a rejected draft if one occurred |

People filmed are consenting adults from the team; vehicles show plates covered by paper signs reading "VIGIL-01"; privacy polygons cover the street and neighbouring houses.

## Judge sequence (8 steps)

Full table with AI processing per step: [spec, Judge sequence](spec/vigil-spec.md#judge-sequence).

| Step | Time | Judge does | System responds | Visible proof |
| --- | --- | --- | --- | --- |
| 1 | 0:00 | Opens the URL | 3D house, 4 camera cones, coverage; summary "N motion triggers → 3 visits → 1 alert" with N measured | Real home cameras; measured blind regions; Cached badge |
| 2 | 0:20 | Opens red card C | 3D view moves to the side yard: solid path, discs with rings, dotted "Not observed · 41 s"; story with citation chips | Gap drawn as a gap; gap sentence written by code |
| 3 | 0:50 | Clicks a citation chip | Players seek; side camera highlighted with the SAM outline; matching disc lights up "Estimated ±0.4 m from Side camera" | Seen versus estimated side by side; model and call IDs |
| 4 | 1:15 | Opens "How this was decided" | Rule r7 fired, triage forced, Wonder draft, validator results, verdict inputs, calibration figures | Code decides; any rejected sentence visible |
| 5 | 1:45 | Taps the recycling bin, clicks Run live | Mask on the still and its footprint in 3D, with latency and cost | Live badge, measured ms, $ cost |
| 6 | 2:15 | Types "tell me if anyone touches the bin after 9 PM" | Draft rule card, then active rule | Rule JSON; identity disclaimer when relevant |
| 7 | 2:45 | On card C clicks Re-run story live | New wording, same verdict, citations still valid | Cached and live side by side; validator result |
| 8 | 3:15 | Opens the Benchmark tab | EVAL table, calibration and 3D accuracy, Reolink-versus-SAM agreement, naive baseline, cost per scenario | Pre-registration commit date and link |

The live home mode (UC-11) cannot be offered to judges without exposing the house, so it appears only in the video, with the measured lag on screen.

## Fallbacks

| Failure | Fallback the judge sees |
| --- | --- |
| Meta API down, slow (over 20 s) or 429 | "Live call failed: showing the recorded result from \<date>" with the cached output; telemetry shows the error |
| Spend cap reached | Live buttons greyed with "Daily live budget used; recorded results shown" |
| Mask wrong on a live tap | "Try another point" plus 3 preset points known to work |
| Wonder re-run fails validation twice | Templated story plus the validator log, itself proof of the design |
| 3D view too slow or WebGL unavailable | Top-down 2D map from the same data (cones, discs, gaps) |
| Video fails to load on a slow connection | Still frames with overlays, plus a 480p version |
| Host down during judging | README links a 90-second screen recording of the same sequence plus local `make demo` instructions |

## Evidence per criterion

| Criterion (weight) | Evidence in the demo | Steps |
| --- | --- | --- |
| Impact (30%) | Real home cameras; summary counts; one alert instead of many; a quiet Normal card; the house in 3D | 1, 2 |
| Use of Meta AI tooling (25%) | SAM outlines turned into 3D positions; live mask projected into 3D; Spark referring to SAM's tags; Wonder story; Wonder adding a SAM watch | 3, 5, 6; card B |
| Technical depth (20%) | Calibration with held-out error; truthful uncertainty radii; gaps from measured coverage; validator log; benchmark with baseline | 2, 4, 7, 8 |
| Demo (25%) | Works with no setup; live calls with telemetry; graceful fallbacks; live home mode in the video | Whole sequence and video |

## Rehearsal checklist

Run this before each gate from G3 onward, and once more before recording the video. Log the date and result of each run in the PR or commit message, and any measured number in [EVAL.md](../EVAL.md).

**Environment**

- [ ] Fresh private browser window on a laptop, and separately on a phone (390 px wide)
- [ ] Sandbox URL loads; Cached badge visible; `GET /api/health` shows mode, spend today and cap
- [ ] Spend today is below the daily cap ($10) with headroom for the 3 live steps
- [ ] Offline E2E suite (`MODEL_API_KEY=invalid`) is green on the current build

**Walk the 8 steps with a stopwatch**

- [ ] Step 1: cones, coverage and blind regions render; summary shows a measured N
- [ ] Step 2: card C opens; dotted "Not observed · 41 s" visible; no positions drawn inside the gap
- [ ] Step 3: every citation chip seeks all players (within 0.2 s) and lights the matching disc
- [ ] Step 4: trace shows rule r7, forced triage, validator results and calibration figures
- [ ] Step 5: live tap on the recycling bin returns a mask with latency and cost; preset points work if it misses
- [ ] Step 6: typed rule compiles to a draft card; an identity phrasing shows the disclaimer
- [ ] Step 7: live re-run gives the same verdict with valid citations
- [ ] Step 8: Benchmark tab shows the EVAL table with the pre-registration commit link
- [ ] Total time about 4 minutes

**Fallback drills**

- [ ] Invalid key: each live button shows "Live call failed: showing the recorded result"
- [ ] Spend cap forced low: live buttons grey out with the budget notice
- [ ] WebGL disabled: the 2D map appears with the same data
- [ ] Throttled network: still frames and the 480p video load
- [ ] 90-second screen recording link in the README works in a private window

**Privacy before any recording or export**

- [ ] Privacy scan, metadata scan and gitleaks clean
- [ ] No house number, street-facing frame, plate or neighbour visible; plates show "VIGIL-01"
- [ ] Live LAN mode off on the edge machine after recording (cellular port check passed)
