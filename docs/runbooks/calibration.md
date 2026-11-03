# Runbook: camera calibration

Tasks: **T-06** (landmark stills and audit-marker survey, Mon 15:45), **T-12** (landmark tool and solver, Mon 23:00), **T-14** (extrinsics accepted or fallback, **Tue 10:00 cut-off**), **T-15** (audit-harness marker walk, Tue 10:30). Requirements: FR-036, FR-037, FR-038, FR-039, NFR-024 to NFR-026. Spec: [Camera calibration](../spec/vigil-spec.md#camera-calibration), [From detection to 3D position](../spec/vigil-spec.md#from-detection-to-3d-position), [UC-10](../spec/vigil-spec.md#uc-10-place-the-cameras-in-the-3d-model-installer-or-homeowner).

**Blocked-by: hardware** (cameras, stills, the scan from [lidar-scan](lidar-scan.md), surveyed audit markers). The solver, landmark proposals and audit error are tested offline on a synthetic camera (`tests/unit/test_calibrate.py`, `tests/unit/test_landmarks.py`).

There are **two separate protocols**. The **product path** is what every home does: nominal FOV plus 6 SAM-proposed landmarks. The **audit harness** is how the benchmark measures that path's accuracy. Audit markers are **never used in the solve** (`vigil spatial calibrate` refuses an audit marker reused as a landmark). The demo never claims an accuracy the audit has not measured.

## 1. Intrinsics (FR-036)

**Primary: nominal FOV.** Focal length from the camera model's datasheet horizontal FOV at 1280 px, centred principal point, no distortion, flagged `intrinsics_source: fov_nominal`. Put the datasheet value in `hfov_deg` for each camera in `config/cameras.yaml` (or pass `--hfov`).

**Optional: lens profile, once per camera *model*.** One checkerboard session of about 20 views on any unit of that model (rigid board; vary distance, tilt and position; cover the image corners), saved to `data/calib/<model>/` (gitignored). Accepted when RMS is under 1.0 px (`intrinsics_source: lens_profile`); otherwise nominal FOV is kept and the rejected RMS is reported. Reuse the same profile for identical units by hand. Record a profile only if the audit shows a camera misses NFR-024 (about 15 minutes per model).

```sh
uv run vigil spatial calibrate <camera> --frames "data/calib/<model>/*.jpg" --pattern 9x6 --square-m 0.025
```

## 2. Extrinsics from 6 landmarks (FR-037)

1. One calibration still per camera from the main stream (T-06), with the landmarks visible.
2. Open the calibration tool (`web/calibrate/`, **LAN only**). SAM 3.1 proposes fixed-landmark masks (`door`, `gate`, `fence post`, `window`, then mask corners) through `POST /api/spatial/landmarks`. Until the edge backend wires `propose_landmarks`, the endpoint answers `blocked` and you click the landmarks by hand (door frames, gate posts, shed or window corners).
3. Accept **6 landmark points** per camera and click each once on the mesh; each pair goes to `POST /api/spatial/pairs`.
4. The solver runs PnP with RANSAC on the 6.

```sh
uv run vigil spatial calibrate <camera> --pairs data/calib/<camera>/pairs.json [--audit data/calib/<camera>/audit.json]
```

| Check | Accept when |
| --- | --- |
| Mean landmark reprojection at 1280 px | Under **6 px** (nominal FOV) or under **4 px** (lens profile) |

| Problem | Action |
| --- | --- |
| Reprojection over threshold | The worst point is dropped and the pose re-solved once; then propose more landmarks |
| Too few landmarks visible | Add a temporary landmark (any box or chair, scanned once) |
| A landmark is hidden | Pick another |
| Mesh unusable | Planar homography from 4 or more ground-level landmarks (`--method homography`) |

## 3. Audit harness (benchmark only, NFR-024 to NFR-026)

- **6 surveyed ground markers per camera** (24 in total), placed and tape-measured into the world frame in T-06 ([lidar-scan](lidar-scan.md#1-place-markers-and-pick-landmarks-first)). Never used for calibration.
- **Held-out ground error** (NFR-024): pass `--audit`; target under **0.25 m** per camera. `locate()` then widens r95 by the measured audit error instead of the landmark error.
- **Marker walk** (T-15, NFR-025, NFR-026): a consenting team member stands on the same 6 markers per camera, in daylight; record each pose on every camera that sees it. `uv run vigil eval --spatial` reports median and p90 position error and the share of points inside the stated r95. Targets (pre-registered in [EVAL.md](../../EVAL.md)): median under 0.5 m within 10 m ⚠️, at least 90% inside r95. Misses are reported.
- **Scale:** 2 tape-measured distances, under 2% (FR-035).
- Any "±0.4 m" label is used only where the audit measured it; otherwise cards show the measured r95.

## 4. Record

`config/calibration.json` per camera: camera matrix, distortion, model, `intrinsics_source` (`fov_nominal` or `lens_profile`), rotation, translation, image size, landmark error, audit errors (when measured), date. It must load and pass `tests/unit/test_calibrate.py`. Commit the calibration report and the audit-harness report (NFR-024) after the `privacy-gate` skill.

## 5. Coverage (FR-038)

```sh
uv run vigil spatial coverage
```

Writes blind-spot polygons to `config/cameras.yaml` (0.25 m grid; visible when inside the image, outside every privacy polygon, with line of sight). Acceptance: the region behind the shed is found, and a walk along its edge agrees.

## The Tue 10:00 cut-off

If landmark PnP has **not passed by Tue 10:00 AM PT**, switch to the measured site-plan fallback and keep going ([spec section 0](../spec/vigil-spec.md#0-baseline-and-scoring-logic)):

- Use the site-plan model ([lidar-scan fallback level 3](lidar-scan.md#7-fallback-ladder)) and ground-plane homographies from 4 or more landmarks.
- Positions still work on flat ground; flag them as fallback in the trace and EVAL.md.
- Do not spend further time on PnP before G2.

## Re-calibration

Re-calibrate a camera whenever it is moved. `vigil spatial check` (P2) compares a reference still against the current view.
