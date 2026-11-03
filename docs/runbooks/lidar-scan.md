# Runbook: LiDAR scan of the house

Task: **T-06** (done by **Mon 15:45 PT**, in the daylight block, before sunset at 16:55), then T-10. Requirements: FR-035, FR-037 (landmarks), NFR-024 to NFR-026 (audit markers), NFR-032. Spec: [Scan capture](../spec/vigil-spec.md#scan-capture), [Processing](../spec/vigil-spec.md#processing-vigil-spatial-build), [Camera calibration](../spec/vigil-spec.md#camera-calibration), [Fallback ladder](../spec/vigil-spec.md#fallback-ladder-for-the-3d-model), diagram [5.12](../architecture/README.md#512-spatial-build-and-calibration-pipeline).

**Blocked-by: hardware.** Needs an iPhone Pro with LiDAR, Scaniverse (free), tape crosses or cones and a tape measure. The build step needs the optional `spatial` extra (Open3D), which is not installed by default, and `build_model` is still blocked in code (see [readiness](../readiness.md#remaining-gaps-no-credits-or-hardware-needed-to-start)).

## Kit

- iPhone Pro with LiDAR, charged; Scaniverse installed
- **6 audit markers per camera** (24 in total: tape crosses or cones on the ground), plus one on the **front-door threshold** (world origin)
- Tape measure and a marker survey sheet; notebook for 2 measured distances
- Optional: a checkerboard on a rigid board, only for a lens profile per camera *model* ([calibration](calibration.md#1-intrinsics-fr-036))

## 1. Place markers and pick landmarks first

1. Put the origin marker on the front-door threshold.
2. **Landmarks (product path, FR-037):** for each camera, check that at least 6 fixed landmarks are visible both in the camera view and to the scan: door frames, gate posts, shed corners, window corners. These are what the calibration solves on.
3. **Audit markers (benchmark only, NFR-024 to NFR-026):** for each camera, place 6 ground markers spread across its view, near and far. **Survey** each one into the world frame with the tape (distances from the origin and from fixed features) and write them on the survey sheet. They are **never used in the solve**; they give the held-out ground error and are the stand points for the T-15 marker walk. Leave them in place or mark their positions so they can be re-placed on Tuesday.
4. Measure **2 known distances** between fixed features (for example two fence posts) with the tape: the scale check.
5. Take one calibration still per camera from the main stream with the markers in place.

## 2. Scan 4 loops

- Scan 4 short **closed loops**: front, left side, right side, backyard.
- Each loop overlaps its neighbour by at least **3 fixed features** (corners, posts, steps).
- Scan in shade or late afternoon (⚠️ sunlight degrades LiDAR); walk slowly; keep the phone **1 to 3 m** from surfaces.
- Known limits: about 5 m range, about 0.5 cm local precision on flat surfaces, drift on large or complex walks. Roofs and upper floors will be missing; ground, walls, fences and the shed are what matter.

## 3. Export from Scaniverse

- Export each loop as **GLB** or **PLY** (Scaniverse also offers OBJ and LAS).
- Copy to `data/scan/` on the workstation. `data/` is gitignored; raw scans never enter the repository.
- ⚠️ Confirm the export keeps metric scale (next step).

## 4. Scale check

Measure the same 2 distances on the exported model (Open3D, or any mesh viewer with a measure tool).

| Result | Action |
| --- | --- |
| Error under 2% on both | Accept |
| 2% or more | `vigil spatial build` rescales from the 2 measured distances; record the factor |

## 5. Build

```sh
uv run vigil spatial build        # FR-035; needs the spatial extra (Open3D)
```

1. Load the 4 segments; check scale; rescale if needed.
2. Register: coarse alignment from 3 clicked point pairs, then ICP; record the fit error.
3. World frame: origin at the front-door marker, +X along the front wall, +Y up (glTF convention).
4. Ground mesh as the ray-cast target, plus a 0.1 m height grid.
5. Simplify and compress to a **GLB under 15 MB**, downscale textures, **strip GPS and device metadata**.

## 6. Metadata strip and check (NFR-032)

- The build strips metadata; verify it independently before anything leaves `data/`:

```sh
exiftool -a -G1 -s demo/<model>.glb     # expect no GPS*, Make, Model, Serial or location tags
bash scripts/metadata_scan.sh demo      # same check as CI step 5
```

- No house number, no street-facing frame and no texture that shows a neighbour.

## 7. Fallback ladder

| Level | When | What |
| --- | --- | --- |
| 1 | Registration works | All 4 segments in one mesh |
| 2 | Registration fails | Segments kept separate, each aligned to a tape-measured site plan |
| 3 | No usable scan | Site plan from tape measurements (house footprint, fences, shed as boxes); calibration uses the ground plane and homographies |

The demo survives at every level. Record which level was used in [readiness](../readiness.md) and EVAL.md.
