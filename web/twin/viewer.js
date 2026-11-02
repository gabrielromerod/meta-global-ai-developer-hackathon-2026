// House model viewer (FR-040). three.js with GLTFLoader and OrbitControls (vendored, pinned
// 0.180.0); a top-down 2D canvas map is drawn from the same data when WebGL is unavailable
// or fails (spec 4 fallbacks). Labels are DOM elements so they stay readable and testable.

import { renderLegend } from "./legend.js";
import { coneCorners, thinPositions } from "./layers.js";

class Labels {
  constructor(container) {
    this.layer = document.createElement("div");
    this.layer.className = "twin-labels";
    container.appendChild(this.layer);
    this.items = [];
  }
  add(text, world, cls = "", data = {}) {
    const el = document.createElement("span");
    el.className = `twin-label ${cls}`.trim();
    el.textContent = text;
    for (const [k, v] of Object.entries(data)) el.dataset[k] = v;
    this.layer.appendChild(el);
    const item = { el, world, group: data.group || null };
    this.items.push(item);
    return item;
  }
  clear(group) {
    this.items = this.items.filter((it) => {
      if (it.group === group) { it.el.remove(); return false; }
      return true;
    });
  }
  update(project) {
    for (const it of this.items) {
      const s = it.world ? project(it.world) : null;
      if (!s) { it.el.style.display = "none"; continue; }
      it.el.style.display = "";
      it.el.style.left = `${s[0]}px`;
      it.el.style.top = `${s[1]}px`;
    }
  }
}

