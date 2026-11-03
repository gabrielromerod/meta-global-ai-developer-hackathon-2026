# Import an uncompressed house GLB

Evidence: FIXTURE only. Generated floor/wall geometry passes through the importer, locate,
coverage, export and the WebGL viewer. Real scan acceptance remains Not verified.

In a local JSON file under data/, provide `origin`, `x_point`, and `up_point`: three scan
coordinates for the front-door origin, a point along the front wall (+X), and a point
above the origin (+Y). The importer applies `world_frame` to both raycasting geometry and
the displayed GLB, preserving the GLB's own node transforms.

CMD, when the owner supplies and reviews the scan:

```cmd
uv run vigil spatial import-glb data\scan.glb --frame data\frame.json --out data\spatial
uv run vigil spatial coverage --site-plan data\spatial\model.glb --grid-out data\coverage.json
```

Coverage also needs camera calibration next to cameras.yaml (or `--calibration PATH`).
Processing automatically uses data/spatial/model.glb when calibration.json is present;
session export copies the imported asset and sets `twin.glb_url`. No extra library or
weights are installed.

The importer accepts embedded static triangle meshes below **15,000,000 bytes**. Draco,
meshopt, external resources, skinning and sparse geometry are refused with named errors;
the viewer displays GLB errors instead of silently hiding them. Ground extraction uses
the lowest approximate horizontal plane, within 0.3 m and at most 35 degrees slope.
Review steps, multiple levels and nonplanar terrain against the real scan before relying
on positions or coverage. Imported files stay in gitignored data/; publishing still needs
the privacy gate and the owner's frame/texture review.
