# Hackathon record

## Event

| Item | Value |
| --- | --- |
| Event | Meta Global AI Developer Hackathon 2026 ([event page](https://cerebralvalley.ai/e/meta-ai-developer-hackathon)) |
| Build window | Oct 26 to Nov 4, 2026, per the [specification](docs/spec/vigil-spec.md#20-minute-repo-audit-run-first-then-update-the-status-column-in-section-1) |
| Submission deadline | Wed Nov 4, 2026, 2:00 PM PT |
| Track | TBD (Indie or Startup; owner to confirm) |

## Commit range

- **First commit:** `375320f` (2026-11-02 11:54 PT), "chore: initial commit with Vigil specification".
- **Last commit:** TBD, the commit submitted on Nov 4.
- Range for review: `375320f..<submitted commit>`. Every commit in this repository was made during the build window.

## Prior work

**None.** The repository audit run before any code was written found no commits, no source files and an empty remote: [docs/audit/2026-11-02-repo-audit.md](docs/audit/2026-11-02-repo-audit.md). All code was written during the build window, starting 2026-11-02.

Third-party open-source libraries and open model weights are used as dependencies, listed in `pyproject.toml` and the model table below; they are not prior work by the team.

## Contributors

| Who | Role |
| --- | --- |
| gabrielromerod (GitHub) | Repository owner |
| Team | TBD: owner to confirm the team members before submission |

## Consent statement

_Placeholder, to be completed and confirmed by the owner before submission._

All people who appear in the footage, and the team member who reads the 3 voice-rule audio fixtures, are consenting adults from the team, who agreed to be filmed or recorded and to have masked footage and the fixtures published in this repository and the hosted sandbox. Vehicles appear with their plates covered by paper signs reading "VIGIL-01". Consent records are held privately by the team and are not committed.

## Privacy notes

- Footage comes from the team's own home cameras. Privacy masks on the cameras and Vigil's own privacy polygons black out the street, neighbouring properties and the house number; audio is off on the cameras and removed again by Vigil.
- Raw video, scans and calibration frames never leave the edge machine and are not in this repository; only masked, audio-free clips selected for the demo are published.
- Scans and images are stripped of GPS and device metadata, checked in CI.
- Only Standard mode is used for Meta API calls (content not used for training).
- Vigil does not identify anyone and creates no face, voice or body templates. People get a role only from where they came from (the house's own doors, an owner check-in, an expected window, or the perimeter).
- Camera audio is off and removed. Spoken rules go only to Muse Voice Transcribe and are never stored; the only audio files in the repository are the consented fixtures listed in `config/audio_fixtures.json`.
- The home network has no inbound ports; the hosted sandbox never connects to the house.

## Models used

| Model | How it is used | File |
| --- | --- | --- |
| `sam-3.1` (Meta Model API) | Tracking and masks; tap-to-protect; calibration landmark proposals | `vigil/meta/sam.py`, `vigil/spatial/landmarks.py` |
| `muse-spark-1.3` (Meta Model API) | Appearance notes, rule compilation, triage fallback, baseline | `vigil/meta/spark.py` |
| `muse-wonder-1.0` (Meta Model API) | Cited stories, verdict and watch proposals | `vigil/meta/wonder.py` |
| `muse-voice-transcribe-1.0` (Meta Model API) | Voice rules (P0): spoken rule to editable text | `vigil/meta/asr.py` |
| Muse Glimmer 30B, open weights, 4-bit, on a local RTX 3090 | Triage on the home edge and in the benchmark, if gate H-03 passes; otherwise Spark triages and the loop is 4 models | `vigil/meta/glimmer.py` |
| SAM 3.1 open weights, on a local RTX 3090 | Local tracking for live home mode and the benchmark | `vigil/meta/sam_local.py` |

Which models actually ran, on which backend, is recorded per call in the call ledger and summarised in [EVAL.md](EVAL.md); the README states whether the 5-model or the 4-model configuration was used.

## Meta API spend

Credit-funded spend is capped at $140 in code. The owner decided on Nov 2 to keep live calls on during judging (Nov 5–10 PT), charged to the card, under a hard $25 cap ($5 per day, none after Nov 10, 23:59 PT); the ledger tags every call `credit` or `paid`.
