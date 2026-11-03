---
name: field-runbook
description: Use when working on physical-world tasks for Vigil - Reolink camera probe or continuous capture, on-camera privacy masks, filming scenarios, iPhone LiDAR scan, checkerboard intrinsics, marker clicking and extrinsic calibration, coverage, the marker walk accuracy test, the 2 h capture endurance or cellular exposure check, GPU probe or local SAM gate H-02.
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
| Reolink probe, on-camera masks, audio off, streams, restreamer, capture | `docs/runbooks/reolink.md` |
| Markers, 4 LiDAR loops, Scaniverse export, scale check, metadata strip | `docs/runbooks/lidar-scan.md` |
| Checkerboard intrinsics, marker-pair extrinsics, marker walk | `docs/runbooks/calibration.md` |
| RTX 3090 H-01 to H-04, gate H-02 | `docs/runbooks/gpu-h01-h04.md` |
| DGX Spark phase D-1 (off by default, owner notice first) | `docs/runbooks/dgx-spark-d1.md` |

## Order, gates and cut-offs (PT)

| Step | Task | Command / tool | Accept when | Cut-off | Fallback |
| --- | --- | --- | --- | --- | --- |
| GPU probe | H-01 | `uv run python scripts/gpu_probe.py` | Report in `eval/hardware/3090.json` | Mon 12:30 | CPU/API backends |
| Reolink probe, masks, audio off | T-04, FR-030 | `uv run vigil reolink probe` | All 4 cameras pass; mask visible in RTSP; no creds in logs | Mon 12:30 | Battery cam -> event clips only |
| Capture | T-05, FR-031 | `uv run vigil reolink capture` | 30 min, no gap > 1 s; 2 h overnight (NFR-029) | Mon 14:00 | FLV stream |
| Markers, LiDAR loops, checkerboard, stills | T-06 | Scaniverse; ~20 board views per camera | Exports in `data/scan/`, `data/calib/`; 2 tape distances written down | Mon 16:30 (before dusk) | Site-plan model |
| Film 12 scenarios, labels first | T-07 | consent first; labels in `eval/labels/` | 12 labelled scenarios | Mon 21:00 | Fewer scenarios, reported |
| Local SAM benchmark | **H-02 gate** | sam3 chunks (see runbook) | 10 s window in <= 10 s; <= 1 extra ID switch vs API | **Mon 22:00** | API SAM (costed); DGX D-1 optional, owner notice |
| 3D build | T-10, FR-035 | `uv run vigil spatial build data/scan` | Scale error < 2%; GLB < 15 MB; no GPS | Mon 20:00 | Site-plan ladder (spec 7) |
| Intrinsics | T-12, FR-036 | `uv run vigil spatial calibrate <camera>` | RMS < 1.0 px | Mon 23:00 | FOV focal, flagged |
| Extrinsics | T-14, FR-037 | calibration tool (`web/calibrate/`, LAN only) | Reprojection < 4 px at 1280; held-out < 0.25 m | **Tue 10:00 hard cut-off** | Measured site-plan + homography |
| Marker walk | T-15, NFR-025/026 | 6 surveyed markers per camera | Recordings in `eval/spatial/` | Tue 11:00 | Report missed |
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
- Tuning calibration past the Tue 10:00 cut-off.
- Committing scans, stills or checkerboard frames from `data/`.
- Turning on the DGX Spark or API SAM bulk runs without the owner and `budget-check`.
- Exposing any camera or edge port to the internet "just for testing".
