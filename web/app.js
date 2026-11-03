// Vigil web app: evening summary, scenario switcher, visit cards, synced players, house model,
// and the live buttons (protect, voice transcribe, compile, re-run). No build step; ES modules.

import {
  appliesBadge, esc, renderRerun, renderVisitDetail, renderVisitList, telemetryLine, verdictHtml,
} from "./cards.js";
import { SyncedPlayer } from "./player.js";
import { createTwin } from "./twin/viewer.js";
import { MAX_SECONDS, Recorder } from "./voice.js";

const $ = (sel) => document.querySelector(sel);
const state = {
  health: null, scenarios: null, twin: null, twinApi: null, player: null,
  scenarioId: null, visitId: null, visit: null, presets: null, protected: [], pending: null,
  cache: new Map(),
};
const SEVERITY = { needs_attention: 0, cant_confirm: 1, noteworthy: 2, normal: 3 };
const VERBS = { touch: "touches", cross: "crosses", enter: "enters", removed: "removes", dwell: "lingers at" };
const WHO = {
  anyone: "anyone", non_household: "anyone except household members",
  external_visitor_only: "someone from outside the property",
};

async function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.headers || {}) } };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.body = JSON.stringify(opts.json);
    init.headers["content-type"] = "application/json";
  }
  if (opts.body !== undefined) {
    init.method = init.method || "POST";
    init.body = opts.body;
  }
  const res = await fetch(path, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return body;
}

async function cached(path) {
  if (!state.cache.has(path)) state.cache.set(path, api(path));
  return state.cache.get(path);
}

// --- wall clock from the session start (no browser time zone involved) -------------------

let baseSeconds = 0;
function setSessionStart(iso) {
  const m = /T(\d\d):(\d\d):(\d\d)/.exec(iso || "");
  baseSeconds = m ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) : 0;
}
function clock(t) {
  const s = Math.floor(baseSeconds + t) % 86400;
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${((h + 11) % 12) + 1}:${mm}:${ss} ${h < 12 ? "AM" : "PM"}`;
}

// --- header, summary, tabs ----------------------------------------------------------------

async function refreshHealth() {
  const h = await api("/api/health");
  state.health = h;
  const live = h.live;
  const badge = $("#live-status");
  badge.className = `pill ${live.available ? "live" : "warn"}`;
  const judging = h.phase === "judging";
  badge.textContent = !live.available
    ? live.notice
    : judging
      ? `Live available · $${h.judging_today_remaining_usd.toFixed(2)} left today · ` +
        `$${h.judging_cap_remaining_usd.toFixed(2)} of $${h.judging_cap_usd.toFixed(0)} judging budget left`
      : `Live available · $${h.spend_today_usd.toFixed(2)} of $${h.daily_cap_usd.toFixed(0)} today`;
  $("#mode-badge").textContent = `Cached by default · ${h.mode}`;
  // Live buttons stay active at a cap (spec 11.6 item 6): the request returns the recorded
  // result with the notice, so a judge never meets a disabled or blank screen.
  document.querySelectorAll(".btn.live").forEach((b) => {
    b.title = live.available ? "Runs a real model call (rate-limited, capped)" : live.notice;
  });
  return h;
}

function renderSummary(data) {
  const s = data.summary;
  $("#summary").innerHTML =
    `<strong data-testid="summary-triggers">${s.motion_triggers}</strong> motion triggers<span class="arrow">→</span>` +
    `<strong data-testid="summary-visits">${s.visits}</strong> visits<span class="arrow">→</span>` +
    `<strong data-testid="summary-alerts">${s.alerts}</strong> alert${s.alerts === 1 ? "" : "s"}` +
    `<span class="sub">The recorded evening, ${esc(data.session_start ? data.session_start.slice(0, 10) : "")}. Everything below is cached; live buttons are marked.</span>`;
  if (data.synthetic) {
    const banner = $("#synthetic-banner");
    banner.hidden = false;
    banner.textContent = `${data.label}. Camera views are drawn from data; no real home or person appears.`;
  }
}

function renderTabs() {
  const tabs = [["evening", "Evening"], ...state.scenarios.scenarios.map((s) => [s.id, s.title]), ["benchmark", "Benchmark"]];
  $("#tabs").innerHTML = tabs.map(([id, label]) =>
    `<button type="button" class="tab" data-tab="${esc(id)}">${esc(label)}</button>`).join("");
  $("#tabs").querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
    const id = b.dataset.tab;
    location.hash = id === "evening" ? "#/" : id === "benchmark" ? "#/benchmark" : `#/scenario/${id}`;
  }));
}

