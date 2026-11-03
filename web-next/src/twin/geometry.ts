import { Spherical, Vector3 } from "three";
/** Public geometry is generic massing. Coordinates remain the supplied house frame. */
export type Vec2 = [number, number];
export function framingFov(base: number, aspect: number): number {
  return (
    (2 *
      Math.atan(
        Math.tan((base * Math.PI) / 360) / Math.min(1, aspect > 0 ? aspect : 1),
      ) *
      180) /
    Math.PI
  );
}
export type Vec3 = [number, number, number];
export function fitPose(
  pose: OrbitPose,
  ground: Ground,
  height: number,
  fov: number,
  aspect: number,
): OrbitPose {
  const target = new Vector3(...pose.target),
    forward = target
      .clone()
      .sub(new Vector3(...pose.position))
      .normalize(),
    right = forward
      .clone()
      .cross(new Vector3(0, 1, 0))
      .normalize(),
    up = right.clone().cross(forward).normalize();
  const tanV = Math.tan((fov * Math.PI) / 360),
    tanH = tanV * Math.max(aspect, Number.EPSILON);
  let required = 0;
  for (const x of [ground.min[0], ground.max[0]])
    for (const y of [0, height])
      for (const z of [ground.min[1], ground.max[1]]) {
        const relative = new Vector3(x, y, z).sub(target),
          depth = relative.dot(forward);
        required = Math.max(
          required,
          Math.abs(relative.dot(right)) / tanH - depth,
          Math.abs(relative.dot(up)) / tanV - depth,
        );
      }
  const distance = Math.max(
    new Vector3(...pose.position).distanceTo(target),
    required + height,
  );
  return {
    target: pose.target,
    position: target
      .clone()
      .addScaledVector(forward, -distance)
      .toArray() as Vec3,
  };
}
export interface Ground {
  min: Vec2;
  max: Vec2;
}
export interface Box {
  id: string;
  kind: string;
  min: Vec2;
  max: Vec2;
  h: number;
}
export interface SceneCamera {
  id: string;
  name: string;
  position: Vec3;
  look_at: Vec3;
  hfov_deg: number;
  range_m: number;
  source_label: string;
}
export interface BlindRegion {
  id: string;
  name: string;
  polygon_m: Vec2[];
}
export interface TwinModel {
  ground: Ground;
  boxes: Box[];
  cameras: SceneCamera[];
  blindRegions: BlindRegion[];
  coverage: { camera_id: string; polygon_m: Vec2[] }[];
}
export interface OrbitPose {
  position: Vec3;
  target: Vec3;
}
export interface Estimate {
  t: number;
  x: number;
  z: number;
  r95: number;
  method: string;
  label: string;
  camera_ids: string[];
  track_id: string;
}
export interface EvidenceGap {
  id: string;
  t0: number;
  t1: number;
  from: Vec2;
  to: Vec2;
  label: string;
}
type RecordValue = Record<string, unknown>;
export interface ProjectedLabel {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  priority: number;
}
export function layoutLabels(
  labels: ProjectedLabel[],
  width: number,
  height: number,
  margin: number,
): ProjectedLabel[] {
  const placed: ProjectedLabel[] = [];
  for (const label of [...labels].sort((a, b) => b.priority - a.priority)) {
    const fits = (candidate: ProjectedLabel) =>
      !placed.some(
        (other) =>
          candidate.x < other.x + other.width + margin &&
          candidate.x + candidate.width + margin > other.x &&
          candidate.y < other.y + other.height + margin &&
          candidate.y + candidate.height + margin > other.y,
      );
    const candidate = (dx: number, dy: number): ProjectedLabel => ({
      ...label,
      x: clamp(
        label.x - label.width / 2 + dx,
        margin,
        Math.max(margin, width - margin - label.width),
      ),
      y: clamp(
        label.y - label.height / 2 + dy,
        margin,
        Math.max(margin, height - margin - label.height),
      ),
    });
    let result: ProjectedLabel | undefined;
    const stride = Math.max(margin, Math.min(label.width, label.height) / 2);
    for (
      let radius = 0;
      radius <= Math.hypot(width, height) && !result;
      radius += stride
    ) {
      for (let i = 0; i < 16 && !result; i++) {
        const angle = (i * Math.PI) / 8,
          next = candidate(Math.cos(angle) * radius, Math.sin(angle) * radius);
        if (fits(next)) result = next;
      }
    }
    if (result) placed.push(result);
  }
  return placed;
}
const record = (v: unknown): RecordValue =>
  v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as RecordValue)
    : {};
const array = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const number = (v: unknown, fallback = 0) =>
  typeof v === "number" && Number.isFinite(v) ? v : fallback;
const text = (v: unknown, fallback = "") =>
  typeof v === "string" ? v : fallback;
const vec2 = (v: unknown): Vec2 => [number(array(v)[0]), number(array(v)[1])];
const vec3 = (v: unknown): Vec3 => [
  number(array(v)[0]),
  number(array(v)[1]),
  number(array(v)[2]),
];
const polygon = (v: unknown) =>
  array(v)
    .filter(
      (p) =>
        Array.isArray(p) &&
        p.length === 2 &&
        p.every((n) => typeof n === "number" && Number.isFinite(n)),
    )
    .map(vec2);
