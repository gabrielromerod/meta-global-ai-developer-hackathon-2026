// Synced camera players (FR-018). Three or four clips play in step from one master clock;
// a citation seeks every player and highlights the cited camera; an overlay canvas draws
// SAM boxes and outlines from the overlay JSON. When a bundle has no clips (the synthetic
// demo), each camera is a canvas drawn from the site plan through that camera's pose, and
// behaves like a <video>: it has its own currentTime that the sync loop keeps in step.

const W = 1280;
const H = 720;
const DRIFT_SYNTH_S = 0.08;
const DRIFT_VIDEO_S = 0.15;

function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function norm(a) { const n = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / n, a[1] / n, a[2] / n]; }
function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

// Same pinhole model as demo/synthetic/build.py, so outlines land on the drawn scene.
export function pinhole(pose) {
  const p = pose.position;
  const f = norm(sub(pose.look_at, p));
  const r = norm([-f[2], 0, f[0]]);
  const u = cross(r, f);
  const fx = (W / 2) / Math.tan((pose.hfov_deg * Math.PI) / 360);
  return (pt) => {
    const d = sub(pt, p);
    const zc = dot(d, f);
    if (zc <= 0.2) return null;
    return [W / 2 + (fx * dot(d, r)) / zc, H / 2 - (fx * dot(d, u)) / zc];
  };
}

function lerp(a, b, k) { return a + (b - a) * k; }

function frameAt(frames, t) {
  if (!frames.length || t < frames[0].t - 0.25 || t > frames[frames.length - 1].t + 0.5) return null;
  let i = 0;
  while (i < frames.length - 1 && frames[i + 1].t <= t) i += 1;
  const a = frames[i];
  const b = frames[Math.min(i + 1, frames.length - 1)];
  if (b === a || b.t === a.t) return a;
  const k = Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t)));
  const box = a.box.map((v, j) => lerp(v, b.box[j], k));
  const outline = a.outline.length === b.outline.length
    ? a.outline.map((pt, j) => [lerp(pt[0], b.outline[j][0], k), lerp(pt[1], b.outline[j][1], k)])
    : a.outline;
  return { box, outline };
}

function drawSegment(ctx, project, a, b, steps) {
  let prev = null;
  for (let s = 0; s <= steps; s += 1) {
    const k = s / steps;
    const pt = project([lerp(a[0], b[0], k), lerp(a[1], b[1], k), lerp(a[2], b[2], k)]);
    if (pt && prev && Math.abs(pt[0]) < 5 * W && Math.abs(pt[1]) < 5 * H) {
      ctx.moveTo(prev[0], prev[1]);
      ctx.lineTo(pt[0], pt[1]);
    }
    prev = pt;
  }
}

function drawScene(canvas, cam, twin, label) {
  const ctx = canvas.getContext("2d");
  ctx.setTransform(canvas.width / W, 0, 0, canvas.height / H, 0, 0);
  const sky = ctx.createLinearGradient(0, 0, 0, H);
  sky.addColorStop(0, "#1b2430");
  sky.addColorStop(1, "#0b0e11");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, H);
  if (!cam.pose) return;
  const project = pinhole(cam.pose);
  const g = twin.ground || { min: [-12, -12], max: [12, 16] };
  ctx.lineWidth = 1.2;
  ctx.strokeStyle = "rgba(120, 150, 120, 0.35)";
  ctx.beginPath();
  for (let x = Math.ceil(g.min[0]); x <= g.max[0]; x += 2) {
    drawSegment(ctx, project, [x, 0, g.min[1]], [x, 0, g.max[1]], 56);
  }
  for (let z = Math.ceil(g.min[1]); z <= g.max[1]; z += 2) {
    drawSegment(ctx, project, [g.min[0], 0, z], [g.max[0], 0, z], 48);
  }
  ctx.stroke();
  const colours = { building: "#c9c4b8", fence: "#a08a6a", protected: "#f2b233", object: "#6fa0d8" };
  for (const b of (twin.site_plan && twin.site_plan.boxes) || []) {
    const [x0, z0] = b.min;
    const [x1, z1] = b.max;
    const h = b.h;
    const c = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
    ctx.strokeStyle = colours[b.kind] || "#999";
    ctx.lineWidth = b.kind === "building" ? 2 : 1.6;
    ctx.beginPath();
    for (let i = 0; i < 4; i += 1) {
      const a = c[i];
      const n = c[(i + 1) % 4];
      drawSegment(ctx, project, [a[0], 0, a[1]], [n[0], 0, n[1]], 16);
      drawSegment(ctx, project, [a[0], h, a[1]], [n[0], h, n[1]], 16);
      drawSegment(ctx, project, [a[0], 0, a[1]], [a[0], h, a[1]], 4);
    }
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.font = "600 26px system-ui, sans-serif";
  ctx.fillText("SYNTHETIC VIEW", 24, 44);
  ctx.font = "22px system-ui, sans-serif";
  ctx.fillText(label, 24, 76);
}

