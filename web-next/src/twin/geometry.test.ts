import { describe, expect, it } from "vitest";
import { PerspectiveCamera, Vector3, Spherical } from "three";
import { OrbitControls } from "three-stdlib";
import fixture from "../fixtures/twin.json";
import {
  parseTwin,
  clampOrbit,
  presetPose,
  coneFootprint,
  evidenceAtTime,
  hatchSegments,
  layoutLabels,
  framingFov,
  fitPose,
} from "./geometry";

describe("FR-040 generic house geometry and bounded orbit", () => {
  it("constrains the top preset before fitting so real OrbitControls does not change its orientation", () => {
    const ground = {
        min: [-9, -10] as [number, number],
        max: [9, 14] as [number, number],
      },
      aspect = 0.665,
      fov = framingFov(42, aspect);
    const legal = clampOrbit(presetPose("top", ground), ground, 8, 55, 0.6, {
      min: 0.08,
      max: 1.48,
    });
    const angle = new Spherical().setFromVector3(
      new Vector3(...legal.position).sub(new Vector3(...legal.target)),
    ).phi;
    expect(angle).toBeGreaterThanOrEqual(0.08 - 1e-10);
    const fitted = fitPose(legal, ground, 3, fov, aspect),
      camera = new PerspectiveCamera(fov, aspect, 0.1, 300),
      controls = new OrbitControls(camera);
    controls.minPolarAngle = 0.08;
    controls.maxPolarAngle = 1.48;
    controls.minDistance = 8;
    controls.maxDistance = 55;
    camera.position.fromArray(fitted.position);
    controls.target.fromArray(fitted.target);
    controls.update();
    expect(
      camera.position.distanceTo(new Vector3(...fitted.position)),
    ).toBeLessThan(1e-8);
    camera.updateMatrixWorld();
    for (const x of [-9, 9])
      for (const y of [0, 3])
        for (const z of [-10, 14]) {
          const projected = new Vector3(x, y, z).project(camera);
          expect(Math.abs(projected.x)).toBeLessThan(1);
          expect(Math.abs(projected.y)).toBeLessThan(1);
        }
  });
  it("preserves horizontal framing on a narrow phone canvas without changing world coordinates", () => {
    const fov = framingFov(42, 0.58);
    const horizontal =
      (2 * Math.atan(Math.tan((fov * Math.PI) / 360) * 0.58) * 180) / Math.PI;
    expect(horizontal).toBeCloseTo(42);
    expect(framingFov(42, 2)).toBe(42);
  });
  it.each(["front", "left", "backyard", "top"])(
    "fits the entire generic property in the narrow %s preset",
    (name) => {
      const ground = {
          min: [-9, -10] as [number, number],
          max: [9, 14] as [number, number],
        },
        aspect = 0.6,
        fov = framingFov(42, aspect),
        pose = fitPose(presetPose(name, ground), ground, 3, fov, aspect);
      const camera = new PerspectiveCamera(fov, aspect, 0.1, 300);
      camera.position.fromArray(pose.position);
      camera.lookAt(new Vector3(...pose.target));
      camera.updateMatrixWorld();
      for (const x of [-9, 9])
        for (const y of [0, 3])
          for (const z of [-10, 14]) {
            const p = new Vector3(x, y, z).project(camera);
            expect(Math.abs(p.x)).toBeLessThanOrEqual(0.96);
            expect(Math.abs(p.y)).toBeLessThanOrEqual(0.96);
          }
    },
  );
  it("keeps all seven configured cameras and the physical right tree barrier", () => {
    const twin = parseTwin(fixture);
    expect(twin.cameras.map((c) => c.id)).toEqual(
      fixture.cameras.map((c) => c.id),
    );
    expect(twin.boxes.find((b) => b.kind === "tree_barrier")?.id).toBe(
      "right_trees",
    );
    expect(twin.blindRegions.some((b) => b.id === "right_trees")).toBe(false);
  });
  it("returns an explicit empty model instead of fabricated cameras for empty inputs", () => {
    expect(parseTwin({}).cameras).toEqual([]);
    expect(parseTwin({}).boxes).toEqual([]);
  });
  it("clamps the target to the ground and the camera above it after downward drag and pan", () => {
    const result = clampOrbit(
      { position: [80, -12, -100], target: [50, -30, 90] },
      { min: [-9, -10], max: [9, 14] },
      8,
      55,
      0.6,
    );
    expect(result.position[1]).toBeGreaterThanOrEqual(0.6);
    expect(result.target[1]).toBe(0);
    expect(result.target[0]).toBeLessThanOrEqual(9);
    expect(result.target[2]).toBeLessThanOrEqual(14);
    const distance = Math.hypot(
      ...result.position.map((n, i) => n - result.target[i]),
    );
    expect(distance).toBeLessThanOrEqual(55.00001);
    expect(distance).toBeGreaterThanOrEqual(8);
  });
  it.each(["front", "left", "backyard", "top", "right"])(
    "keeps the %s preset above ground and inside zoom bounds",
    (name) => {
      const pose = presetPose(name, { min: [-9, -10], max: [9, 14] });
      expect(pose.position[1]).toBeGreaterThan(0);
      expect(
        Math.hypot(...pose.position.map((n, i) => n - pose.target[i])),
      ).toBeLessThan(55);
    },
  );
  it("clips nominal cone footprints to ground bounds and opaque house walls", () => {
    const twin = parseTwin(fixture);
    for (const camera of twin.cameras) {
      const points = coneFootprint(camera, twin.boxes, twin.ground);
      expect(points.length).toBeGreaterThan(3);
      for (const [x, z] of points) {
        expect(x).toBeGreaterThanOrEqual(twin.ground.min[0]);
        expect(x).toBeLessThanOrEqual(twin.ground.max[0]);
        expect(z).toBeGreaterThanOrEqual(twin.ground.min[1]);
        expect(z).toBeLessThanOrEqual(twin.ground.max[1]);
        expect(x > -3.00001 && x < 2.99999 && z > 0.00001 && z < 6.99999).toBe(
          false,
        );
      }
    }
  });
  it("hatches only inside the blind polygon", () => {
    const lines = hatchSegments(
      [
        [0, 0],
        [2, 0],
        [2, 2],
        [0, 2],
      ],
      0.5,
    );
    expect(lines.length).toBeGreaterThan(2);
    for (const line of lines)
      for (const [x, z] of line) {
        expect(x).toBeGreaterThanOrEqual(0);
        expect(x).toBeLessThanOrEqual(2);
        expect(z).toBeGreaterThanOrEqual(0);
        expect(z).toBeLessThanOrEqual(2);
      }
  });
  it("lays out clustered projected camera controls without overlaps or clipping", () => {
    const labels = Array.from({ length: 12 }, (_, i) => ({
      id: String(i),
      x: 195,
      y: 140,
      width: i < 7 ? 40 : 100,
      height: 40,
      priority: i < 7 ? 10 : 1,
    }));
    const arranged = layoutLabels(labels, 390, 280, 8);
    expect(arranged.length).toBe(12);
    for (const item of arranged) {
      expect(item.x).toBeGreaterThanOrEqual(8);
      expect(item.x + item.width).toBeLessThanOrEqual(382);
      expect(item.y).toBeGreaterThanOrEqual(8);
      expect(item.y + item.height).toBeLessThanOrEqual(272);
      for (const other of arranged.filter((o) => o.id !== item.id))
        expect(
          item.x < other.x + other.width &&
            item.x + item.width > other.x &&
            item.y < other.y + other.height &&
            item.y + item.height > other.y,
        ).toBe(false);
    }
  });
});

