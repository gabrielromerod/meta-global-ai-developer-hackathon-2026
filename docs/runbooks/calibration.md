# Runbook: camera calibration

Tasks: **T-06** (views and stills), **T-12** (tool and solver, Mon 23:00), **T-14** (extrinsics accepted or fallback, **Tue 10:00 cut-off**), **T-15** (marker walk). Requirements: FR-036, FR-037, FR-038, FR-039, NFR-024 to NFR-026. Spec: [Camera calibration](../spec/vigil-spec.md#camera-calibration), [From detection to 3D position](../spec/vigil-spec.md#from-detection-to-3d-position), [UC-10](../spec/vigil-spec.md#uc-10-build-the-3d-model-and-calibrate-the-cameras-installer).

**Blocked-by: hardware** (cameras, checkerboard, markers, the scan from [lidar-scan](lidar-scan.md)). The solver itself is tested offline on a synthetic camera (`test_calibrate.py`).

## 1. Intrinsics (FR-036)

1. Print a checkerboard and mount it on a **rigid** board (any bend ruins the fit). Note the square size and inner-corner count.
2. For each camera, capture about **20 views** from the **main stream**: vary distance, tilt and position, and cover the corners of the image.
3. Save frames to `data/calib/<camera_id>/` (gitignored).
4. Solve with the OpenCV standard model, or the fisheye model for very wide lenses.

| Result | Action |
| --- | --- |
| RMS reprojection under 1.0 px | Accept |
| Otherwise | Fallback: focal length from the lens field of view, no distortion; **flag low accuracy** in `calibration.json` and the trace |

## 2. Extrinsics (FR-037)

1. Use the 8 ground markers per camera placed during the scan and the calibration still per camera.
2. Open the calibration tool (`web/calibrate/`, **LAN only**; it posts to `POST /api/spatial/pairs`, which is bound to the LAN interface).
3. For each marker, click it in the still, then click the same marker on the mesh.
4. The solver runs PnP with RANSAC on **6 points** and **holds out 2**.

| Check | Accept when |
| --- | --- |
| Mean reprojection | Under 4 px at 1280 px width |
| Held-out ground error | Under 0.25 m |

| Problem | Action |
| --- | --- |
| Held-out error over 0.25 m | Add markers and redo |
| A marker is hidden in the still | Pick another fixed feature visible in both |
| Mesh unusable | Planar homography from 4 or more markers |

## 3. Record

`config/calibration.json` per camera: camera matrix, distortion, model (standard or fisheye), rotation, translation, image size, intrinsic RMS, reprojection and held-out errors, date. Pass: it loads and passes `test_calibration.py`. Commit the calibration report written by `vigil spatial calibrate` (NFR-024).

## 4. Coverage (FR-038)

```sh
uv run vigil spatial coverage
```

Writes blind-spot polygons to `config/cameras.yaml` (0.25 m grid; visible when inside the image, outside every privacy polygon, with line of sight). Acceptance: the region behind the shed is found, and a walk along its edge agrees.

## 5. Marker walk for 3D accuracy (T-15, NFR-025, NFR-026)

1. A consenting team member stands on **6 surveyed markers per camera** that were **not** used for calibration.
2. Record each pose on all cameras that see it.
3. `uv run vigil eval --spatial` reports median and p90 position error and the share of points inside their stated 95% radius.
4. Targets were pre-registered in [EVAL.md](../../EVAL.md) before measuring: median under 0.5 m within 10 m ⚠️, at least 90% inside r95. Misses are reported, not hidden.

## The Tue 10:00 cut-off

If extrinsic calibration has **not passed by Tue 10:00 AM PT**, switch to the measured site-plan fallback and keep going ([spec section 0](../spec/vigil-spec.md#0-baseline-and-scoring-logic)):

- Use the site-plan model ([lidar-scan fallback level 3](lidar-scan.md#7-fallback-ladder)) and ground-plane homographies from 4 or more markers.
- Positions still work on flat ground; flag them as fallback in the trace and EVAL.md.
- Do not spend further time on PnP before G2.

## Re-calibration

Re-calibrate a camera whenever it is moved. `vigil spatial check` (P2) compares a reference still against the current view.