const clamp = (v: number, min: number, max: number) =>
  Math.max(min, Math.min(max, v));

export function parseTwin(value: unknown): TwinModel {
  const data = record(value),
    ground = record(data.ground);
  return {
    ground: {
      min: vec2(ground.min ?? [-9, -10]),
      max: vec2(ground.max ?? [9, 14]),
    },
    boxes: array(record(data.site_plan).boxes)
      .map(record)
      .filter(
        (b) => Array.isArray(b.min) && Array.isArray(b.max) && number(b.h) > 0,
      )
      .map((b) => ({
        id: text(b.id),
        kind: text(b.kind),
        min: vec2(b.min),
        max: vec2(b.max),
        h: number(b.h),
      })),
    cameras: array(data.cameras)
      .map(record)
      .filter(
        (c) =>
          text(c.id) && Array.isArray(c.position) && Array.isArray(c.look_at),
      )
      .map((c) => ({
        id: text(c.id),
        name: text(c.name, text(c.id)),
        position: vec3(c.position),
        look_at: vec3(c.look_at),
        hfov_deg: clamp(number(c.hfov_deg, 90), 1, 179),
        range_m: Math.max(0, number(c.range_m, 8)),
        source_label: text(c.source_label, "Status unavailable"),
      })),
    blindRegions: array(data.blind_regions)
      .map(record)
      .filter((b) => polygon(b.polygon_m).length >= 3)
      .map((b) => ({
        id: text(b.id),
        name: text(b.name, "Unobserved region"),
        polygon_m: polygon(b.polygon_m),
      })),
    coverage: array(data.coverage)
      .map(record)
      .filter((c) => polygon(c.polygon_m).length >= 3)
      .map((c) => ({
        camera_id: text(c.camera_id),
        polygon_m: polygon(c.polygon_m),
      })),
  };
}

export function clampOrbit(
  pose: OrbitPose,
  ground: Ground,
  minDistance: number,
  maxDistance: number,
  clearance: number,
  polar?: { min: number; max: number },
): OrbitPose {
  const target: Vec3 = [
    clamp(pose.target[0], ground.min[0], ground.max[0]),
    0,
    clamp(pose.target[2], ground.min[1], ground.max[1]),
  ];
  const offset = new Vector3(...pose.position).sub(new Vector3(...pose.target));
  const distance = clamp(
    offset.length() || minDistance,
    minDistance,
    maxDistance,
  );
  const spherical = new Spherical().setFromVector3(offset);
  spherical.radius = distance;
  spherical.phi = clamp(
    spherical.phi,
    polar?.min ?? 0,
    Math.min(
      polar?.max ?? Math.PI / 2,
      Math.acos(Math.min(1, clearance / distance)),
    ),
  );
  const position = new Vector3(...target)
    .add(offset.setFromSpherical(spherical))
    .toArray() as Vec3;
  position[1] = Math.max(clearance, position[1]);
  return { position, target };
}

export function presetPose(name: string, ground: Ground): OrbitPose {
  const x = (ground.min[0] + ground.max[0]) / 2,
    z = (ground.min[1] + ground.max[1]) / 2;
  const span = Math.max(
    ground.max[0] - ground.min[0],
    ground.max[1] - ground.min[1],
  );
  const poses: Record<string, Vec3> = {
    front: [-span * 0.48, span * 0.7, -span * 0.68],
    left: [span * 0.8, span * 0.55, span * 0.16],
    backyard: [span * 0.46, span * 0.65, span * 0.8],
    top: [0, span * 1.05, -span * 0.02],
    right: [-span * 0.8, span * 0.55, span * 0.16],
  };
  const relative = poses[name] ?? poses.front;
  return {
    target: [x, 0, z],
    position: [x + relative[0], relative[1], z + relative[2]],
  };
}

/** Ray distance at the first opaque wall; never projects a cone through the house. */
function wallDistance(origin: Vec2, direction: Vec2, box: Box): number {
  let enter = -Infinity,
    leave = Infinity;
  for (let i = 0; i < 2; i++) {
    if (Math.abs(direction[i]) < 1e-8) {
      if (origin[i] < box.min[i] || origin[i] > box.max[i]) return Infinity;
      continue;
    }
    const a = (box.min[i] - origin[i]) / direction[i],
      b = (box.max[i] - origin[i]) / direction[i];
    enter = Math.max(enter, Math.min(a, b));
    leave = Math.min(leave, Math.max(a, b));
  }
  if (leave < Math.max(enter, 0)) return Infinity;
  return enter >= 0 ? enter : leave > 0 ? 0 : Infinity;
}

