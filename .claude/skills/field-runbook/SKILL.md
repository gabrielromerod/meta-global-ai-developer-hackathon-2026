---
name: field-runbook
description: Use when working on physical-world tasks for Vigil - Reolink camera probe or continuous capture, on-camera privacy masks, drawing zone kinds, filming the daylight or night scenarios, recording voice fixtures, iPhone LiDAR scan, landmark alignment, surveying audit markers, optional lens profiles, coverage, the audit-harness marker walk, the 2 h capture endurance or cellular exposure check, GPU probe or local SAM gate H-02.
---

# Field runbook

## Overview

Field work produces data Claude cannot fake. Claude prepares commands, checks results
against gates and records outcomes; the owner does the physical steps. Every step has a
measured acceptance value, a cut-off and a fallback, so a weak field result lowers accuracy,
never the demo.

**Detailed steps live in `docs/runbooks/`.** Read the matching one before starting; this
skill only gives the order, gates and cut-offs:

| Work | Runbook |
| --- | --- |
| Reolink probe, on-camera masks, zone kinds, audio off, streams, restreamer, capture | `docs/runbooks/reolink.md` |
| Landmarks, 6 audit markers per camera, LiDAR loops, Scaniverse export, scale check, metadata strip | `docs/runbooks/lidar-scan.md` |
| Nominal FOV, 6-landmark PnP, optional lens profile, audit harness, marker walk | `docs/runbooks/calibration.md` |
| RTX 3090 H-01 to H-04, gate H-02 | `docs/runbooks/gpu-h01-h04.md` |
| DGX Spark phase D-1 (off by default, owner notice first) | `docs/runbooks/dgx-spark-d1.md` |

## Order, gates and cut-offs (PT)

| Step | Task | Command / tool | Accept when | Cut-off | Fallback |
| --- | --- | --- | --- | --- | --- |
| GPU probe | H-01 | `uv run python scripts/gpu_probe.py` | Report in `eval/hardware/3090.json` | **Done** (Ready, Nov 2) | CPU/API backends |
| Reolink probe, masks, audio off, zone kinds | T-04, FR-030 | `uv run vigil reolink probe` | All 4 cameras pass; mask visible in RTSP; no creds in logs; egress and perimeter zones drawn | Mon 13:45 | Battery cam -> event clips only |
| Capture | T-05, FR-031 | `uv run vigil reolink capture` | Capturing before T-07a; 2 h overnight (NFR-029) | Mon 14:30 | NVR or camera recording export |
| Landmarks, audit markers, LiDAR loops, stills | T-06 | Scaniverse; 6 landmarks and 6 surveyed audit markers per camera | Exports in `data/scan/`, `data/calib/`; survey sheet; 2 tape distances | Mon 15:45 (daylight) | Site-plan model |
| Daylight scenarios A, B, B′, labels first; 3 voice fixtures | T-07a | consent first; labels in `eval/labels/`; WAVs in `demo/voice/` | Labelled before sunset (16:55); fixture hashes in `config/audio_fixtures.json` | Mon 16:50 | Fewer scenarios, reported |
| Night scenarios A′ and C, labels first | T-07b | after about 17:55, cameras in IR | Labelled; r7 window 17:30–06:00 covers both | Mon 19:00 | Fewer scenarios, reported |
| Local SAM benchmark | **H-02 gate** | sam3 chunks (see runbook) | 10 s window in <= 10 s; <= 1 extra ID switch vs API | **Mon 22:00** | API SAM (costed); DGX D-1 optional, owner notice |
| 3D build | T-10, FR-035 | `uv run vigil spatial build data/scan` | Scale error < 2%; GLB < 15 MB; no GPS | Mon 20:00 | Site-plan ladder (spec 7) |
| Intrinsics | T-12, FR-036 | `uv run vigil spatial calibrate <camera>` (`--hfov`) | Nominal FOV, flagged `fov_nominal`; optional lens profile per camera model, RMS < 1.0 px | Mon 23:00 | Nominal FOV |
| Extrinsics | T-14, FR-037 | calibration tool (`web/calibrate/`, LAN only), `--pairs` | Landmark reprojection < 6 px (nominal) or < 4 px (profile) at 1280; audit held-out < 0.25 m | **Tue 10:00 hard cut-off** | Measured site-plan + homography |
| Marker walk (audit harness) | T-15, NFR-025/026 | person on the 6 surveyed markers per camera; never used in the solve | Recordings in `eval/spatial/` | Tue 10:30 | Report missed |
| Coverage | T-17, FR-038 | `uv run vigil spatial coverage` | Shed-back region found; edge walk agrees | Tue 11:00 | Hand-drawn blind polygon, flagged |
| Exposure check | NFR-031, FR-034 | phone on cellular tries edge and camera ports | Nothing reachable | Before the video | Do not record live mode |

**Tue 10:00 rule:** if extrinsics have not passed, switch to the site-plan fallback at
10:00 and keep going. Do not keep tuning. **H-02 rule:** at Mon 22:00 the 3090 passes or
the plan moves to API SAM; the DGX Spark is used only after the owner is notified.

## How Claude helps

1. Read the matching runbook above; list prerequisites to the owner.
2. Run only offline/LAN commands the owner asked for. Never paste credentials into
   commands or logs; they come from `.env`.
3. Compare each result with its gate; write the measured value, date and pass/fail into
   the runbook log, `EVAL.md` (numbers) or `eval/hardware/` (probe JSON).
4. On a miss: apply the fallback in the table, record the switch in `docs/readiness.md`,
   continue with the next step.
5. Raw outputs stay in `data/` (gitignored). Anything bound for the repo goes through the
   `privacy-gate` skill first.

## Red flags

- Marking FR-030 to FR-039 Verified from synthetic tests alone.
- Using an audit marker as a calibration landmark (it voids the held-out error).
- Relabelling a recorded time to fit a rule window (r7 is 17:30–06:00 because C is filmed at about 18:00).
- Tuning calibration past the Tue 10:00 cut-off.
- Committing scans, stills or checkerboard frames from `data/`.
- Turning on the DGX Spark or API SAM bulk runs without the owner and `budget-check`.
- Exposing any camera or edge port to the internet "just for testing".
