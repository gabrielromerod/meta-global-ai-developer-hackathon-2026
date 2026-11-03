// LAN-only calibration tool (FR-037): pick a marker in a camera still and the same marker on
// the ground map, then post the pair to /api/spatial/pairs. After 6 pairs the server runs
// PnP with RANSAC (2 more markers are held out for the error check, spec 7).

const $ = (s) => document.querySelector(s);
const still = $("#still-canvas");
const map = $("#map-canvas");
let twin = null;
let pixel = null;
let world = null;
let image = null;

function mapTransform() {
  const g = twin.ground;
  const s = Math.min(map.width / (g.max[0] - g.min[0]), map.height / (g.max[1] - g.min[1]));
  return {
    toScreen: (x, z) => [(g.max[0] - x) * s, (g.max[1] - z) * s],
    toWorld: (sx, sy) => [g.max[0] - sx / s, g.max[1] - sy / s],
  };
}

function drawStill() {
  const ctx = still.getContext("2d");
  ctx.fillStyle = "#101418";
  ctx.fillRect(0, 0, still.width, still.height);
  if (image) ctx.drawImage(image, 0, 0, still.width, still.height);
  else {
    ctx.fillStyle = "#a3abb2";
    ctx.font = "28px system-ui";
    ctx.fillText("Choose a still frame for this camera (stays local)", 40, 60);
  }
  if (pixel) {
    ctx.strokeStyle = "#f2b233";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(pixel[0], pixel[1], 12, 0, Math.PI * 2);
    ctx.moveTo(pixel[0] - 20, pixel[1]);
    ctx.lineTo(pixel[0] + 20, pixel[1]);
    ctx.moveTo(pixel[0], pixel[1] - 20);
    ctx.lineTo(pixel[0], pixel[1] + 20);
    ctx.stroke();
  }
}

function drawMap() {
  const ctx = map.getContext("2d");
  const { toScreen } = mapTransform();
  ctx.fillStyle = "#24301f";
  ctx.fillRect(0, 0, map.width, map.height);
  const poly = (pts) => {
    ctx.beginPath();
    pts.forEach(([x, z], i) => { const [a, b] = toScreen(x, z); if (i) ctx.lineTo(a, b); else ctx.moveTo(a, b); });
    ctx.closePath();
  };
  for (const b of (twin.site_plan && twin.site_plan.boxes) || []) {
    ctx.fillStyle = "#c9c4b8";
    poly([[b.min[0], b.min[1]], [b.max[0], b.min[1]], [b.max[0], b.max[1]], [b.min[0], b.max[1]]]);
    ctx.fill();
  }
  for (const c of twin.cameras || []) {
    if (!c.position) continue;
    const [a, b] = toScreen(c.position[0], c.position[2]);
    ctx.fillStyle = "#4fc3f7";
    ctx.fillRect(a - 5, b - 5, 10, 10);
    ctx.fillText(c.name, a + 8, b);
  }
  if (world) {
    const [a, b] = toScreen(world[0], world[2]);
    ctx.strokeStyle = "#f2b233";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(a, b, 9, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function pos(canvas, ev) {
  const r = canvas.getBoundingClientRect();
  return [((ev.clientX - r.left) / r.width) * canvas.width, ((ev.clientY - r.top) / r.height) * canvas.height];
}

// Owner endpoints need VIGIL_OWNER_TOKEN (F2). It lives in this tab's sessionStorage only.
const TOKEN_KEY = "vigil_owner_token";

function ownerToken() {
  const typed = $("#owner-token").value.trim();
  try {
    if (typed) sessionStorage.setItem(TOKEN_KEY, typed);
  } catch (_) { /* storage blocked: the typed value still works for this page */ }
  return typed;
}

function restoreToken() {
  try {
    $("#owner-token").value = sessionStorage.getItem(TOKEN_KEY) || "";
  } catch (_) { /* storage blocked */ }
}

function ready() {
  $("#send").disabled = !(pixel && world);
}

async function boot() {
  restoreToken();
  twin = await (await fetch("/api/twin")).json();
  $("#camera").innerHTML = (twin.cameras || []).map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
  still.addEventListener("click", (ev) => {
    pixel = pos(still, ev).map(Math.round);
    $("#pixel").textContent = `pixel: ${pixel[0]}, ${pixel[1]}`;
    drawStill();
    ready();
  });
  map.addEventListener("click", (ev) => {
    const [sx, sy] = pos(map, ev);
    const [x, z] = mapTransform().toWorld(sx, sy);
    world = [Number(x.toFixed(3)), 0, Number(z.toFixed(3))];
    $("#world").textContent = `world: x ${world[0]}, z ${world[2]}`;
    drawMap();
    ready();
  });
  $("#still").addEventListener("change", (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    const img = new Image();
    img.onload = () => { image = img; drawStill(); };
    img.src = URL.createObjectURL(file);
  });
  $("#send").addEventListener("click", async () => {
    const body = { camera_id: $("#camera").value, pixel, world };
    const token = ownerToken();
    if (!token) { $("#status").textContent = "Enter the owner token (VIGIL_OWNER_TOKEN) first."; return; }
    const res = await fetch("/api/spatial/pairs", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    });
    const out = await res.json();
    if (!res.ok) { $("#status").textContent = out.detail || `HTTP ${res.status}`; return; }
    const li = document.createElement("li");
    li.textContent = `${body.camera_id}: pixel (${pixel.join(", ")}) ↔ world (${world.join(", ")})`;
    $("#pairs").appendChild(li);
    $("#status").textContent = out.extrinsics
      ? `Solved: reprojection ${out.extrinsics.reproj_mean_px ?? "?"} px. ${out.note || ""}`
      : `${out.pairs} of ${out.needed} pairs. ${out.note || ""}`;
    pixel = null;
    world = null;
    drawStill();
    drawMap();
    ready();
  });
  drawStill();
  drawMap();
}

boot().catch((err) => { $("#status").textContent = `Could not start: ${err.message}`; });