describe("FR-040 evidence and shared clock", () => {
  const data = {
    positions: [
      {
        t: 0,
        x: 4,
        z: 2,
        r95: 1,
        method: "footpoint",
        camera_ids: ["side_left"],
      },
      {
        t: 12,
        x: 4,
        z: 8,
        r95: 1,
        method: "footpoint",
        camera_ids: ["side_left"],
      },
    ],
    paths: [
      [
        [4, 2],
        [4, 8],
      ],
    ],
    gaps: [
      {
        id: "g",
        t0: 2,
        t1: 10,
        from: [4, 2],
        to: [4, 8],
        label: "Not observed · 8 s",
      },
    ],
    events: [{ t: 0, camera_id: "side_left" }],
  };
  it("never draws a continuous path or a position through an unobserved interval", () => {
    const view = evidenceAtTime(data, 6);
    expect(view.current).toBeNull();
    expect(view.paths).toEqual([]);
    expect(view.gaps[0].label).toBe("Not observed · 8 s");
  });
  it("does not fabricate endpoints for a gap that has no observed endpoints", () => {
    const view = evidenceAtTime(
      {
        gaps: [
          { id: "battery", t0: 1, t1: 8, label: "Not observed · battery wake" },
        ],
      },
      4,
    );
    expect(view.gaps).toEqual([]);
    expect(view.gapLabels).toEqual(["Not observed · battery wake"]);
  });
  it("accepts observed gap endpoints with their API timestamps and only keeps x/z", () => {
    const view = evidenceAtTime(
      {
        gaps: [
          {
            id: "g",
            t0: 2,
            t1: 10,
            from: [4, 2, 2],
            to: [4, 8, 10],
            label: "Not observed · 8 s",
          },
        ],
      },
      6,
    );
    expect(view.gaps[0].from).toEqual([4, 2]);
    expect(view.gaps[0].to).toEqual([4, 8]);
  });
  it("pulses only cameras with a cited event near the current time", () => {
    expect(evidenceAtTime(data, 0).pulseCameras).toEqual(["side_left"]);
    expect(evidenceAtTime(data, 6).pulseCameras).toEqual([]);
  });
});
