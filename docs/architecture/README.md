# Architecture diagrams

Every Mermaid diagram in the specification, extracted verbatim into its own `.mmd` file and embedded below with an explanation and the files it maps to. Source sections: [spec 5](../spec/vigil-spec.md#5-technical-architecture) (5.1 to 5.13) and [spec 10](../spec/vigil-spec.md#10-compute-plan-rtx-3090-first-dgx-spark-only-if-a-gate-fails). There are **14 diagrams**.

Vigil is a fixed pipeline: Meta models perceive and write; Vigil's code links, checks and decides.

## Validation

Each `.mmd` file was compiled with Mermaid CLI 11.17.1 on 2026-11-02, rendering to a temporary directory outside the repo:

```sh
npx -y @mermaid-js/mermaid-cli@11 -i docs/architecture/<name>.mmd -o docs/architecture/rendered/<name>.svg
```

`docs/architecture/rendered/` is gitignored; render locally when you need the SVGs. Keep the `.mmd` files and the blocks below identical; if a diagram changes, change the spec first.

| # | File | Spec section | Compiles |
| --- | --- | --- | --- |
| 1 | [5.1-c4-context.mmd](5.1-c4-context.mmd) | [5.1](../spec/vigil-spec.md#51-c4-level-1-system-context) | Pass |
| 2 | [5.2-c4-containers.mmd](5.2-c4-containers.mmd) | [5.2](../spec/vigil-spec.md#52-c4-level-2-containers) | Pass |
| 3 | [5.3-c4-components.mmd](5.3-c4-components.mmd) | [5.3](../spec/vigil-spec.md#53-c4-level-3-components-of-the-vigil-package) | Pass |
| 4 | [5.4-seq-process-window.mmd](5.4-seq-process-window.mmd) | [5.4](../spec/vigil-spec.md#54-sequence-processing-one-window) | Pass |
| 5 | [5.5-seq-story-validation-verdict.mmd](5.5-seq-story-validation-verdict.mmd) | [5.5](../spec/vigil-spec.md#55-sequence-story-validation-and-verdict) | Pass |
| 6 | [5.6-seq-tap-to-protect-voice-rule.mmd](5.6-seq-tap-to-protect-voice-rule.mmd) | [5.6](../spec/vigil-spec.md#56-sequence-tap-to-protect-and-voice-rule) | Pass |
| 7 | [5.7-seq-closed-loop.mmd](5.7-seq-closed-loop.mmd) | [5.7](../spec/vigil-spec.md#57-sequence-the-closed-loop-wonder-steers-sam-31) | Pass |
| 8 | [5.8-data-flow-privacy-boundary.mmd](5.8-data-flow-privacy-boundary.mmd) | [5.8](../spec/vigil-spec.md#58-data-flow-and-ai-inference-pipeline-with-the-privacy-boundary) | Pass |
| 9 | [5.9-state-visit-lifecycle.mmd](5.9-state-visit-lifecycle.mmd) | [5.9](../spec/vigil-spec.md#59-state-machine-visit-lifecycle) | Pass |
| 10 | [5.10-state-rules-watches.mmd](5.10-state-rules-watches.mmd) | [5.10](../spec/vigil-spec.md#510-state-machines-rules-and-watches) | Pass |
| 11 | [5.11-deployment.mmd](5.11-deployment.mmd) | [5.11](../spec/vigil-spec.md#511-deployment) | Pass |
| 12 | [5.12-spatial-build-calibration.mmd](5.12-spatial-build-calibration.mmd) | [5.12](../spec/vigil-spec.md#512-spatial-build-and-calibration-pipeline) | Pass |
| 13 | [5.13-seq-live-home-mode.mmd](5.13-seq-live-home-mode.mmd) | [5.13](../spec/vigil-spec.md#513-sequence-live-near-real-time-mode-at-home) | Pass |
| 14 | [10-compute-plan.mmd](10-compute-plan.mmd) | [10](../spec/vigil-spec.md#10-compute-plan-rtx-3090-first-dgx-spark-only-if-a-gate-fails) | Pass |

## 5.1 C4 level 1: system context

Source: [5.1-c4-context.mmd](5.1-c4-context.mmd) · [spec section](../spec/vigil-spec.md#51-c4-level-1-system-context)

```mermaid
flowchart LR
  owner["Homeowner<br/>[Person]<br/>live view on home network, rules, visit cards"]
  judge["Judge<br/>[Person]<br/>opens the hosted sandbox"]
  cams["4 Reolink cameras<br/>[External system]<br/>front, left side, right side, backyard<br/>RTSP streams + on-camera AI events"]
  phone["iPhone Pro LiDAR scan<br/>[External input]<br/>4 scan segments, GLB or PLY"]
  vigil["Vigil<br/>[Software system]<br/>one cited story per visit,<br/>placed in a 3D model of the house"]
  meta["Meta Model API<br/>[External system]<br/>sam-3.1, muse-spark-1.3,<br/>muse-wonder-1.0, muse-voice-transcribe-1.0"]
  cams -->|"video and AI events, home network only"| vigil
  phone -->|"one-time scan export"| vigil
  owner -->|"taps, rules"| vigil
  vigil -->|"live view, 3D view, visit cards"| owner
  judge -->|"recorded footage + live model calls"| vigil
  vigil -->|"masked, audio-free clips, event JSON,<br/>spoken-rule audio (FR-022)"| meta
```

Vigil as one software system between its people (homeowner, judge) and its external systems (4 Reolink cameras, a one-time iPhone LiDAR scan, the Meta Model API). The key boundary: raw video stays at home, and only masked, audio-free clips, event JSON and spoken-rule audio (FR-022, transcribed and never stored) reach Meta.

**Maps to:** `vigil/` as a whole; `config/cameras.yaml`; `vigil/meta/client.py` (the only path to Meta)

## 5.2 C4 level 2: containers

Source: [5.2-c4-containers.mmd](5.2-c4-containers.mmd) · [spec section](../spec/vigil-spec.md#52-c4-level-2-containers)

```mermaid
flowchart TB
  subgraph home["Home edge: the team PC on the home network"]
    rs["Restreamer<br/>[go2rtc]<br/>one connection per camera, WebRTC for the LAN app"]
    cap["Capture service<br/>[Python, ffmpeg]<br/>10 s segments, audio removed, 48 h ring"]
    evt["Reolink events<br/>[reolink_aio, TCP push]<br/>person and vehicle per camera"]
    pipe["Pipeline worker<br/>[Python package vigil]<br/>privacy, SAM, events, visits, 3D positions, rules, story"]
    spat["Spatial tools<br/>[Python, Open3D, OpenCV]<br/>scan build, calibration, coverage"]
    lan["LAN app<br/>[FastAPI + static web + three.js]<br/>live view, 3D view, cards"]
    db[("SQLite + masked windows + GLB")]
  end
  subgraph cloud["Hosted sandbox: one Docker container"]
    api["Web API + web app<br/>[FastAPI, three.js]"]
    bundle[("Demo bundle<br/>masked clips, overlays, DB, GLB, calibration")]
  end
  cams["4 Reolink cameras"]
  meta["Meta Model API"]
  cams -->|"RTSP"| rs
  cams -->|"AI events"| evt
  rs --> cap
  cap --> pipe
  evt --> pipe
  spat --> db
  pipe <--> db
  pipe -->|"HTTPS"| meta
  lan --> db
  rs -->|"WebRTC"| lan
  pipe -->|"server-sent events"| lan
  pipe -->|"vigil export"| bundle
  api --> bundle
  api -->|"live: protect, transcribe, compile rule, re-run story"| meta
```

Two deployments of the same `vigil` package. The home edge PC runs the restreamer, capture, Reolink events, the pipeline worker, the spatial tools and the LAN app over SQLite plus masked windows and the GLB. The hosted sandbox is one Docker container serving an exported demo bundle; it makes only 4 kinds of live call (protect, transcribe voice, compile rule, re-run story) and never connects to the house.

**Maps to:** `infra/go2rtc.yaml`, `vigil/reolink/capture.py`, `vigil/reolink/ai_events.py`, `vigil/spatial/`, `vigil/api/`, `vigil/store/`, `vigil/store/export.py`, `Dockerfile`

## 5.3 C4 level 3: components of the vigil package

Source: [5.3-c4-components.mmd](5.3-c4-components.mmd) · [spec section](../spec/vigil-spec.md#53-c4-level-3-components-of-the-vigil-package)

```mermaid
flowchart LR
  subgraph reolink["vigil/reolink"]
    probe["probe.py"]
    capture["capture.py"]
    aievents["ai_events.py"]
  end
  subgraph ingest["vigil/ingest"]
    privacy["privacy.py"] --> windows["windows.py"] --> motion["motion.py"]
  end
  subgraph metapkg["vigil/meta"]
    client["client.py<br/>retry, cache, spend ledger"]
    sam["sam.py"]
    spark["spark.py"]
    wonder["wonder.py"]
    asr["asr.py"]
  end
  subgraph perception["vigil/perception"]
    tracks["tracks.py"] --> events["events.py"]
  end
  subgraph spatial["vigil/spatial"]
    scan["scan.py"]
    calib["calibrate.py"]
    coverage["coverage.py"]
    locate["locate.py"]
  end
  subgraph reasoning["vigil/reasoning"]
    visits["visits.py"] --> rules["rules.py"] --> triage["triage.py"] --> story["story.py"] --> validator["validator.py"] --> verdict["verdict.py"]
    loop["loop.py"]
  end
  store[("vigil/store")]
  capture --> privacy
  aievents --> motion
  motion --> sam --> tracks
  tracks --> spark --> visits
  tracks --> locate
  scan --> calib --> locate
  scan --> coverage --> visits
  locate --> visits
  events --> visits
  story --> wonder
  verdict --> store
  validator --> loop --> sam
  sam --> client
  spark --> client
  wonder --> client
  asr --> client
```

One box per file. Data flows from Reolink capture through ingest (privacy, windows, motion), to SAM 3.1 tracks and events, through spatial positions, into reasoning (visits, rules, triage, story, validator, verdict) and the store. Every model call goes through `meta/client.py`, which owns retries, caching and the spend ledger; `loop.py` feeds validated watch proposals back to SAM.

**Maps to:** `vigil/reolink/*`, `vigil/ingest/*`, `vigil/meta/*`, `vigil/perception/*`, `vigil/spatial/*`, `vigil/reasoning/*`, `vigil/store/*`

## 5.4 Sequence: processing one window

Source: [5.4-seq-process-window.mmd](5.4-seq-process-window.mmd) · [spec section](../spec/vigil-spec.md#54-sequence-processing-one-window)

```mermaid
sequenceDiagram
  autonumber
  participant I as ingest
  participant C as meta.client
  participant S as sam-3.1
  participant P as muse-spark-1.3
  participant E as perception
  participant V as reasoning
  participant D as SQLite
  I->>I: apply clock offset, black out privacy polygons, strip audio
  I->>I: cut 10 s windows with 2 s overlap, motion score
  alt motion below threshold
    I->>D: store window as idle, no model call
  else motion above threshold
    I->>C: upload masked window, POST /v1/files
    C-->>I: file_id
    loop one request per noun phrase: person, car, plus active watches
      I->>C: POST /v1/responses model sam-3.1, concept prompt
      C->>S: streamed request
      S-->>C: per-frame boxes and masks
    end
    C-->>E: parsed tracks, at most 16 ids per request
    E->>E: stitch ids across overlapping windows by box IoU
    E->>E: burn track tags into a preview clip
    E->>C: tagged clip + JSON schema with enum of tags
    C->>P: appearance notes request
    P-->>C: notes per tag, schema-checked
    E->>E: build events: enter, exit, cross, touch, remove, dwell
    E->>V: events + notes
    V->>V: link across cameras by topology and notes, record gaps
    V->>D: visits, events, gaps, model_calls
  end
```

The motion gate decides whether any model is called. An active window is uploaded once (`POST /v1/files`) and SAM 3.1 gets one request per noun phrase (`person`, `car`, plus active watches) on the same `file_id`. Tracks are stitched across overlapping windows, tags are burned into a preview clip for Spark's appearance notes, events are built, and visits are linked by topology and notes with gaps recorded.

**Maps to:** `vigil/ingest/sync.py`, `privacy.py`, `windows.py`, `motion.py`; `vigil/meta/client.py`, `sam.py`, `spark.py`; `vigil/perception/tracks.py`, `overlays.py`, `events.py`; `vigil/reasoning/visits.py`, `topology.py`; `vigil/store/db.py`

## 5.5 Sequence: story, validation and verdict

Source: [5.5-seq-story-validation-verdict.mmd](5.5-seq-story-validation-verdict.mmd) · [spec section](../spec/vigil-spec.md#55-sequence-story-validation-and-verdict)

```mermaid
sequenceDiagram
  autonumber
  participant V as visits.py
  participant R as rules.py
  participant T as triage.py
  participant G as Glimmer or Spark
  participant W as muse-wonder-1.0
  participant X as validator.py
  participant Y as verdict.py
  V->>R: closed visit ledger: events, gaps, protected objects
  R-->>V: fired rules, rule floor
  V->>T: ledger summary
  alt rule fired, protected object touched (not a 9.4 case-2 household touch), or unresolved gap
    T-->>V: escalate, forced by code
  else otherwise
    T->>G: summary JSON
    G-->>T: escalate true or false + reason
  end
  alt not escalated
    V->>Y: templated story from events
  else escalated
    V->>W: ledger JSON + output schema
    W-->>X: verdict proposal, sentences with ids, watch proposals
    X->>X: every sentence cites ids in this visit, no action inside a gap
    alt draft fails
      X->>W: retry once with the failure list
      W-->>X: second draft
      opt fails again
        X->>Y: fall back to templated story
      end
    end
    X->>Y: validated sentences + proposal
  end
  Y->>Y: verdict = deterministic function of floor, gaps, proposal
```

Wonder writes; code checks and decides. Rules set the floor; triage is forced by code for a fired rule, a touched protected object or an unresolved gap, otherwise Glimmer or Spark decides. Escalated visits go to Wonder with the ledger JSON; the validator retries once with the failure list, then falls back to the template. The verdict is a deterministic function of floor, gaps and proposal. Gap sentences never come from the model.

**Maps to:** `vigil/reasoning/rules.py`, `triage.py`, `story.py`, `templates.py`, `validator.py`, `verdict.py`; `vigil/meta/wonder.py`, `glimmer.py`, `spark.py`

## 5.6 Sequence: tap-to-protect and voice rule

Source: [5.6-seq-tap-to-protect-voice-rule.mmd](5.6-seq-tap-to-protect-voice-rule.mmd) · [spec section](../spec/vigil-spec.md#56-sequence-tap-to-protect-and-voice-rule)

```mermaid
sequenceDiagram
  autonumber
  actor O as Owner or judge
  participant UI as Web app
  participant API as FastAPI
  participant S as sam-3.1
  participant A as muse-voice-transcribe-1.0
  participant P as muse-spark-1.3
  O->>UI: tap the side gate on a still frame
  UI->>API: POST /api/protect camera, frame_ts, point
  API->>S: image + point prompt
  S-->>API: box + mask
  API-->>UI: protected object po_3, mask outline, latency, cost
  O->>UI: hold mic (or tap a sample-audio button): tell me if anyone except family opens this gate after dark
  UI->>API: POST /api/voice/transcribe WAV, max 30 s and 2 MB
  API->>A: transcribe
  A-->>API: transcript
  API-->>UI: editable transcript, call ID, latency, cost
  O->>UI: accept or edit the transcript
  UI->>API: POST /api/rules/compile text
  API->>P: transcript + schema, targets limited to existing objects and zones
  P-->>API: rule draft JSON
  API->>API: validate draft, map identity phrases to applies_to, note what Vigil cannot do
  API-->>UI: draft card: non-household touches po_3, 17:30 to 06:00, basis note
  O->>UI: confirm
  UI->>API: POST /api/rules/r7/confirm
  API-->>UI: rule active
```

A tap on a still becomes a SAM 3.1 point prompt; the mask is stored as a protected object and returned with latency and cost. A spoken rule (or one of the 3 sample-audio fixture buttons) is transcribed first and returned as an editable transcript (FR-022, P0; typed rules skip this step). The accepted text is then compiled by Spark against the catalogue of existing objects and zones, identity phrases are mapped to `applies_to`, and the draft card shows the scope (here non-household, 17:30 to 06:00), the basis note and what Vigil cannot do. The rule is activated on confirm.

**Maps to:** `vigil/api/routes.py` (`POST /api/protect`, `POST /api/voice/transcribe`, `GET /api/voice/fixtures`, `POST /api/rules/compile`, `POST /api/rules/{id}/confirm`), `vigil/meta/sam.py`, `asr.py`, `spark.py`, `vigil/reasoning/rules.py`, `web/app.js`

## 5.7 Sequence: the closed loop (Wonder steers SAM 3.1)

Source: [5.7-seq-closed-loop.mmd](5.7-seq-closed-loop.mmd) · [spec section](../spec/vigil-spec.md#57-sequence-the-closed-loop-wonder-steers-sam-31)

```mermaid
sequenceDiagram
  autonumber
  participant W as muse-wonder-1.0
  participant X as validator.py
  participant L as loop.py
  participant D as SQLite watches
  participant I as next porch window
  participant S as sam-3.1
  participant UI as Visit card
  W-->>X: watch_proposals: porch, package
  X->>L: proposals from a validated draft only
  L->>L: camera exists, noun phrase in allowlist, under 4 watches per camera
  alt rejected
    L->>D: log rejected proposal with reason
  else accepted
    L->>D: watch w2 active, origin wonder, expires in 24 h
    L-->>UI: Now watching: package on porch, with undo
    I->>S: concept prompts person, car, package
    S-->>I: package track
    I->>I: package removed while a person overlaps, event e41
  end
```

Watch proposals come only from a validated draft. `loop.py` checks the camera exists, the noun phrase is on the allowlist and the camera has fewer than 4 watches; rejected proposals are logged, accepted ones become a 24 h watch with an undo notice, and the next windows on that camera add the phrase to SAM's prompts, which is how scenario B later yields a `removed` event.

**Maps to:** `vigil/reasoning/loop.py`, `vigil/reasoning/validator.py`, `config/allowlist.json`, `vigil/meta/sam.py`, `vigil/perception/events.py`, `web/cards.js`

## 5.8 Data flow and AI inference pipeline, with the privacy boundary

Source: [5.8-data-flow-privacy-boundary.mmd](5.8-data-flow-privacy-boundary.mmd) · [spec section](../spec/vigil-spec.md#58-data-flow-and-ai-inference-pipeline-with-the-privacy-boundary)

```mermaid
flowchart LR
  subgraph home["Home: raw data never leaves the house"]
    cams["Reolink cameras<br/>on-camera privacy masks, audio off"]
    raw[("Raw segments<br/>48 h ring, gitignored")]
    mask["privacy.py<br/>exact polygons to black, audio removed"]
    check{"Pre-upload check<br/>polygon pixels all zero?<br/>no audio stream?"}
    masked[("Masked windows")]
    locate["locate.py<br/>foot point to ground,<br/>uncertainty radius"]
    glb[("LiDAR model + calibration")]
  end
  subgraph metaapi["Meta Model API, Standard mode"]
    sam["sam-3.1<br/>tracks and masks"]
    spark["muse-spark-1.3<br/>appearance notes, rule compile"]
    wonder["muse-wonder-1.0<br/>story from JSON only"]
  end
  ledger[("Event ledger<br/>events, gaps, 3D estimates;<br/>no pixels")]
  cams --> raw --> mask --> check
  check -->|"pass"| masked
  check -->|"fail: block upload"| mask
  masked --> sam
  masked -->|"tagged clip"| spark
  sam --> locate
  glb --> locate
  locate --> ledger
  sam --> ledger
  spark --> ledger
  ledger --> wonder
```

The privacy boundary drawn as data flow. Raw segments live only in the gitignored 48 h ring at home; `privacy.py` blacks out polygons and strips audio, and a pre-upload check blocks any window with a non-zero polygon pixel or an audio stream. Only masked windows reach SAM and Spark; Wonder sees only the event ledger (events, gaps, 3D estimates), never pixels, which is also what makes its claims checkable.

**Maps to:** `vigil/ingest/privacy.py`, `scripts/privacy_scan.py`, `vigil/reolink/capture.py`, `vigil/spatial/locate.py`, `vigil/meta/sam.py`, `spark.py`, `wonder.py`, `vigil/store/schema.sql`

## 5.9 State machine: visit lifecycle

Source: [5.9-state-visit-lifecycle.mmd](5.9-state-visit-lifecycle.mmd) · [spec section](../spec/vigil-spec.md#59-state-machine-visit-lifecycle)

```mermaid
stateDiagram-v2
  [*] --> Open: first event on any camera
  Open --> Open: linked event within transit window
  Open --> InGap: subject leaves toward a blind spot
  InGap --> Open: re-linked within max transit
  InGap --> Closed: max transit exceeded, gap stays unresolved
  Open --> Closed: no linked event for 60 s
  Closed --> Triaged: rules evaluated, triage done
  Triaged --> Templated: not escalated
  Triaged --> Drafted: escalated to Wonder
  Drafted --> Validated: every sentence passes
  Drafted --> Drafted: rejected once, retry
  Drafted --> Templated: rejected twice
  Validated --> Published
  Templated --> Published
  Published --> [*]
```

A visit opens on its first event, stays open while linked events arrive within the transit window, and enters InGap when the subject leaves toward a blind spot; it re-links within the maximum transit time or closes with the gap unresolved. After 60 s with no linked event it closes, is triaged, then either templated or drafted by Wonder (one retry, then template) before it is published.

**Maps to:** `vigil/reasoning/visits.py`, `topology.py`, `triage.py`, `story.py`, `validator.py`; `visits.state` in `vigil/store/schema.sql`

## 5.10 State machines: rules and watches

Source: [5.10-state-rules-watches.mmd](5.10-state-rules-watches.mmd) · [spec section](../spec/vigil-spec.md#510-state-machines-rules-and-watches)

```mermaid
stateDiagram-v2
  direction LR
  state Rule {
    [*] --> Draft: compiled from voice or text
    Draft --> Active: owner confirms
    Draft --> Discarded: owner cancels
    Active --> Disabled: owner turns off
    Disabled --> Active: owner turns on
  }
  state Watch {
    [*] --> Proposed: Wonder or owner tap
    Proposed --> Rejected: not in allowlist or cap reached
    Proposed --> Watching: accepted, owner notified
    Watching --> Revoked: owner taps undo
    Watching --> Expired: object gone or 24 h passed
  }
```

Rules go Draft to Active only on owner confirmation, and can be disabled and re-enabled. Watches are Proposed by Wonder or an owner tap, Rejected if off the allowlist or over the cap, otherwise Watching with an owner notice, and end as Revoked (undo) or Expired (object gone or 24 h).

**Maps to:** `vigil/reasoning/rules.py`, `vigil/reasoning/loop.py`; `rules.state` and `watches.status` in `vigil/store/schema.sql`

## 5.11 Deployment

Source: [5.11-deployment.mmd](5.11-deployment.mmd) · [spec section](../spec/vigil-spec.md#511-deployment)

```mermaid
flowchart TB
  subgraph house["Home network: no inbound ports"]
    cams["4 Reolink cameras"]
    pc["Team PC<br/>go2rtc, capture, pipeline, LAN app"]
    phoneapp["Owner phone on home Wi-Fi"]
  end
  subgraph gh["GitHub public repo"]
    code["Source, tests, EVAL.md, HACKATHON.md"]
    bundle["demo bundle<br/>masked clips, overlays, DB, GLB, calibration"]
    ci["GitHub Actions<br/>lint, unit, integration, E2E, secret scan,<br/>privacy and metadata scan"]
  end
  subgraph host["Container host, for example Fly.io or Render"]
    app["Docker: FastAPI + static web + three.js<br/>VIGIL_MODE=sandbox"]
    secret["Secret: MODEL_API_KEY, daily cap,<br/>VIGIL_ALLOW_PAID, VIGIL_JUDGING_CAP_USD"]
  end
  meta["api.meta.ai/v1"]
  cams -->|"RTSP, AI events"| pc
  pc -->|"WebRTC, SSE"| phoneapp
  pc -->|"HTTPS outbound"| meta
  pc -->|"vigil export, git push"| bundle
  code --> ci
  bundle --> app
  code --> app
  secret --> app
  app -->|"live calls"| meta
```

Where everything runs. The home network has no inbound ports: cameras feed the team PC, which serves the owner's phone over WebRTC and SSE and calls Meta outbound only. The public GitHub repo holds source, tests, EVAL.md, HACKATHON.md and the demo bundle, and CI runs lint, tests, E2E and the secret, privacy and metadata scans. A container host runs the sandbox image with `VIGIL_MODE=sandbox`, the API key as a secret, the daily cap, and the judging settings `VIGIL_ALLOW_PAID` and `VIGIL_JUDGING_CAP_USD`.

**Maps to:** `.github/workflows/ci.yml`, `Dockerfile`, `vigil/settings.py`, `vigil/api/app.py`, `vigil/store/export.py`, `demo/`

## 5.12 Spatial build and calibration pipeline

Source: [5.12-spatial-build-calibration.mmd](5.12-spatial-build-calibration.mmd) · [spec section](../spec/vigil-spec.md#512-spatial-build-and-calibration-pipeline)

```mermaid
flowchart TB
  subgraph capture["One-time capture"]
    scan["Scan 4 LiDAR loops<br/>with overlaps"]
    stills["Calibration still<br/>per camera"]
    fov["Nominal FOV<br/>from the camera model datasheet"]
    profile["Optional lens profile per camera model<br/>checkerboard, about 20 views"]
  end
  subgraph build["vigil spatial build"]
    scale{"Scale error under 2%?"}
    reg["Register segments<br/>3 point pairs, then ICP"]
    frame["World frame<br/>origin at front door"]
    ground["Ground mesh + height grid"]
    glb["GLB under 15 MB,<br/>metadata stripped"]
  end
  subgraph cal["vigil spatial calibrate: product path"]
    intr["Intrinsics: lens profile if RMS under 1 px,<br/>else nominal FOV, flagged"]
    propose["SAM 3.1 proposes landmarks<br/>door, gate, fence post, window"]
    pnp["Accept 6 landmarks, click each on the mesh,<br/>PnP with RANSAC on 6"]
    reproj{"Landmark reprojection under 6 px nominal<br/>or 4 px profile?"}
    json[("calibration.json")]
  end
  subgraph audit["Audit harness: benchmark only"]
    markers["6 surveyed markers per camera<br/>never used for calibration"]
    held{"Held-out ground error<br/>under 0.25 m?"}
    report[("Audit report in EVAL")]
  end
  cov["vigil spatial coverage<br/>visibility grid, blind regions"]
  yaml[("cameras.yaml<br/>blind-spot polygons")]
  scan --> scale
  scale -->|"yes"| reg
  scale -->|"no: rescale"| reg
  reg --> frame --> ground --> glb
  fov --> intr
  profile --> intr
  stills --> propose --> pnp
  intr --> pnp
  glb --> pnp
  pnp --> reproj
  reproj -->|"yes"| json
  reproj -->|"no: SAM proposes more, drop worst point"| pnp
  json --> held
  markers --> held
  held -->|"yes"| report
  held -->|"no: record a lens profile for that model, re-solve"| profile
  json --> cov
  glb --> cov
  cov --> yaml
```

One-time capture (4 LiDAR loops, a still per camera, the camera model's nominal FOV, and an optional checkerboard lens profile per camera model) feeds `vigil spatial build` (scale check, registration, world frame, ground mesh, GLB under 15 MB with metadata stripped), then the product path of `vigil spatial calibrate`: intrinsics from the lens profile if its RMS is under 1 px, else nominal FOV (flagged); SAM 3.1 proposes landmarks, the installer accepts 6 and clicks each on the mesh, and PnP with RANSAC runs on the 6 with a landmark reprojection gate. The audit harness (benchmark only) compares the result against 6 surveyed markers per camera that are never used for calibration; a miss leads to a lens profile for that model and a re-solve. `vigil spatial coverage` then writes blind-spot polygons back to `cameras.yaml`. Every gate has a measured acceptance value and a fallback.

**Maps to:** `vigil/spatial/scan.py`, `calibrate.py`, `coverage.py`, `web/calibrate/`, `config/calibration.json`, `config/cameras.yaml`; runbooks [lidar-scan](../runbooks/lidar-scan.md) and [calibration](../runbooks/calibration.md)

## 5.13 Sequence: live near-real-time mode at home

Source: [5.13-seq-live-home-mode.mmd](5.13-seq-live-home-mode.mmd) · [spec section](../spec/vigil-spec.md#513-sequence-live-near-real-time-mode-at-home)

```mermaid
sequenceDiagram
  autonumber
  participant R as Reolink camera
  participant E as ai_events.py
  participant C as capture.py
  participant P as pipeline
  participant S as sam-3.1
  participant L as locate.py
  participant UI as LAN app, 3D view
  R-)E: TCP push: person on Backyard
  E-)UI: SSE camera_ai event
  UI->>UI: Backyard view cone pulses, position pending
  C->>C: segment closes after up to 10 s
  C->>P: window = segment + last 2 s of previous
  P->>P: privacy mask, motion score
  P->>S: upload + concept prompt person
  S-->>P: masks per frame
  P->>L: foot points
  L-->>P: ground positions with 95% radius
  P-)UI: SSE tracks and 3D estimates
  UI->>UI: draw discs, update path, show measured lag
```

Why the live mode is near-real-time, not real-time. The Reolink TCP-push event reaches the 3D view first (the cone pulses, position pending). When the 10 s segment closes, the window (segment plus the last 2 s of the previous one) is masked, gated and sent to SAM 3.1; foot points become ground positions with a 95% radius, and the discs, path and measured lag are pushed over SSE.

**Maps to:** `vigil/reolink/ai_events.py`, `capture.py`, `vigil/api/live.py`, `vigil/meta/sam.py` (or `sam_local.py`), `vigil/spatial/locate.py`, `web/twin/`; runbook [reolink](../runbooks/reolink.md)

## 10 Compute plan: RTX 3090 first, DGX Spark only if a gate fails

Source: [10-compute-plan.mmd](10-compute-plan.mmd) · [spec section](../spec/vigil-spec.md#10-compute-plan-rtx-3090-first-dgx-spark-only-if-a-gate-fails)

```mermaid
flowchart LR
  subgraph ws["Workstation, home network: RTX 3090 24 GB (verify with H-01)"]
    cpu["CPU work<br/>ffmpeg capture, privacy masks, events,<br/>Open3D scan build, PnP, coverage"]
    samL["SAM 3.1 open weights<br/>image prompts + short video chunks"]
    glim["Muse Glimmer 30B, 4-bit<br/>llama.cpp server, triage"]
    guard["Budget guard + ledger<br/>every API call priced before sending"]
  end
  subgraph dgx["DGX Spark, 128 GB unified: OFF by default"]
    samD["SAM 3.1 full 10 s windows<br/>only if gate H-02 fails"]
  end
  subgraph metaapi["Meta Model API: $150 credits, then card up to $25 during judging"]
    samA["sam-3.1"]
    spark["muse-spark-1.3"]
    wonder["muse-wonder-1.0"]
    asr["muse-voice-transcribe-1.0"]
  end
  host["Hosted sandbox<br/>CPU only, cached by default"]
  cpu --> samL
  samL --> glim
  cpu -.->|"conditional, after notice"| samD
  guard --> samA
  guard --> spark
  guard --> wonder
  guard --> asr
  host -->|"capped live calls"| guard
```

Where each workload runs. CPU work, local SAM 3.1 open weights and Muse Glimmer 30B 4-bit run on the RTX 3090 workstation (only after H-01 verifies it; SAM and Glimmer are never co-resident). The DGX Spark is off by default and only runs full 10 s SAM windows if gate H-02 fails (phase D-1). Every paid API call passes the budget guard first, including the hosted sandbox's capped live calls: the $150 credits first, then at most $25 on the card during judging.

**Maps to:** `vigil/meta/sam_local.py`, `glimmer.py`, `budget.py`, `client.py`, `vigil/settings.py` (`VIGIL_SAM_BACKEND`, `VIGIL_TRIAGE_BACKEND`), `scripts/gpu_probe.py`; runbooks [gpu-h01-h04](../runbooks/gpu-h01-h04.md) and [dgx-spark-d1](../runbooks/dgx-spark-d1.md)
