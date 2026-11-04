# Runbook: simplified house model from a LiDAR scan

Requirement: FR-035 (fallback ladder **level 2**: segments aligned without ICP, then a
site plan with heights measured from the scan). Code: `vigil/spatial/massing.py`,
`scripts/build_house_massing.py`. Tests: `tests/unit/test_massing.py`,
`tests/integration/test_consumer_api.py::test_private_house_massing_is_served_to_loopback_only`.
Related: [LiDAR scan](lidar-scan.md), [GLB import](glb-import.md), spec 9.1 `vigil/spatial`.

The goal is a light, **untextured** house that reads as the real home in the 3D views
(volumes, roofs, porch, patio cover, fences, lawn and paving, cameras) without shipping the
scan. The textured scan never leaves `data/`; the React app never loads it.

## Privacy boundary

| Artefact | Where | Who sees it |
| --- | --- | --- |
| Raw scans (`*.glb`, `*.zip`) | `data/scan/` (gitignored) | Nobody but the owner's machine |
| Recipe with real measurements | `data/spatial/massing_recipe.json` | Same |
| Massing (`massing.json`) and QA plan (`massing_plan.png`) | `data/spatial/` | `GET /api/ui/twin?model=house`, **LAN or loopback clients only** |
| Generic public diagram | `config/public_massing.json` | Everyone (hosted sandbox, judges) |

`validate_massing` rejects identifying keys (address, latitude/longitude, GPS, street, house
number, compass/north, textures, images, meshes, `glb_url`), unknown kinds and non-finite
numbers before the API serves anything. The public route keeps `generic_massing: true` and
does not even reveal that a private model exists to a non-LAN client.

Satellite imagery is a **visual check only**: nothing is saved from it and no coordinates on
Earth enter the recipe. (Map providers' terms forbid deriving data from their imagery; open
orthophotos or the owner's own drone photo are the alternatives if a stored reference is ever
needed.)

## Method

### 1. Sample the scan surfaces

`sample_glb_points` draws area-weighted random points on every triangle of each segment
(default 1,500 per m²) and reads the base-colour texel under each point. Only numbers leave
this step: positions and an RGB per point.

### 2. Align the segments (yaw + translation)

Phone LiDAR apps export gravity-aligned meshes, so two loops differ only by a rotation about
the vertical axis, a horizontal shift and a ground-height offset. Two loops of a house (front,
back and side) share too little surface for ICP, so the pose comes from **walls**:

1. Keep points 0.5 to 2.0 m above the local ground: walls and fences, no lawn, no roof.
2. `axis_angle` fits each long wall's direction (SVD of its points). The difference between
   the same wall's angle in both segments is the yaw. Check it on two perpendicular walls
   (front facade and side passage): the two estimates must agree to about 0.1°.