export function coneFootprint(
  camera: SceneCamera,
  boxes: Box[],
  ground: Ground,
): Vec2[] {
  const origin: Vec2 = [camera.position[0], camera.position[2]];
  const heading = Math.atan2(
    camera.look_at[0] - origin[0],
    camera.look_at[2] - origin[1],
  );
  const half = (camera.hfov_deg * Math.PI) / 360;
  const points: Vec2[] = [origin];
  for (let i = 0; i <= 32; i++) {
    const angle = heading - half + (2 * half * i) / 32,
      direction: Vec2 = [Math.sin(angle), Math.cos(angle)];
    let distance = camera.range_m;
    for (const box of boxes)
      distance = Math.min(distance, wallDistance(origin, direction, box));
    for (let axis = 0; axis < 2; axis++) {
      const edge = direction[axis] >= 0 ? ground.max[axis] : ground.min[axis];
      if (Math.abs(direction[axis]) > 1e-8)
        distance = Math.min(
          distance,
          Math.max(0, (edge - origin[axis]) / direction[axis]),
        );
    }
    points.push([
      clamp(origin[0] + direction[0] * distance, ground.min[0], ground.max[0]),
      clamp(origin[1] + direction[1] * distance, ground.min[1], ground.max[1]),
    ]);
  }
  return points;
}

/** Diagonal scanlines intersect actual polygon edges, including nonrectangular regions. */
export function hatchSegments(points: Vec2[], spacing: number): [Vec2, Vec2][] {
  if (points.length < 3 || spacing <= 0) return [];
  const values = points.map(([x, z]) => z - x),
    min = Math.min(...values),
    max = Math.max(...values),
    segments: [Vec2, Vec2][] = [];
  for (let offset = min + spacing; offset < max; offset += spacing) {
    const intersections: Vec2[] = [];
    points.forEach((a, i) => {
      const b = points[(i + 1) % points.length],
        av = a[1] - a[0] - offset,
        bv = b[1] - b[0] - offset;
      if ((av <= 0 && bv > 0) || (bv <= 0 && av > 0)) {
        const t = av / (av - bv);
        intersections.push([
          a[0] + t * (b[0] - a[0]),
          a[1] + t * (b[1] - a[1]),
        ]);
      }
    });
    intersections.sort((a, b) => a[0] - b[0]);
    for (let i = 0; i + 1 < intersections.length; i += 2)
      segments.push([intersections[i], intersections[i + 1]]);
  }
  return segments;
}

export function evidenceAtTime(value: unknown, time: number) {
  const data = record(value),
    rawGaps = array(data.gaps).map(record);
  const inGap = (t: number) =>
    rawGaps.some((g) => t > number(g.t0) && t < number(g.t1));
  const all = array(data.positions)
    .map(record)
    .filter(
      (p) =>
        typeof p.x === "number" &&
        typeof p.z === "number" &&
        typeof p.t === "number" &&
        !inGap(number(p.t)),
    )
    .map(
      (p) =>
        ({
          t: number(p.t),
          x: number(p.x),
          z: number(p.z),
          r95: Math.max(0, number(p.r95)),
          method: text(p.method),
          label: text(p.label, "3D estimate"),
          camera_ids: array(p.camera_ids ?? p.cameras).map((c) => text(c)),
          track_id: text(p.track_id),
        }) satisfies Estimate,
    )
    .sort((a, b) => a.t - b.t);
  const positions = all.filter((p) => p.t <= time);
  const paths: Vec2[][] = [];
  let path: Vec2[] = [];
  positions.forEach((p, i) => {
    const previous = positions[i - 1];
    const crossesGap =
      previous &&
      rawGaps.some((g) => previous.t <= number(g.t0) && p.t >= number(g.t1));
    if (previous && (crossesGap || previous.track_id !== p.track_id)) {
      if (path.length > 1) paths.push(path);
      path = [];
    }
    path.push([p.x, p.z]);
  });
  if (path.length > 1) paths.push(path);
  const nearest = all.reduce<Estimate | null>(
    (best, p) =>
      Math.abs(p.t - time) <= 1 &&
      (!best || Math.abs(p.t - time) < Math.abs(best.t - time))
        ? p
        : best,
    null,
  );
  const endpoint = (v: unknown) =>
    Array.isArray(v) &&
    v.length >= 2 &&
    v.slice(0, 2).every((n) => typeof n === "number" && Number.isFinite(n));
  const gaps = rawGaps
    .filter((g) => endpoint(g.from) && endpoint(g.to))
    .map(
      (g) =>
        ({
          id: text(g.id),
          t0: number(g.t0),
          t1: number(g.t1),
          from: vec2(g.from),
          to: vec2(g.to),
          label: text(g.label, "Not observed"),
        }) satisfies EvidenceGap,
    );
  const pulseCameras = [
    ...new Set(
      array(data.events)
        .map(record)
        .filter((e) => Math.abs(number(e.t) - time) <= 1)
        .map((e) => text(e.camera_id))
        .filter(Boolean),
    ),
  ];
  return {
    positions,
    paths,
    current: inGap(time) ? null : nearest,
    gaps,
    gapLabels: rawGaps.map((g) => text(g.label, "Not observed")),
    pulseCameras,
  };
}
