// Owner tokens stay in sessionStorage and are sent only to this origin's API.
import { esc } from "./cards.js";
const KEY = "vigil_owner_token";
const $ = sel => document.querySelector(sel);

export async function ownerFetch(path, opts = {}) {
  const url = new URL(path, location.href);
  if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) throw new Error("Use this app's API.");
  const init = { ...opts, headers: { ...(opts.headers || {}) } };
  const token = sessionStorage.getItem(KEY);
  if (token) init.headers.Authorization = `Bearer ${token}`;
  if (opts.json !== undefined) {
    init.body = JSON.stringify(opts.json);
    init.method ||= "POST";
    init.headers["content-type"] = "application/json";
    delete init.json;
  }
  const response = await fetch(url, init);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
  return data;
}

export async function setupOwner(health, cameras) {
  const sandbox = health.mode === "sandbox";
  const status = $("#owner-status");
  const showError = error => { status.textContent = error.message; };
  $("#owner-disabled").hidden = !sandbox;
  $("#owner-controls").disabled = sandbox;
  $("#owner-token-open").disabled = sandbox;
  const camera = $("#owner-window-camera");
  camera.innerHTML = '<option value="">All perimeter cameras</option>' + cameras.map(c =>
    `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");
  const sheet = $("#owner-token-sheet");
  $("#owner-token-open").addEventListener("click", () => {
    $("#owner-token-input").value = sessionStorage.getItem(KEY) || "";
    sheet.showModal();
  });
  $("#owner-token-close").addEventListener("click", () => sheet.close());
  $("#owner-token-form").addEventListener("submit", async ev => {
    ev.preventDefault();
    const token = $("#owner-token-input").value.trim();
    if (token) sessionStorage.setItem(KEY, token); else sessionStorage.removeItem(KEY);
    $("#owner-token-input").value = "";
    sheet.close();
    await refresh().catch(showError);
  });
  async function refresh() {
    const result = await ownerFetch("/api/windows");
    $("#owner-windows").innerHTML = result.windows.map(w =>
      `<li class="owner-window" data-window="${esc(w.id)}"><b>${esc(w.label || w.id)}</b> · ` +
      `${esc(w.state)} · ${esc(w.start)} – ${esc(w.end)}` +
      `${w.recorded ? ' <span class="pill subtle">Recorded example · B′</span>' : ""}` +
      `${!w.recorded && !sandbox && !["cancelled", "expired"].includes(w.state) ?
        ` <button type="button" class="btn small" data-cancel-window="${esc(w.id)}">Cancel</button>` : ""}</li>`
    ).join("") || "<li>No Expected Windows.</li>";
    $("#owner-windows").querySelectorAll("[data-cancel-window]").forEach(button => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await ownerFetch(`/api/windows/${encodeURIComponent(button.dataset.cancelWindow)}`, { method: "DELETE" });
          await refresh();
        } catch (error) { button.disabled = false; showError(error); }
      });
    });
  }
  let timer;
  function tick() {
    const end = Number(sessionStorage.getItem("vigil_checkin_deadline") || 0);
    const remaining = Math.max(0, Math.ceil((end - Date.now()) / 1000));
    $("#owner-countdown").textContent = remaining ? `${remaining} s remaining` : "";
    if (!remaining && timer) { clearInterval(timer); timer = null; }
  }
  if (!sandbox) { tick(); timer = setInterval(tick, 250); }
  $("#owner-checkin").addEventListener("click", async () => {
    const button = $("#owner-checkin");
    button.disabled = true;
    try {
      const result = await ownerFetch("/api/checkin", { method: "POST" });
      sessionStorage.setItem("vigil_checkin_deadline", String(
        Date.parse(result.checkin.start) + result.binds_within_s * 1000));
      status.textContent = result.note;
      tick();
      if (!timer) timer = setInterval(tick, 250);
    } catch (error) { showError(error); }
    finally { button.disabled = false; }
  });
  $("#owner-window-form").addEventListener("submit", async ev => {
    ev.preventDefault();
    const button = $("#owner-window-create");
    button.disabled = true;
    try {
      await ownerFetch("/api/windows", { json: {
        start: new Date($("#owner-window-start").value).toISOString(),
        end: new Date($("#owner-window-end").value).toISOString(),
        label: $("#owner-window-label").value.trim() || null,
        cameras: camera.value ? [camera.value] : [],
        zones: $("#owner-window-zones").value.split(",").map(s => s.trim()).filter(Boolean),
      } });
      status.textContent = "Expected Window created for future arrivals.";
      await refresh();
    } catch (error) { showError(error); }
    finally { button.disabled = false; }
  });
  await refresh();
}