class SyntheticClip {
  constructor(canvas, camera, twin) {
    this.el = canvas;
    this.camera = camera;
    this.twin = twin;
    this._t = 0;
    this.paused = true;
    const self = this;
    Object.defineProperty(canvas, "currentTime", {
      configurable: true,
      get() { return self._t; },
      set(v) { self._t = Number(v); },
    });
    drawScene(canvas, camera, twin, camera.name);
  }
  get currentTime() { return this._t; }
  set currentTime(v) { this._t = v; }
  play() { this.paused = false; }
  pause() { this.paused = true; }
  advance(dt) { if (!this.paused) this._t += dt; }
}

class VideoClip {
  constructor(video) {
    this.el = video;
    this.target = 0;
    video.addEventListener("loadedmetadata", () => { this.currentTime = this.target; });
  }
  get currentTime() { return this.el.currentTime; }
  set currentTime(v) {
    this.target = v;
    if (this.el.readyState < 1) return;
    this.el.currentTime = Math.max(0, Math.min(v, this.el.duration || v));
  }
  get paused() { return this.el.paused; }
  play() { this.el.play().catch(() => {}); }
  pause() { this.el.pause(); }
  advance() {}
}

export class SyncedPlayer {
  constructor(container, opts = {}) {
    this.container = container;
    this.opts = opts;
    this.clips = [];
    this.tiles = new Map();
    this.overlays = {};
    this.protected = [];
    this.master = 0;
    this.playing = false;
    this.scenario = null;
    this._last = performance.now();
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
  }

  load(scenario, twin) {
    this.scenario = scenario;
    this.sourceLabel = twin && twin.synthetic ? "synthetic outline" : "SAM 3.1";
    this.overlays = scenario.overlays || {};
    this.container.innerHTML = "";
    this.clips = [];
    this.tiles.clear();
    for (const cam of scenario.cameras) {
      const fig = document.createElement("figure");
      fig.className = "tile";
      fig.dataset.camera = cam.id;
      fig.dataset.testid = "player-tile";
      let clip;
      if (cam.clip_url) {
        const v = document.createElement("video");
        v.className = "player-media";
        v.muted = true;
        v.playsInline = true;
        v.preload = "auto";
        v.src = cam.clip_url;
        v.addEventListener("loadedmetadata", () => this._drawOverlays());
        v.dataset.camera = cam.id;
        fig.appendChild(v);
        clip = new VideoClip(v);
      } else {
        const c = document.createElement("canvas");
        c.className = "player-media";
        c.width = 640;
        c.height = 360;
        c.dataset.camera = cam.id;
        c.setAttribute("role", "img");
        c.setAttribute("aria-label", `${cam.name} camera (synthetic view)`);
        fig.appendChild(c);
        clip = new SyntheticClip(c, cam, twin);
      }
      const ov = document.createElement("canvas");
      ov.className = "overlay";
      ov.width = 640;
      ov.height = 360;
      fig.appendChild(ov);
      const cap = document.createElement("figcaption");
      cap.textContent = cam.name;
      fig.appendChild(cap);
      const cited = document.createElement("span");
      cited.className = "cited";
      cited.textContent = "Cited";
      fig.appendChild(cited);
      fig.addEventListener("click", (ev) => this._tap(ev, cam.id, clip.el));
      this.container.appendChild(fig);
      clip.overlay = ov;
      clip.cameraId = cam.id;
      this.clips.push(clip);
      this.tiles.set(cam.id, fig);
    }
    this.seekAbs(scenario.t0);
  }

