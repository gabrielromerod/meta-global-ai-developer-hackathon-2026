# Vigil

**One cited story per visit, placed in a 3D model of the house.** Meta models perceive and write; Vigil's code links, checks and decides, so you get fewer, better alerts and can check every claim in one click.

- **Video:** TBD
- **Sandbox:** TBD

Built for the Meta Global AI Developer Hackathon 2026. Engineering specification: [docs/spec/vigil-spec.md](docs/spec/vigil-spec.md).

## What Vigil does

- **Turns motion into visits, not alerts.** Four home Reolink cameras feed 10 s windows; SAM 3.1 tracks people and objects, and Vigil links them across cameras by measured topology into one visit with one verdict: Normal, Noteworthy, Needs your attention, or Can't confirm.
- **Writes a story you can check.** Muse Wonder writes the story from the event ledger (never pixels); every sentence cites event IDs, and a validator rejects any sentence it cannot back. One click on a citation seeks every camera to the evidence.
- **Is honest about what it did not see.** Blind spots come from measured coverage; when someone goes behind the shed, the card shows a dotted "Not observed · 41 s" gap instead of a guessed path.
- **Places everything in 3D.** An iPhone LiDAR scan becomes a model of the house; each camera is calibrated into it, and each detection becomes a ground position with a stated uncertainty radius.
- **Lets you protect what matters in plain language.** Tap an object to protect it (SAM 3.1 point prompt), type a rule, and Vigil compiles it, telling you what it cannot do: it never identifies people.

## Models

| Model | Role | File |
| --- | --- | --- |
| `sam-3.1` (Meta Model API) | Tracks and masks per noun phrase on masked windows; tap-to-protect point prompts | [`vigil/meta/sam.py`](vigil/meta/sam.py) |
| `muse-spark-1.3` | Appearance notes keyed to SAM's own track tags; rule compilation; triage fallback; naive baseline | [`vigil/meta/spark.py`](vigil/meta/spark.py) |
| `muse-wonder-1.0` | Cited story from the event ledger JSON; verdict and watch proposals (the closed loop that steers SAM) | [`vigil/meta/wonder.py`](vigil/meta/wonder.py) |
| `muse-voice-transcribe-1.0` | Voice rules (P2; typed rules are the default) | [`vigil/meta/asr.py`](vigil/meta/asr.py) |
| Muse Glimmer 30B (open weights, 4-bit, llama.cpp on a local RTX 3090) | Triage: escalate to Wonder or use a template | [`vigil/meta/glimmer.py`](vigil/meta/glimmer.py) |
| SAM 3.1 open weights (local RTX 3090) | Tracking for live home mode and bulk benchmark processing, behind the same interface as the API | [`vigil/meta/sam_local.py`](vigil/meta/sam_local.py) |

Every hosted call goes through [`vigil/meta/client.py`](vigil/meta/client.py) (retries, cache, call ledger) and is priced by the budget guard before it is sent. Standard mode only: no Contributor-mode model IDs.

## Quickstart

Requires Python 3.12, [uv](https://docs.astral.sh/uv/) and ffmpeg.

```sh
uv sync                          # install the locked environment
pwsh scripts/tasks.ps1 test      # Windows
make test                        # Linux, macOS, WSL
uv run vigil serve               # web app and API on http://127.0.0.1:8000
```

The sandbox runs cached by default and works with no API key. The pipeline is being built during the hackathon; commands that are not implemented yet exit with a notice (see [docs/readiness.md](docs/readiness.md)).

## Evaluation

Targets were pre-registered before any run in [EVAL.md](EVAL.md). Results are appended after the run, including misses.

| Metric | Target | Result |
| --- | --- | --- |
| Alert reduction | at least 80% | TBD |
| Correct verdict | at least 10 of 12 | TBD |
| Cross-camera link precision | at least 90% | TBD |
| Claims inside gaps | 0 | TBD |
| Uncited sentences shipped | 0 | TBD |
| 3D position error (median, within 10 m) | under 0.5 m | TBD |
| Test points inside stated 95% radius | at least 90% | TBD |
| Total Meta API spend | under $140 | TBD |

## Honest limits

- **Near-real-time, not real-time.** Only the cameras' own Reolink AI events are real-time; SAM 3.1 tracks and 3D positions follow seconds to tens of seconds later, and the measured lag is shown on screen.
- **Positions are estimates.** Every 3D position carries an uncertainty radius; nothing is drawn inside a gap; low-confidence estimates are marked.
- **Night footage is infrared and greyscale.** Colour notes become "unknown" and linking relies on transit time; night and day results are reported separately.
- **No multi-home scale claim.** The demo is one house. Windows are independent, so processing parallelises by camera; per-camera-day cost is a labelled projection from measured numbers.
- **Live home mode is shown only in the video.** The hosted sandbox replays recorded footage and never connects to the house.

## Privacy

- Raw video stays at home. Privacy polygons are blacked out and audio removed before anything is stored for upload; uploads are refused otherwise.
- Muse Wonder never sees pixels, only the event ledger.
- Vigil never identifies people, and stores no face, age, gender, skin or ethnicity attributes.
- People filmed are consenting adults from the team; plates are covered with "VIGIL-01"; no house number, street-facing frame or GPS metadata is published.
- CI scans for secrets, unmasked pixels and location metadata.

Details: [HACKATHON.md](HACKATHON.md#privacy-notes) and [docs/conventions.md](docs/conventions.md#privacy-rules).

## Repository map

| Path | What it holds |
| --- | --- |
| [`vigil/reolink/`](vigil/reolink/) | Camera probe, continuous capture, Reolink AI events |
| [`vigil/ingest/`](vigil/ingest/) | Config loader, clock sync, privacy masking, windows, motion gate |
| [`vigil/meta/`](vigil/meta/) | Meta client, budget guard, cache, model adapters (hosted and local) |
| [`vigil/perception/`](vigil/perception/) | Track stitching, events, overlays |
| [`vigil/spatial/`](vigil/spatial/) | LiDAR model build, calibration, coverage, 3D positions |
| [`vigil/reasoning/`](vigil/reasoning/) | Topology, visits and gaps, rules, triage, story, validator, verdict, closed loop |
| [`vigil/store/`](vigil/store/) | SQLite schema, database access, demo export |
| [`vigil/api/`](vigil/api/) | FastAPI app, routes, live stream, guards |
| [`vigil/eval/`](vigil/eval/) | Benchmark, metrics, naive baseline, spatial evaluation |
| [`config/`](config/) | Cameras, zones, privacy polygons, topology (sample geometry until calibrated) |
| [`tests/`](tests/) | Unit, integration and E2E tests |
| [`docs/`](docs/README.md) | Requirements, use cases, demo path, architecture, plans, runbooks |
| [`scripts/`](scripts/) | Task runner for Windows; probes and scans as they land |

## Documentation

- [Documentation index](docs/README.md)
- [Functional](docs/requirements/functional.md) and [non-functional](docs/requirements/non-functional.md) requirement checklists
- [Demo happy path](docs/demo-happy-path.md) and [use cases](docs/use-cases.md)
- [Architecture diagrams](docs/architecture/README.md)
- [Schedule](docs/plans/schedule.md) and [backlog](docs/backlog.md)
- [Conventions](docs/conventions.md) and [runbooks](docs/README.md#index)
