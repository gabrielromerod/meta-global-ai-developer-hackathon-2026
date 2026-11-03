# Vigil

**One cited story per visit, placed in a 3D model of the house.** Meta models perceive and write; Vigil's code links, checks and decides, so you get fewer, better alerts and can check every claim in one click. Vigil does not identify anyone and creates no face, voice or body templates.

- **Video:** TBD
- **Sandbox:** TBD. Live calls stay on during judging (Nov 5–10 PT) under a **$25 hard cap** ($5 per day, none after Nov 10, 23:59 PT); past a cap or on a failure, every live button shows the recorded result with a notice.

Built for the Meta Global AI Developer Hackathon 2026. Engineering specification: [docs/spec/vigil-spec.md](docs/spec/vigil-spec.md) (revised Nov 2: [change set](docs/spec/changes/2026-11-02-business-corrections.md)).

## What Vigil does

- **Turns motion into visits, not alerts.** Four home Reolink cameras feed 10 s windows; SAM 3.1 tracks people and objects, and Vigil links them across cameras by measured topology into one visit with one verdict: Normal, Noteworthy, Needs your attention, or Can't confirm.
- **Knows where a person came from, not who they are.** Someone who walks out of the house's own door is treated as household; someone arriving from the street, driveway or side alley is an external visitor; someone arriving during an owner-set guest or delivery window is expected. A rule can say "anyone except family": the same gate touch after dark stays quiet for a person who came out of the house (scenario A′) and alerts for one who came in from the alley (scenario C).
- **Writes a story you can check.** Muse Wonder writes the story from the event ledger (never pixels); every sentence cites event IDs, and a validator rejects any sentence it cannot back, including a role claim the ledger does not hold. One click on a citation seeks every camera to the evidence.
- **Is honest about what it did not see.** Blind spots come from measured coverage; when someone goes behind the shed, the card shows a dotted "Not observed · 41 s" gap instead of a guessed path.
- **Places everything in 3D.** An iPhone LiDAR scan becomes a model of the house; each camera is placed in it from nominal lens FOV and 6 landmarks that SAM 3.1 proposes, and each detection becomes a ground position with a stated uncertainty radius.
- **Takes rules by voice or text.** Tap an object to protect it (SAM 3.1 point prompt); hold the mic, tap a sample-audio button, or type a rule; Muse Voice Transcribe gives an editable transcript and Muse Spark compiles it, with a plain-words note on whom the rule applies to.

## Models: the 5-model loop

| Model | Role | File |
| --- | --- | --- |
| `sam-3.1` (Meta Model API; open weights locally if gate H-02 passes) | Perceives: masks and tracks per noun phrase on masked windows, tap-to-protect point prompts, calibration landmark proposals | [`vigil/meta/sam.py`](vigil/meta/sam.py), [`vigil/meta/sam_local.py`](vigil/meta/sam_local.py), [`vigil/spatial/landmarks.py`](vigil/spatial/landmarks.py) |
| Muse Glimmer 30B (open weights, 4-bit, llama.cpp on a local RTX 3090) | Triages routine visits at $0 API cost | [`vigil/meta/glimmer.py`](vigil/meta/glimmer.py) |
| `muse-spark-1.3` | Appearance notes keyed to SAM's own track tags; rule compilation; triage fallback; naive baseline | [`vigil/meta/spark.py`](vigil/meta/spark.py) |
| `muse-wonder-1.0` | Cited story from the event ledger JSON; verdict and watch proposals (the closed loop that steers SAM) | [`vigil/meta/wonder.py`](vigil/meta/wonder.py) |
| `muse-voice-transcribe-1.0` | Turns spoken rules into editable text | [`vigil/meta/asr.py`](vigil/meta/asr.py) |

**Glimmer's part depends on gate H-03**, which has not run yet. Glimmer triages only on the home edge and in the benchmark; the hosted sandbox triages with Spark and shows Glimmer as recorded trace badges. If H-03 fails, triage falls back to Spark and the loop is 4 models. **Configuration used for the submission: TBD** (filled in once H-02 and H-03 have run).

Every hosted call goes through [`vigil/meta/client.py`](vigil/meta/client.py) (retries, cache, call ledger) and is priced by the budget guard before it is sent. Standard mode only: no Contributor-mode model IDs.

## Quickstart