function webglAvailable() {
  if (new URLSearchParams(location.search).get("twin") === "2d") return false;
  try {
    const c = document.createElement("canvas");
    return Boolean(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch {
    return false;
  }
}

function nearest(items, t, maxDt = 1.0) {
  let best = null;
  let bestDt = maxDt;
  for (const it of items) {
    const dt = Math.abs(it.t - t);
    if (dt <= bestDt) { best = it; bestDt = dt; }
  }
  return best;
}

// ---------------------------------------------------------------------------
// WebGL viewer
// ---------------------------------------------------------------------------

async function createWebGL(container, twin, labels) {
  const THREE = await import("three");
  const { OrbitControls } = await import("three/addons/controls/OrbitControls.js");
  const { GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js");
  const L = await import("./layers.js");

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.insertBefore(renderer.domElement, labels.layer);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x101418);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 300);
  camera.position.set(-6, 24, -16);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0.5, 0, 4);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x334433, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(-8, 20, -6);
  scene.add(sun);

  const base = new THREE.Group();
  scene.add(base);
  const fallbackPlan = () => base.add(L.buildSitePlan(THREE, twin));
  if (twin.glb_url) {
    new GLTFLoader().load(twin.glb_url, (gltf) => base.add(gltf.scene), undefined, fallbackPlan);
  } else {
    fallbackPlan();
  }
  scene.add(L.buildCoverage(THREE, twin));
  scene.add(L.buildBlindRegions(THREE, twin, labels));
  const { group: coneGroup, cones } = L.buildCones(THREE, twin, labels);
  scene.add(coneGroup);
  let footprints = L.buildFootprints(THREE, twin.protected_objects, labels);
  scene.add(footprints);

  let visit = null;
  let discs = [];
  let posLabel = null;
  let highlighted = null;
  const pulses = new Map();

  function resize() {
    const w = container.clientWidth || 600;
    const h = container.clientHeight || 380;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  const v = new THREE.Vector3();
  function project(world) {
    v.set(world[0], world[1], world[2]).project(camera);
    if (v.z > 1 || v.z < -1) return null;
    const w = container.clientWidth;
    const h = container.clientHeight;
    return [(v.x * 0.5 + 0.5) * w, (-v.y * 0.5 + 0.5) * h];
  }

  let frames = 0;
  function animate(now) {
    controls.update();
    for (const [id, until] of pulses) {
      const c = cones.get(id);
      if (!c) continue;
      if (now > until) {
        pulses.delete(id);
        c.faceMat.opacity = id === highlighted ? 0.3 : 0.12;
      } else {
        c.faceMat.opacity = 0.15 + 0.25 * (0.5 + 0.5 * Math.sin(now / 120));
      }
    }
    renderer.render(scene, camera);
    labels.update(project);
    frames += 1;
    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);

  return {
    mode: "webgl",
    frames: () => frames,
    showVisit(data) {
      if (visit) scene.remove(visit);
      labels.clear("visit");
      const built = L.buildVisitLayer(THREE, data, {
        add: (text, world, cls, extra = {}) => labels.add(text, world, cls, { ...extra, group: "visit" }),
      });
      visit = built.group;
      discs = built.discs;
      scene.add(visit);
      posLabel = labels.add("", null, "pos-label", { group: "visit" });
      const pts = data.positions || [];
      if (pts.length) {
        const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
        const cz = pts.reduce((s, p) => s + p.z, 0) / pts.length;
        controls.target.set(cx, 0, cz);
        camera.position.set(cx - 5, 16, cz - 11);
      }
    },
    setTime(t) {
      for (const d of discs) d.scale.setScalar(1);
      const hit = nearest(discs.map((d) => ({ t: d.userData.t, d })), t, 1.5);
      if (posLabel) {
        if (hit) {
          hit.d.scale.setScalar(1.35);
          posLabel.el.textContent = hit.d.userData.label;
          posLabel.world = [hit.d.position.x, 0.9, hit.d.position.z];
        } else {
          posLabel.world = null;
        }
      }
    },
    highlightCamera(id) {
      highlighted = id;
      for (const [cid, c] of cones) {
        c.faceMat.opacity = cid === id ? 0.3 : 0.12;
        c.edgeMat.opacity = cid === id ? 1 : 0.6;
      }
    },
    pulseCamera(id, ms = 2400) { pulses.set(id, performance.now() + ms); },
    setProtected(objects) {
      scene.remove(footprints);
      labels.items.filter((it) => it.el.classList.contains("protected-label")).forEach((it) => it.el.remove());
      labels.items = labels.items.filter((it) => !it.el.classList.contains("protected-label"));
      footprints = L.buildFootprints(THREE, objects, labels);
      scene.add(footprints);
    },
  };
}

// ---------------------------------------------------------------------------
// 2D top-down fallback (same data, same encoding)
// ---------------------------------------------------------------------------

function create2D(container, twin, labels) {
  const canvas = document.createElement("canvas");
  container.insertBefore(canvas, labels.layer);
  const ctx = canvas.getContext("2d");
  const g = twin.ground || { min: [-12, -12], max: [12, 16] };
  let view = { s: 10, ox: 0, oy: 0 };
  let data = null;
  let current = null;
  let highlighted = null;
  let objects = twin.protected_objects || [];
  const pulses = new Map();

  // Seen from above with the street at the bottom: +x to the left, +z up.
  const toScreen = (x, z) => [view.ox + (g.max[0] - x) * view.s, view.oy + (g.max[1] - z) * view.s];

  function resize() {
    const w = container.clientWidth || 600;
    const h = container.clientHeight || 380;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const s = Math.min(w / (g.max[0] - g.min[0]), h / (g.max[1] - g.min[1]));
    view = { s, ox: (w - (g.max[0] - g.min[0]) * s) / 2, oy: (h - (g.max[1] - g.min[1]) * s) / 2 };
    draw();
  }

  function poly(pts) {
    ctx.beginPath();
    pts.forEach(([x, z], i) => {
      const [sx, sy] = toScreen(x, z);
      if (i) ctx.lineTo(sx, sy); else ctx.moveTo(sx, sy);
    });
    ctx.closePath();
  }

  const hatch = (() => {
    const c = document.createElement("canvas");
    c.width = 8;
    c.height = 8;
    const h = c.getContext("2d");
    h.strokeStyle = "#9aa0a6";
    h.lineWidth = 2;
    h.beginPath();
    h.moveTo(0, 8);
    h.lineTo(8, 0);
    h.stroke();
    return ctx.createPattern(c, "repeat");
  })();

  function circle(x, z, r) {
    const [sx, sy] = toScreen(x, z);
    ctx.beginPath();
    ctx.arc(sx, sy, Math.max(2, r * view.s), 0, Math.PI * 2);
  }

  function draw(now = performance.now()) {
    const w = canvas.width;
    ctx.clearRect(0, 0, w, canvas.height);
    ctx.fillStyle = "#24301f";
    poly([[g.min[0], g.min[1]], [g.max[0], g.min[1]], [g.max[0], g.max[1]], [g.min[0], g.max[1]]]);
    ctx.fill();
    for (const c of twin.coverage || []) {
      ctx.fillStyle = "rgba(110,160,220,0.22)";
      poly(c.polygon_m);
      ctx.fill();
    }
    for (const r of twin.blind_regions || []) {
      ctx.fillStyle = hatch;
      poly(r.polygon_m);
      ctx.fill();
      ctx.strokeStyle = "#9aa0a6";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    const colours = { building: "#c9c4b8", fence: "#a08a6a", protected: "#f2b233", object: "#6fa0d8" };
    for (const b of (twin.site_plan && twin.site_plan.boxes) || []) {
      ctx.fillStyle = colours[b.kind] || "#999";
      poly([[b.min[0], b.min[1]], [b.max[0], b.min[1]], [b.max[0], b.max[1]], [b.min[0], b.max[1]]]);
      ctx.fill();
    }
    for (const cam of twin.cameras || []) {
      if (!cam.position) continue;
      const c = coneCorners(cam);
      const pulsing = pulses.has(cam.id) && pulses.get(cam.id) > now;
      const alpha = pulsing ? 0.2 + 0.3 * (0.5 + 0.5 * Math.sin(now / 120)) : cam.id === highlighted ? 0.4 : 0.15;
      ctx.fillStyle = `rgba(79,195,247,${alpha})`;
      ctx.strokeStyle = "#4fc3f7";
      ctx.lineWidth = cam.id === highlighted ? 2 : 1;
      poly([[cam.position[0], cam.position[2]], [c[0][0], c[0][2]], [c[1][0], c[1][2]]]);
      ctx.fill();
      ctx.stroke();
    }
    for (const o of objects) {
      if (!o.footprint || o.footprint.length < 3) continue;
      ctx.setLineDash([4, 3]);
      ctx.strokeStyle = "#f2b233";
      poly(o.footprint);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    if (data) {
      ctx.strokeStyle = "#f2b233";
      ctx.lineWidth = 2.5;
      for (const seg of data.paths || []) {
        ctx.beginPath();
        seg.forEach(([x, z], i) => {
          const [sx, sy] = toScreen(x, z);
          if (i) ctx.lineTo(sx, sy); else ctx.moveTo(sx, sy);
        });
        ctx.stroke();
      }
      for (const p of thinPositions(data.positions || [])) {
        const big = current && current.t === p.t ? 1.35 : 1;
        ctx.lineWidth = 1.5;
        if (p.method === "footpoint") {
          circle(p.x, p.z, p.r95 * big);
          ctx.fillStyle = "rgba(242,178,51,0.22)";
          ctx.fill();
          ctx.setLineDash([3, 2]);
          ctx.stroke();
          ctx.setLineDash([]);
        } else if (p.method === "fused") {
          circle(p.x, p.z, p.r95 * big);
          ctx.stroke();
          circle(p.x, p.z, p.r95 * 0.6 * big);
          ctx.stroke();
        } else {
          ctx.lineWidth = 2.5;
          circle(p.x, p.z, p.r95 * big);
          ctx.stroke();
        }
      }
      ctx.strokeStyle = "#9aa0a6";
      ctx.lineWidth = 2.5;
      ctx.lineCap = "round";
      ctx.setLineDash([1, 6]);
      for (const gap of data.gaps || []) {
        if (!gap.from || !gap.to) continue;
        const a = toScreen(gap.from[0], gap.from[1]);
        const b = toScreen(gap.to[0], gap.to[1]);
        ctx.beginPath();
        ctx.moveTo(a[0], a[1]);
        ctx.lineTo(b[0], b[1]);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.lineCap = "butt";
    }
    labels.update(([x, , z]) => toScreen(x, z));
  }

  function tick(now) {
    if ([...pulses.values()].some((u) => u > now)) draw(now);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  for (const r of twin.blind_regions || []) {
    const cx = r.polygon_m.reduce((s, p) => s + p[0], 0) / r.polygon_m.length;
    const cz = r.polygon_m.reduce((s, p) => s + p[1], 0) / r.polygon_m.length;
    labels.add(`Blind region · ${r.name}`, [cx, 0, cz], "region-label");
  }
  for (const cam of twin.cameras || []) {
    if (cam.position) labels.add(cam.name, cam.position, "cam-label");
  }
  new ResizeObserver(resize).observe(container);
  resize();
  let posLabel = null;

  return {
    mode: "2d",
    frames: () => 0,
    showVisit(d) {
      data = d;
      labels.clear("visit");
      for (const gap of d.gaps || []) {
        if (!gap.from || !gap.to) continue;
        labels.add(gap.label, [(gap.from[0] + gap.to[0]) / 2, 0, (gap.from[1] + gap.to[1]) / 2],
          "gap-label", { gap: gap.id, group: "visit" });
      }
      posLabel = labels.add("", null, "pos-label", { group: "visit" });
      draw();
    },
    setTime(t) {
      current = data ? nearest(thinPositions(data.positions || []), t, 1.5) : null;
      if (posLabel) {
        posLabel.el.textContent = current ? current.label : "";
        posLabel.world = current ? [current.x, 0, current.z] : null;
      }
      draw();
    },
    highlightCamera(id) { highlighted = id; draw(); },
    pulseCamera(id, ms = 2400) { pulses.set(id, performance.now() + ms); },
    setProtected(list) { objects = list || []; draw(); },
  };
}

export async function createTwin(container, legendEl, twin) {
  renderLegend(legendEl);
  container.innerHTML = "";
  const labels = new Labels(container);
  let api = null;
  if (webglAvailable()) {
    try {
      api = await createWebGL(container, twin, labels);
    } catch (err) {
      console.warn("WebGL viewer failed; using the 2D map", err);
      container.querySelectorAll("canvas").forEach((c) => c.remove());
      labels.items.forEach((it) => it.el.remove());
      labels.items = [];
    }
  }
  if (!api) api = create2D(container, twin, labels);
  container.dataset.mode = api.mode;
  window.vigilTwin = api;
  return api;
}
