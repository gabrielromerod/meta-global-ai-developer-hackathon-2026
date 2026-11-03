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

All people who appear in the footage are consenting adults from the team, who agreed to be filmed and to have masked footage published in this repository and the hosted sandbox. Vehicles appear with their plates covered by paper signs reading "VIGIL-01". Consent records are held privately by the team and are not committed.

## Privacy notes

- Footage comes from the team's own home cameras. Privacy masks on the cameras and Vigil's own privacy polygons black out the street, neighbouring properties and the house number; audio is off on the cameras and removed again by Vigil.
- Raw video, scans and calibration frames never leave the edge machine and are not in this repository; only masked, audio-free clips selected for the demo are published.
- Scans and images are stripped of GPS and device metadata, checked in CI.
- Only Standard mode is used for Meta API calls (content not used for training).
- Vigil never identifies people and stores no face, age, gender, skin or ethnicity attributes.
- The home network has no inbound ports; the hosted sandbox never connects to the house.

## Models used

| Model | How it is used | File |
| --- | --- | --- |
| `sam-3.1` (Meta Model API) | Tracking and masks; tap-to-protect | `vigil/meta/sam.py` |
| `muse-spark-1.3` (Meta Model API) | Appearance notes, rule compilation, triage fallback, baseline | `vigil/meta/spark.py` |
| `muse-wonder-1.0` (Meta Model API) | Cited stories, verdict and watch proposals | `vigil/meta/wonder.py` |
| `muse-voice-transcribe-1.0` (Meta Model API) | Voice rules (P2) | `vigil/meta/asr.py` |
| Muse Glimmer 30B, open weights, 4-bit, on a local RTX 3090 | Triage | `vigil/meta/glimmer.py` |
| SAM 3.1 open weights, on a local RTX 3090 | Local tracking for live home mode and the benchmark | `vigil/meta/sam_local.py` |

Which models actually ran, on which backend, is recorded per call in the call ledger and summarised in [EVAL.md](EVAL.md).
