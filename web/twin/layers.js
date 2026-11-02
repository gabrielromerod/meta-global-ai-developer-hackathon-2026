// three.js layers for the house model (FR-040): site plan, coverage, hatched blind regions,
// camera cones, protected footprints, and per-visit discs, paths and gap lines encoded as in
// the spec 7 table. World frame: x along the front wall, y up, z towards the backyard (m).

const Y = { coverage: 0.01, blind: 0.02, footprint: 0.04, disc: 0.05, path: 0.08, gap: 0.08 };
export const COLOURS = {
  coverage: 0x6ea0dc, blind: 0x9aa0a6, cone: 0x4fc3f7, disc: 0xf2b233, gap: 0x9aa0a6,
  building: 0xc9c4b8, fence: 0xa08a6a, protected: 0xf2b233, object: 0x6fa0d8, ground: 0x4d6147,
};

function flatShape(THREE, pts) {
  // Shape lies in XY; after rotateX(-90deg) a shape point (x, -z) lands on world (x, 0, z).
  const shape = new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, -z)));
  const geo = new THREE.ShapeGeometry(shape);
  geo.rotateX(-Math.PI / 2);
  return geo;
}

function loop(THREE, pts, y, material) {
  const geo = new THREE.BufferGeometry().setFromPoints(pts.map(([x, z]) => new THREE.Vector3(x, y, z)));
  const line = new THREE.LineLoop(geo, material);
  line.computeLineDistances();
  return line;
}

function circlePts(cx, cz, r, n = 48) {
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const a = (i / n) * Math.PI * 2;
    out.push([cx + r * Math.cos(a), cz + r * Math.sin(a)]);
  }
  return out;
}

export function buildSitePlan(THREE, twin) {
  const group = new THREE.Group();
  group.name = "site-plan";
  const g = twin.ground || { min: [-12, -12], max: [12, 16] };
  const ground = new THREE.Mesh(
    flatShape(THREE, [[g.min[0], g.min[1]], [g.max[0], g.min[1]], [g.max[0], g.max[1]], [g.min[0], g.max[1]]]),
    new THREE.MeshLambertMaterial({ color: COLOURS.ground }),
  );
  group.add(ground);
  for (const b of (twin.site_plan && twin.site_plan.boxes) || []) {
    const w = b.max[0] - b.min[0];
    const d = b.max[1] - b.min[1];
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(w, b.h, d),
      new THREE.MeshLambertMaterial({ color: COLOURS[b.kind] || 0x999999 }),
    );
    mesh.position.set(b.min[0] + w / 2, b.h / 2, b.min[1] + d / 2);
    mesh.name = b.id;
    group.add(mesh);
  }
  return group;
}

export function buildCoverage(THREE, twin) {
  const group = new THREE.Group();
  group.name = "coverage";
  for (const c of twin.coverage || []) {
    const mesh = new THREE.Mesh(
      flatShape(THREE, c.polygon_m),
      new THREE.MeshBasicMaterial({ color: COLOURS.coverage, transparent: true, opacity: 0.22, depthWrite: false }),
    );
    mesh.position.y = Y.coverage;
    mesh.userData.camera = c.camera_id;
    group.add(mesh);
  }
  return group;
}

function hatchTexture(THREE) {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  ctx.strokeStyle = "#c4c8cc";
  ctx.lineWidth = 5;
  for (let k = -64; k <= 128; k += 16) {
    ctx.beginPath();
    ctx.moveTo(k, 0);
    ctx.lineTo(k + 64, 64);
    ctx.stroke();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(1, 1);
  return tex;
}

export function buildBlindRegions(THREE, twin, labels) {
  const group = new THREE.Group();
  group.name = "blind-regions";
  const tex = hatchTexture(THREE);
  for (const r of twin.blind_regions || []) {
    const fill = new THREE.Mesh(
      flatShape(THREE, r.polygon_m),
      new THREE.MeshBasicMaterial({ map: tex, color: COLOURS.blind, transparent: true, opacity: 0.85, depthWrite: false }),
    );
    fill.position.y = Y.blind;
    group.add(fill);
    group.add(loop(THREE, r.polygon_m, Y.blind + 0.01, new THREE.LineBasicMaterial({ color: COLOURS.blind })));
    const cx = r.polygon_m.reduce((s, p) => s + p[0], 0) / r.polygon_m.length;
    const cz = r.polygon_m.reduce((s, p) => s + p[1], 0) / r.polygon_m.length;
    labels.add(`Blind region · ${r.name}`, [cx, 0.3, cz], "region-label");
  }
  return group;
}

export function coneCorners(cam) {
  const p = cam.position;
  const l = cam.look_at;
  let f = [l[0] - p[0], l[1] - p[1], l[2] - p[2]];
  const fn = Math.hypot(...f);
  f = f.map((v) => v / fn);
  let r = [-f[2], 0, f[0]];
  const rn = Math.hypot(...r) || 1;
  r = r.map((v) => v / rn);
  const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
  const d = (cam.range_m || 8) * 0.55;
  const th = Math.tan(((cam.hfov_deg || 90) * Math.PI) / 360);
  const tv = Math.tan(((cam.vfov_deg || 56) * Math.PI) / 360);
  return [[1, 1], [-1, 1], [-1, -1], [1, -1]].map(([a, b]) =>
    [0, 1, 2].map((i) => p[i] + d * (f[i] + a * th * r[i] + b * tv * u[i])));
}

export function buildCones(THREE, twin, labels) {
  const group = new THREE.Group();
  group.name = "cones";
  const cones = new Map();
  for (const cam of twin.cameras || []) {
    if (!cam.position) continue;
    const p = cam.position;
    const c = coneCorners(cam);
    const verts = [];
    for (let i = 0; i < 4; i += 1) verts.push(...p, ...c[i], ...c[(i + 1) % 4]);
    const faceGeo = new THREE.BufferGeometry();
    faceGeo.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    const faceMat = new THREE.MeshBasicMaterial({
      color: COLOURS.cone, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false,
    });
    const faces = new THREE.Mesh(faceGeo, faceMat);
    const edges = [];
    for (let i = 0; i < 4; i += 1) edges.push(...p, ...c[i], ...c[i], ...c[(i + 1) % 4]);
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute("position", new THREE.Float32BufferAttribute(edges, 3));
    const edgeMat = new THREE.LineBasicMaterial({ color: COLOURS.cone, transparent: true, opacity: 0.8 });
    const lines = new THREE.LineSegments(edgeGeo, edgeMat);
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.25, 0.35), new THREE.MeshLambertMaterial({ color: 0x20476b }));
    body.position.set(...p);
    const g = new THREE.Group();
    g.add(faces, lines, body);
    g.userData.camera = cam.id;
    group.add(g);
    cones.set(cam.id, { faceMat, edgeMat });
    labels.add(cam.name, [p[0], p[1] + 0.5, p[2]], "cam-label");
  }
  return { group, cones };
}