Requires Python 3.12, [uv](https://docs.astral.sh/uv/) and ffmpeg.

```sh
uv sync                          # install the locked environment
pwsh scripts/tasks.ps1 test      # Windows
make test                        # Linux, macOS, WSL
make demo                        # serve the synthetic demo bundle (scenarios A, A′, B, B′, C)
uv run vigil serve               # web app and API on http://127.0.0.1:8000
```

The sandbox runs cached by default and works with no API key. The offline core is built and tested on synthetic data; nothing has run on real footage or billed calls yet (status: [docs/readiness.md](docs/readiness.md)).

## Evaluation

Targets were pre-registered before any run in [EVAL.md](EVAL.md). Results are appended after the run, including misses.

| Metric | Target | Result |
| --- | --- | --- |
| Alert reduction | at least 80% | TBD |
| Correct verdict | at least 10 of 12 | TBD |
| Cross-camera link precision | at least 90% | TBD |
| Claims inside gaps | 0 | TBD |
| Uncited sentences shipped | 0 | TBD |
| Role miss rate (household subjects not recognised as household), day and night | reported, no target | TBD |
| 3D position error (median, within 10 m) | under 0.5 m | TBD |
| Test points inside stated 95% radius | at least 90% | TBD |
| Credit-funded Meta API spend | under $140 | TBD |
| Judging spend after the credit window | at most $25 | TBD |

## Honest limits

- **Near-real-time, not real-time.** Only the cameras' own Reolink AI events are real-time; SAM 3.1 tracks and 3D positions follow seconds to tens of seconds later, and the measured lag is shown on screen.
- **Positions are estimates with a measured radius.** Each 3D position shows an r95 radius measured by the audit harness (surveyed markers never used in calibration); a "±0.4 m" label appears only where the audit measured it. Nominal-FOV intrinsics widen the radius at the image edges. Nothing is drawn inside a gap.
- **Night footage is infrared and greyscale.** Colour notes become "unknown", so linking relies on transit time, and household or expected roles do not carry across a blind spot (the subject becomes `unknown`, which fails closed). Night and day results are reported separately.
- **Roles are spatial origin, not identity.** Vigil treats someone as household only when it saw them come out of the house's own doors, or when a household member checked in on the LAN app just before they came into view. **A household member arriving from the street without a check-in counts as non-household** and can trigger "anyone except family" rules. A person who got into the house unobserved and then walks out of a door can be treated as household; rules that apply to anyone are unaffected.
- **Edge hardware has a power cost.** The development box is an RTX 3090 (about 48 W idle, 349 W under load, GPU board power measured by nvidia-smi); running a box like it 24/7 would cost the homeowner roughly $15–26 per month in electricity (estimate). The [unit economics](docs/spec/vigil-spec.md#119-commercial-unit-economics-new-why-the-edge-plus-cloud-cascade-wins) (about 78–83% gross margin at $14.99 per month including payment fees, at 2–3 escalations per day with appearance notes kept local) exclude this cost and are estimates until T-27 measures the tier rates; a low-power edge accelerator is an untested assumption.
- **No multi-home scale claim.** The demo is one house; per-camera-day cost is a labelled projection from measured numbers.
- **Live home mode is shown only in the video.** The hosted sandbox replays recorded footage and never connects to the house.

## Privacy

- Raw video stays at home. Privacy polygons are blacked out and audio removed before anything is stored for upload; uploads are refused otherwise.
- Muse Wonder never sees pixels, only the event ledger.
- Vigil does not identify anyone and creates no face, voice or body templates; no schema has face, age, gender, skin, ethnicity, height, gait, body-measurement, voice-feature or name fields.
- Spoken rules go only to Muse Voice Transcribe and are never written to disk; only the transcript is cached. The only audio in the repo is the 3 consented voice-rule fixtures listed in `config/audio_fixtures.json` (none recorded yet), checked repository-wide in CI.
- People filmed are consenting adults from the team; plates are covered with "VIGIL-01"; no house number, street-facing frame or GPS metadata is published.
- CI scans for secrets, unmasked pixels, stray audio and location metadata.

Details: [HACKATHON.md](HACKATHON.md#privacy-notes) and [docs/conventions.md](docs/conventions.md#privacy-rules).

## Repository map

| Path | What it holds |
| --- | --- |
| [`vigil/reolink/`](vigil/reolink/) | Camera probe, continuous capture, Reolink AI events |
| [`vigil/ingest/`](vigil/ingest/) | Config loader (zones with kinds), clock sync, privacy masking, windows, motion gate |
| [`vigil/meta/`](vigil/meta/) | Meta client, budget guard (credit and judging caps), cache, model adapters (hosted and local) |
| [`vigil/perception/`](vigil/perception/) | Track stitching, events with origin tagging, overlays |
| [`vigil/spatial/`](vigil/spatial/) | LiDAR model build, landmark proposals, calibration and audit harness, coverage, 3D positions |
| [`vigil/reasoning/`](vigil/reasoning/) | Topology, visits, gaps and roles, rules, triage, story, validator, verdict, closed loop |
| [`vigil/store/`](vigil/store/) | SQLite schema, database access, demo export |
| [`vigil/api/`](vigil/api/) | FastAPI app, routes, voice, owner windows and check-in, live stream, guards |
| [`vigil/eval/`](vigil/eval/) | Benchmark, metrics (incl. role miss rate), naive baseline, spatial evaluation |
| [`config/`](config/) | Cameras, zones, privacy polygons, topology, default rules, role phrases and banned words, audio fixture list |
| [`tests/`](tests/) | Unit, integration and E2E tests |
| [`docs/`](docs/README.md) | Requirements, use cases, demo path, architecture, plans, runbooks |
| [`scripts/`](scripts/) | Task runner for Windows, Meta smoke test, GPU probe, privacy and metadata scans, backlog sync |

## Documentation

- [Documentation index](docs/README.md)
- [Functional](docs/requirements/functional.md) and [non-functional](docs/requirements/non-functional.md) requirement checklists
- [Demo happy path](docs/demo-happy-path.md) and [use cases](docs/use-cases.md)
- [Architecture diagrams](docs/architecture/README.md)
- [Schedule](docs/plans/schedule.md) and [backlog](docs/backlog.md) (GitHub issues #1 to #80)
- [Conventions](docs/conventions.md) and [runbooks](docs/README.md#index)