function markTab(id) {
  document.querySelectorAll(".tab").forEach((b) => {
    if (b.dataset.tab === id) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
}

function allVisits() {
  return state.scenarios.scenarios.flatMap((s) => s.visits)
    .sort((a, b) => (SEVERITY[a.verdict] ?? 9) - (SEVERITY[b.verdict] ?? 9) || a.t0 - b.t0);
}

function showVisitList(visits, title) {
  $("#visits-title").textContent = title;
  renderVisitList($("#visit-list"), visits, state.visitId, (id) => { location.hash = `#/visit/${id}`; });
}

// --- scenario, players and twin -----------------------------------------------------------

async function loadScenario(id) {
  if (state.scenarioId === id) return cached(`/api/scenarios/${id}`);
  const sc = await cached(`/api/scenarios/${id}`);
  state.scenarioId = id;
  state.player.load(sc, state.twin);
  state.player.setProtected(state.protected);
  $("#scrub").max = String(sc.t1 - sc.t0);
  return sc;
}

function onCite({ t, camera }) {
  state.player.seekAbs(t);
  if (camera) {
    state.player.highlight(camera);
    state.twinApi.highlightCamera(camera);
    state.twinApi.pulseCamera(camera);
  }
  state.twinApi.setTime(t);
  const players = $("#players-panel");
  if (players.getBoundingClientRect().top > window.innerHeight) players.scrollIntoView({ block: "nearest" });
}

let lastTwinUpdate = 0;
function onTime(t, playing) {
  $("#player-clock").textContent = clock(t);
  if (state.player && state.player.scenario) $("#scrub").value = String(t - state.player.scenario.t0);
  $("#play-toggle").textContent = playing ? "Pause" : "Play";
  const now = performance.now();
  if (state.twinApi && (!playing || now - lastTwinUpdate > 250)) {
    lastTwinUpdate = now;
    state.twinApi.setTime(t);
  }
}

// --- views --------------------------------------------------------------------------------

async function showEvening() {
  markTab("evening");
  state.visitId = null;
  $("#detail").hidden = true;
  $("#layout").classList.add("no-detail");
  $("#benchmark").hidden = true;
  showVisitList(allVisits(), "Visits this evening");
  const first = allVisits()[0];
  if (first) await loadScenario(first.scenario);
}

async function showScenario(id) {
  const sc = state.scenarios.scenarios.find((s) => s.id === id);
  if (!sc) return showEvening();
  location.replace(`#/visit/${sc.visit_ids[0]}`);
}

async function showVisit(id) {
  const [visit, positions] = await Promise.all([api(`/api/visits/${id}`), api(`/api/visits/${id}/positions`)]);
  state.visitId = id;
  state.visit = visit;
  markTab(visit.scenario);
  $("#benchmark").hidden = true;
  const sc = state.scenarios.scenarios.find((s) => s.id === visit.scenario);
  showVisitList(sc ? sc.visits : allVisits(), `Visits in ${sc ? sc.title : "this scenario"}`);
  const detail = $("#detail");
  renderVisitDetail(detail, visit, {
    onCite, onRerun: (live, btn) => rerun(visit, live, btn), onFeedback: (kind, btn) => feedback(visit, kind, btn),
  });
  detail.hidden = false;
  $("#layout").classList.remove("no-detail");
  await loadScenario(visit.scenario);
  state.twinApi.showVisit(positions);
  const firstCite = visit.sentences.flatMap((s) => s.citations)[0];
  if (firstCite) {
    state.player.seekAbs(firstCite.t);
    state.player.highlight(firstCite.camera_id);
    state.twinApi.highlightCamera(firstCite.camera_id);
  }
  refreshHealth().catch(() => {});
  window.scrollTo(0, 0);
}

async function showBenchmark() {
  markTab("benchmark");
  const ev = await api("/api/eval");
  const rows = (ev.targets || ev.metrics || []).map((m) =>
    `<tr><td>${esc(m.metric || m.name)}</td><td>${esc(m.target ?? "")}</td><td>${esc(m.result ?? "not measured")}</td></tr>`).join("");
  const panel = $("#benchmark");
  panel.innerHTML = `<div class="panel-head"><h2>Benchmark</h2><span class="pill subtle">${esc(ev.status || "")}</span></div>` +
    `<p>${esc(ev.note || "")}</p><table><thead><tr><th>Metric</th><th>Pre-registered target</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table>`;
  panel.hidden = false;
  panel.scrollIntoView({ block: "start" });
}

async function route() {
  const h = location.hash || "#/";
  try {
    let m;
    if ((m = /^#\/visit\/([\w-]+)$/.exec(h))) await showVisit(m[1]);
    else if ((m = /^#\/scenario\/([\w-]+)$/.exec(h))) await showScenario(m[1]);
    else if (h === "#/benchmark") await showBenchmark();
    else await showEvening();
  } catch (err) {
    $("#detail").hidden = false;
    $("#detail").innerHTML = `<span class="notice">Could not load: ${esc(err.message)}</span>`;
  }
  document.body.dataset.ready = "1";
}

// --- live buttons ---------------------------------------------------------------------------

async function rerun(visit, live, btn) {
  const out = $("#detail [data-testid=rerun-out]");
  btn.disabled = true;
  out.innerHTML = `<span class="card-meta">${live ? "Running triage, Wonder and the validator live…" : "Loading the recorded re-run…"}</span>`;
  try {
    const job = await api(`/api/visits/${visit.id}/rerun`, { json: { stage: "story", live } });
    let res = await api(job.poll);
    for (let i = 0; res.status !== "done" && i < 120; i += 1) {
      await new Promise((r) => setTimeout(r, 500));
      res = await api(job.poll);
    }
    renderRerun(out, visit, res);
  } catch (err) {
    out.innerHTML = `<span class="notice">${esc(err.status === 429 ? "Too many live requests; try again in a minute." : err.message)}</span>`;
  } finally {
    btn.disabled = false;
    refreshHealth().catch(() => {});
  }
}

async function feedback(visit, kind, btn) {
  btn.disabled = true;
  try {
    const res = await api(`/api/visits/${visit.id}/feedback`, { json: { kind } });
    btn.insertAdjacentHTML("afterend", `<span class="card-meta" data-testid="feedback-note">${esc(res.note)}</span>`);
  } catch (err) {
    btn.disabled = false;
    btn.insertAdjacentHTML("afterend", `<span class="notice">${esc(err.message)}</span>`);
  }
}

function renderPresets() {
  $("#protect-presets").innerHTML = state.presets.protect.map((p, i) =>
    `<button type="button" class="btn small" data-preset="${i}">${esc(p.label)} (${esc(p.camera_id)})</button>`).join("");
  $("#protect-presets").querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => {
    const p = state.presets.protect[Number(b.dataset.preset)];
    choosePoint({ camera_id: p.camera_id, x: p.point[0], y: p.point[1], label: p.label });
  }));
}

function choosePoint(pt) {
  state.pending = pt;
  const box = $("#protect-result");
  box.hidden = false;
  box.innerHTML = `Point (${pt.x}, ${pt.y}) on <b>${esc(pt.camera_id)}</b>` +
    `<div class="btn-row"><button type="button" class="btn" data-run="false">Show recorded result</button>` +
    `<button type="button" class="btn live" data-run="true">Run live</button></div>`;
  box.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => protect(b.dataset.run === "true")));
}

async function protect(live) {
  const pt = state.pending;
  const box = $("#protect-result");
  try {
    const body = { camera_id: pt.camera_id, point: { x: pt.x, y: pt.y }, live };
    if (pt.label) body.label = pt.label;
    const res = await api("/api/protect", { json: body });
    let html = res.notice ? `<span class="notice" data-testid="fallback-notice">${esc(res.notice)}</span>` : "";
    if (res.result) {
      const o = res.result.object;
      state.protected = state.protected.filter((p) => p.id !== o.id);
      state.protected.push({ ...o, outline: res.result.outline, camera_id: res.result.camera_id });
      state.player.setProtected(state.protected);
      state.twinApi.setProtected([...(state.twin.protected_objects || []), ...state.protected.filter((p) => p.footprint)]);
      html += `<p>Protected <b>${esc(o.label)}</b> (${esc(o.id)}) on ${esc(o.camera_id)}${o.footprint ? "; footprint shown in the house model" : ""}.</p>`;
    }
    $("#protect-result").innerHTML = html + telemetryLine(res.telemetry);
  } catch (err) {
    box.innerHTML += `<span class="notice">${esc(err.status === 429 ? "Too many live requests; try again in a minute." : err.message)}</span>`;
  }
  refreshHealth().catch(() => {});
}

// --- voice rules (FR-022): record or play a sample -> editable transcript -> compile ---------

function showTranscript(res, source) {
  const r = res.result || {};
  $("#rule-text").value = r.transcript || "";
  const label = res.live ? "Live transcript" : "Recorded result";
  const note = res.notice ? `<span class="notice" data-testid="voice-notice">${esc(res.notice)}</span>` : "";
  $("#transcript-meta").innerHTML = `<b>${label}</b> · ${esc(source)} · edit before compiling ` +
    telemetryLine(res.telemetry) + note;
  $("#rule-text").focus();
}

async function transcribeFixture(fixture, btn) {
  btn.disabled = true;
  $("#transcript-meta").textContent = "Transcribing the sample…";
  try {
    // Live only when the consented WAV is in this build; otherwise the cached transcript.
    const live = Boolean(fixture.recorded && state.health && state.health.live.available);
    const res = await api("/api/voice/transcribe", { json: { fixture_id: fixture.id, live } });
    showTranscript(res, fixture.label);
  } catch (err) {
    $("#transcript-meta").innerHTML = `<span class="notice">${esc(err.status === 429 ? "Too many live requests; try again in a minute." : err.message)}</span>`;
  } finally {
    btn.disabled = false;
    refreshHealth().catch(() => {});
  }
}

async function renderVoice() {
  const body = await api("/api/voice/fixtures");
  $("#voice-samples").innerHTML = body.fixtures.map((f, i) =>
    `<button type="button" class="btn small sample" data-testid="voice-sample" data-fixture="${esc(f.id)}" data-index="${i}"` +
    ` title="${esc(f.recorded ? "Sends the consented recording" : "Uses the recorded transcript")}">${esc(f.label)}</button>`).join("");
  $("#voice-note").textContent = body.note || "";
  $("#voice-samples").querySelectorAll("[data-fixture]").forEach((b) => b.addEventListener("click", () =>
    transcribeFixture(body.fixtures[Number(b.dataset.index)], b)));
}

function setupMic() {
  const mic = $("#mic");
  const status = $("#mic-status");
  if (!Recorder.supported()) {
    mic.disabled = true;
    status.textContent = "No microphone here: use a sample recording or type the rule.";
    return;
  }
  const rec = new Recorder({
    maxSeconds: MAX_SECONDS,
    onTick: (s) => { status.textContent = `Recording… ${s.toFixed(1)} s of ${MAX_SECONDS} s`; },
    onLimit: () => finish(),
  });
  let pressedAt = 0;
  let busy = false;
  async function begin() {
    if (rec.recording || busy) return;
    try {
      await rec.start();
      pressedAt = performance.now();
      mic.classList.add("recording");
      mic.setAttribute("aria-pressed", "true");
      status.textContent = "Recording… tap again or release to stop.";
    } catch {
      status.textContent = "Microphone permission denied: use a sample recording or type the rule.";
    }
  }
  async function finish() {
    if (!rec.recording || busy) return;
    busy = true;
    mic.classList.remove("recording");
    mic.setAttribute("aria-pressed", "false");
    const out = await rec.stop();
    status.textContent = `Sending ${out.seconds.toFixed(1)} s (16 kHz mono WAV, ${(out.blob.size / 1024).toFixed(0)} KB)…`;
    try {
      const res = await api("/api/voice/transcribe?live=1", { body: out.blob, headers: { "content-type": "audio/wav" } });
      showTranscript(res, "your recording");
      status.textContent = "Recording sent; nothing was stored in the browser.";
    } catch (err) {
      status.textContent = err.status === 429 ? "Too many live requests; try again in a minute." : `Could not transcribe: ${err.message}. Type the rule instead.`;
    } finally {
      busy = false;
      refreshHealth().catch(() => {});
    }
  }
  mic.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    if (rec.recording) finish(); else begin();
  });
  mic.addEventListener("pointerup", () => {
    if (rec.recording && performance.now() - pressedAt > 600) finish(); // hold-to-speak
  });
  mic.addEventListener("click", (e) => {
    if (e.detail === 0) { if (rec.recording) finish(); else begin(); } // keyboard
  });
}

