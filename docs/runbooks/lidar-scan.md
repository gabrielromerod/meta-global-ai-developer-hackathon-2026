# Runbook: LiDAR scan of the house

Task: **T-06** (Mon 16:30 PT, **before dusk**), then T-10. Requirements: FR-035, NFR-032. Spec: [Scan capture](../spec/vigil-spec.md#scan-capture), [Processing](../spec/vigil-spec.md#processing-vigil-spatial-build), [Fallback ladder](../spec/vigil-spec.md#fallback-ladder-for-the-3d-model), diagram [5.12](../architecture/README.md#512-spatial-build-and-calibration-pipeline).

**Blocked-by: hardware.** Needs an iPhone Pro with LiDAR, Scaniverse (free), markers and a tape measure. The build step needs the optional `spatial` extra (Open3D), which is not installed by default.

## Kit

- iPhone Pro with LiDAR, charged; Scaniverse installed
- 8 ground markers **per camera view** (tape crosses or cones), plus one on the **front-door threshold** (world origin)
- Tape measure; notebook for 2 measured distances
- The printed checkerboard on a rigid board (for [calibration](calibration.md), done in the same session)

## 1. Place markers first

1. Put the origin marker on the front-door threshold.
2. For each camera, place 8 ground markers spread across its view, near and far, all on the ground and visible both to the camera and to the scan. Two of them will be held out for the accuracy check.
3. Measure **2 known distances** between fixed features (for example two fence posts, or two markers far apart) with the tape. Write them down; they are the scale check.
4. Take one calibration still per camera from the main stream while the markers are in place.

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