export function buildFootprints(THREE, objects, labels) {
  const group = new THREE.Group();
  group.name = "protected";
  for (const o of objects || []) {
    if (!o.footprint || o.footprint.length < 3) continue;
    const mat = new THREE.LineDashedMaterial({ color: COLOURS.protected, dashSize: 0.15, gapSize: 0.1 });
    group.add(loop(THREE, o.footprint, Y.footprint, mat));
    const cx = o.footprint.reduce((s, p) => s + p[0], 0) / o.footprint.length;
    const cz = o.footprint.reduce((s, p) => s + p[1], 0) / o.footprint.length;
    labels.add(`Protected · ${o.label}`, [cx, 0.6, cz], "pos-label protected-label");
  }
  return group;
}

export function thinPositions(positions) {
  // Keep every 4th single-camera estimate (2 s at 2 Hz) and every 2nd fused or
  // low-confidence one, so the uncertainty discs stay readable.
  let k = 0;
  return positions.filter((p) => {
    k += 1;
    return p.method === "footpoint" ? k % 4 === 1 : k % 2 === 1;
  });
}

export function buildVisitLayer(THREE, data, labels) {
  const group = new THREE.Group();
  group.name = "visit";
  const discs = [];
  for (const p of thinPositions(data.positions || [])) {
    const g = new THREE.Group();
    g.position.set(p.x, Y.disc, p.z);
    if (p.method === "footpoint") {
      const fill = new THREE.Mesh(
        flatShape(THREE, circlePts(0, 0, p.r95)),
        new THREE.MeshBasicMaterial({ color: COLOURS.disc, transparent: true, opacity: 0.22, depthWrite: false }),
      );
      g.add(fill);
      g.add(loop(THREE, circlePts(0, 0, p.r95), 0.01,
        new THREE.LineDashedMaterial({ color: COLOURS.disc, dashSize: 0.08, gapSize: 0.06 })));
    } else if (p.method === "fused") {
      for (const r of [p.r95, p.r95 * 0.6]) {
        g.add(loop(THREE, circlePts(0, 0, r), 0.01, new THREE.LineBasicMaterial({ color: COLOURS.disc })));
      }
    } else {
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(p.r95 * 0.9, p.r95, 48).rotateX(-Math.PI / 2),
        new THREE.MeshBasicMaterial({ color: COLOURS.disc, side: THREE.DoubleSide }),
      );
      g.add(ring);
    }
    g.userData = { t: p.t, label: p.label };
    group.add(g);
    discs.push(g);
  }
  for (const seg of data.paths || []) {
    const geo = new THREE.BufferGeometry().setFromPoints(seg.map(([x, z]) => new THREE.Vector3(x, Y.path, z)));
    group.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: COLOURS.disc })));
  }
  for (const gap of data.gaps || []) {
    if (!gap.from || !gap.to) continue;
    const geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(gap.from[0], Y.gap, gap.from[1]),
      new THREE.Vector3(gap.to[0], Y.gap, gap.to[1]),
    ]);
    const line = new THREE.Line(geo, new THREE.LineDashedMaterial({ color: COLOURS.gap, dashSize: 0.12, gapSize: 0.22 }));
    line.computeLineDistances();
    group.add(line);
    labels.add(gap.label, [(gap.from[0] + gap.to[0]) / 2, 0.4, (gap.from[1] + gap.to[1]) / 2], "gap-label", { gap: gap.id });
  }
  return { group, discs };
}