async function compileRule(live) {
  const text = $("#rule-text").value.trim();
  const box = $("#rule-result");
  box.hidden = false;
  if (!text) { box.innerHTML = `<span class="notice">Type a rule first.</span>`; return; }
  box.innerHTML = `<span class="card-meta">${live ? "Compiling live with Muse Spark…" : "Loading the recorded draft…"}</span>`;
  try {
    const res = await api("/api/rules/compile", { json: { text, live } });
    const r = res.result || {};
    let html = res.notice ? `<span class="notice" data-testid="fallback-notice">${esc(res.notice)}</span>` : "";
    if (r.question) html += `<p><b>${esc(r.question)}</b></p>`;
    if (r.rule) {
      const rule = r.rule;
      const when = rule.active ? `${rule.active.start} to ${rule.active.end}` : "any time";
      const applies = rule.applies_to || "anyone";
      html += `<div class="rule-card" data-testid="rule-draft"><b>Draft rule ${esc(rule.id)}</b>: ${esc(rule.name)}<br>` +
        `When ${esc(WHO[applies] || "anyone")} ${esc(VERBS[rule.trigger] || rule.trigger)} ${esc(rule.target.kind.replace("_", " "))} <b>${esc(rule.target.id)}</b>, ${esc(when)} → ${verdictHtml(rule.severity, rule.severity === "needs_attention" ? "Needs your attention" : rule.severity)}` +
        `<div>${appliesBadge(applies)}</div>` +
        `<p class="basis-note" data-testid="basis-note"><b>${esc(r.applies_label || "")}</b> ${esc(r.basis_note || "")}</p>` +
        `<ul class="limits">${(r.limits_note || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` +
        `<details><summary>Rule JSON</summary><pre class="mono">${esc(JSON.stringify(rule, null, 1))}</pre></details>` +
        `<button type="button" class="btn" data-confirm="${esc(rule.id)}">Confirm rule</button> <span class="rule-state"></span></div>`;
    }
    box.innerHTML = html + telemetryLine(res.telemetry);
    const c = box.querySelector("[data-confirm]");
    if (c) c.addEventListener("click", async () => {
      const done = await api(`/api/rules/${c.dataset.confirm}/confirm`, { method: "POST" });
      box.querySelector(".rule-state").textContent = `Rule ${done.id} is ${done.state}. ${done.note}`;
      c.disabled = true;
    });
  } catch (err) {
    box.innerHTML = `<span class="notice">${esc(err.status === 429 ? "Too many live requests; try again in a minute." : err.message)}</span>`;
  }
  refreshHealth().catch(() => {});
}