3. `wall_peaks` histograms the wall points along X and Z. Matching peaks (for example the
   house's side wall, or the side gate seen from both loops) give the translation.
4. The ground offset comes from `ground_level`: a low percentile of the points in a small
   region right next to the house in each segment (the porch, the patio). Both are set to 0.
5. Verify visually: overlay the two top-down orthophotos. Walls must continue across the
   seam; a doubled wall means a wrong peak was paired.

Write the result in the recipe as `rotate_deg` and `translate` per segment. A brute-force
overlap score is not reliable when the overlap is a narrow passage; the wall-line method is.

### 3. House frame

`house_frame(door, front_angle_deg, base_y)` builds the Vigil frame from spec 7: origin at the
**front door threshold**, +Y up, **+Z into the house** (the street is at −Z, as in the generic
diagram) and +X completing a right-handed frame. It is a pure rotation (the front wall is
levelled to X, then turned 180° about Y): **never a mirror**. Camera names keep their meaning
from the house's point of view ("left" is the left side looking out of the front door).

### 4. Trace the plan (operator step)

On the top-down orthophoto in the house frame (1 m grid), an operator traces rectangles in
metres:

- **Buildings**: the main body and each wing. Walls are where the wall histogram peaks.
- **Porch** (roof slab and posts), **pergola** (patio cover), **doors** (front door, garage
  door: a line on the facade with a height).
- **Fences and gates**: segments; `observed: false` when the scan did not see that stretch.
- **Surfaces**: driveway, walkway, lawns, beds, patio. Leave `kind` out to classify it.
- **Trees** and other tall objects (cluster centre, radius, height).
- **Cameras**: position and look-at point. They are **nominal** (`placement_measured: false`)
  until marked on the scan or calibrated (FR-036/037).

### 5. Measure what the scan can see

`build_massing` fills in what the recipe leaves blank:

| Quantity | How | Why this estimator |
| --- | --- | --- |
| Eave (wall top) | Points within 0.4 m of the footprint edges are cut into 0.5 m stretches; each stretch reports its 98th-percentile height; the eave is the **median** of the stretches | Gables, gutters and shrubs touch only a few stretches, so the median ignores them |
| Gable-fronted wings | `eave_from: <body>`: a wing whose street face is a gable shares the body's eave | Its street face is mostly gable and would read too high |
| Fence height | 97th percentile of points within 0.25 m of the segment | Fences are thin and uniform |
| Surface kind | Majority of ground texels: green → lawn; high luminance variance → gravel; else paving | Coarse on purpose; dry or patchy lawn may need `kind` set by hand |

### 6. Infer what the scan cannot see

A handheld scan does not see the roof. Roofs are **inferred**: `hip` for the main body and
`gable_x`/`gable_z` for wings, with an assumed pitch (default 4:12) and a 0.4 m overhang.
**Check:** the inferred gable peak of a wing should match the peak the scan saw on its street
face. Every assumption is listed in `detail.notes.assumed` and shown in the UI as
"approximate".

**Aerial check (visual only):** look at the house from above (satellite view or the owner's own
drone photo). Do not save it. Correct in the recipe:

- **Roof form per volume:** a straight ridge line that reaches an edge means a gable (`gable_z`
  or `gable_x`); ridges that split into a "V" at the corners mean a hip.
- **Porch roofs:** `porches[].roof`.
- **Solar arrays:** `solar[]`, as plan rectangles. They are drawn on the roof slope.
- **Solid or slatted patio covers:** `pergolas[].style`.
- **Trees the scan missed.**

Check the scale too: the roof outline in pixels divided by the scanned wall width should agree
along both axes within a few percent. Roof overhangs make roofs look about 2 × 0.4 m wider than
the walls.

### 7. Build, check, serve

```sh
uv run python scripts/build_house_massing.py data/spatial/massing_recipe.json
```

It prints the measured eaves, fence heights and surface kinds and writes
`data/spatial/massing_plan.png`: the orthophoto with the traced plan on top (blue: buildings,
red: fences, yellow: surfaces, white: cameras). Every outline must sit on the scan. Then open
Home and choose **My house**. The switch appears only on a LAN or loopback client when
`data/spatial/massing.json` exists. Visit replays of the **demo** data stay on the generic
diagram, because their routes were authored for it. Replays of real evidence use the private
house.

## Toward photos instead of LiDAR

The same recipe can be produced from ordinary photos. Every model stays in its documented role.

| Step | Who | Output |
| --- | --- | --- |
| Find structure in each photo | **SAM 3.1** segments walls, doors, garage door, fences, gates and cameras (the same "SAM proposes landmarks" role as FR-037) | Masks and boxes |
| Describe what was found | **Muse Spark** reads a photo with SAM's tags and returns JSON from an enum (`wall`, `door`, `garage_door`, `fence`, `camera_mount`, `lawn`, `paving`) | Typed features per photo |
| Measure and place | **Code**: multi-view geometry, or the owner's 2 tape measurements for scale, turns the features into house-frame rectangles; `build_massing` fills in heights | `massing_recipe.json` |
| Fill gaps and review | **Muse Wonder** receives only the recipe JSON (**never pixels**) and may propose missing pieces (for example "a gate likely closes this fence line"). Proposals pass an allowlist and are shown to the owner as suggestions, like FR-020 watches | Suggested recipe edits |

Cameras would be identified by SAM and Spark on the photos (`camera_mount`) and then placed by
calibration (FR-036/037), never by a model's guess. Nothing identifies a person: the inputs
are pictures of the building, and the privacy review of FR-003 applies to every photo first.

## Acceptance

Status stays **Not verified** for field use until the owner checks the plan against the
property (tape measurements or a manual walk-through, logged with a date in
`docs/readiness.md`). The camera placement stays nominal until calibration.