  get duration() { return this.scenario ? this.scenario.t1 - this.scenario.t0 : 0; }
  get absTime() { return this.scenario ? this.scenario.t0 + this.master : 0; }
  currentTimes() { return this.clips.map((c) => c.currentTime); }

  play() {
    this.playing = true;
    this.clips.forEach((c) => c.play());
    this._emit();
  }

  pause() {
    this.playing = false;
    this.clips.forEach((c) => c.pause());
    this._emit();
  }

  toggle() { if (this.playing) this.pause(); else this.play(); }

  seekAbs(t) {
    if (!this.scenario) return;
    const rel = Math.min(Math.max(t - this.scenario.t0, 0), this.duration);
    this.master = rel;
    for (const c of this.clips) c.currentTime = rel;
    this._drawOverlays();
    this._emit();
  }

  highlight(cameraId) {
    for (const [id, fig] of this.tiles) fig.classList.toggle("highlight", id === cameraId);
  }

  setProtected(list) {
    this.protected = list || [];
    this._drawOverlays();
  }

  _tap(ev, cameraId, el) {
    if (!this.opts.onTap) return;
    const rect = el.getBoundingClientRect();
    const x = ((ev.clientX - rect.left) / rect.width) * W;
    const y = ((ev.clientY - rect.top) / rect.height) * H;
    this.opts.onTap({ camera_id: cameraId, x: Math.round(x), y: Math.round(y), t: this.absTime });
  }

  _emit() { if (this.opts.onTime) this.opts.onTime(this.absTime, this.playing); }

  _loop(now) {
    const dt = Math.min(0.25, (now - this._last) / 1000);
    this._last = now;
    if (this.scenario && this.playing) {
      this.master += dt;
      if (this.master >= this.duration) {
        this.master = this.duration;
        this.pause();
      }
      for (const c of this.clips) {
        c.advance(dt);
        const limit = c instanceof VideoClip ? DRIFT_VIDEO_S : DRIFT_SYNTH_S;
        if (Math.abs(c.currentTime - this.master) > limit) c.currentTime = this.master;
      }
      this._drawOverlays();
      this._emit();
    }
    requestAnimationFrame(this._loop);
  }

  _drawOverlays() {
    if (!this.scenario) return;
    const t = this.absTime;
    for (const c of this.clips) {
      const ctx = c.overlay.getContext("2d");
      ctx.setTransform(c.overlay.width / W, 0, 0, c.overlay.height / H, 0, 0);
      ctx.clearRect(0, 0, W, H);
      for (const po of this.protected) {
        if (po.camera_id !== c.cameraId || !po.outline || !po.outline.length) continue;
        ctx.setLineDash([10, 8]);
        ctx.strokeStyle = "#f2b233";
        ctx.lineWidth = 4;
        ctx.beginPath();
        po.outline.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
        ctx.closePath();
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "#f2b233";
        ctx.font = "600 24px system-ui, sans-serif";
        ctx.fillText(`Protected: ${po.label}`, po.outline[0][0], Math.max(28, po.outline[0][1] - 10));
      }
      const tracks = this.overlays[c.cameraId] || {};
      for (const tr of Object.values(tracks)) {
        const f = frameAt(tr.frames, t);
        if (!f) continue;
        const colour = tr.cls === "person" ? "#4fc3f7" : tr.cls === "car" ? "#c792ea" : "#a5d6a7";
        ctx.fillStyle = colour + "33";
        ctx.strokeStyle = colour;
        ctx.lineWidth = 3;
        ctx.beginPath();
        f.outline.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        ctx.setLineDash([8, 6]);
        ctx.lineWidth = 2;
        ctx.strokeRect(f.box[0], f.box[1], f.box[2] - f.box[0], f.box[3] - f.box[1]);
        ctx.setLineDash([]);
        ctx.fillStyle = colour;
        ctx.font = "600 24px system-ui, sans-serif";
        ctx.fillText(`${tr.tag} ${tr.cls} · ${this.sourceLabel}`, f.box[0], Math.max(26, f.box[1] - 8));
      }
    }
  }
}