// --- boot -----------------------------------------------------------------------------------

async function boot() {
  const [, scenarios, twin, presets] = await Promise.all([
    refreshHealth(), api("/api/scenarios"), api("/api/twin"), api("/api/presets"),
  ]);
  state.scenarios = scenarios;
  state.twin = twin;
  state.presets = presets;
  setSessionStart(scenarios.session_start);
  renderSummary(scenarios);
  renderTabs();
  renderPresets();
  setupMic();
  await renderVoice().catch((err) => { $("#voice-note").textContent = `Sample recordings unavailable: ${err.message}`; });
  state.player = new SyncedPlayer($("#players"), {
    onTime,
    onTap: (pt) => { if ($("#protect-mode").checked) choosePoint(pt); },
  });
  window.vigil = { state, player: state.player };
  $("#play-toggle").addEventListener("click", () => state.player.toggle());
  $("#scrub").addEventListener("input", (e) => {
    if (state.player.scenario) state.player.seekAbs(state.player.scenario.t0 + Number(e.target.value));
  });
  $("#protect-mode").addEventListener("change", (e) => document.body.classList.toggle("protect-mode", e.target.checked));
  $("#rule-form").addEventListener("submit", (e) => { e.preventDefault(); compileRule(false); });
  $("#rule-live").addEventListener("click", () => compileRule(true));
  state.twinApi = await createTwin($("#twin"), $("#legend"), twin);
  window.vigil.twin = state.twinApi;
  $("#twin-mode").textContent = state.twinApi.mode === "webgl"
    ? `3D · ${twin.synthetic ? "synthetic site plan" : "LiDAR model"}`
    : `2D map (WebGL unavailable) · ${twin.synthetic ? "synthetic site plan" : "LiDAR model"}`;
  window.addEventListener("hashchange", route);
  await route();
}

boot().catch((err) => {
  $("#summary").innerHTML = `<span class="notice">Vigil could not start: ${esc(err.message)}</span>`;
  document.body.dataset.ready = "error";
});
