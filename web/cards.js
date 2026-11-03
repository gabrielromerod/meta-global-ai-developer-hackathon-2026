// Visit list and visit cards (FR-017, FR-023 UI, FR-044, NFR-018, NFR-022).
// Verdicts are icon + word; every sentence has citation chips and a source badge; every
// subject shows where it came from (its role and stored role_basis), never who it is.

export const VERDICT_ICONS = {
  needs_attention:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 21h20z" fill="currentColor"/><path d="M12 9v6M12 17.5v.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></svg>',
  noteworthy:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M12 7v6M12 16.5v.5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  normal:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="currentColor"/><path d="m7.5 12.5 3 3 6-6.5" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  cant_confirm:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="4" fill="none" stroke="currentColor" stroke-width="2.2" stroke-dasharray="3 2.5"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.5v.4M12 16.8v.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
};

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

export function verdictHtml(verdict, label) {
  const icon = VERDICT_ICONS[verdict] || VERDICT_ICONS.cant_confirm;
  return `<span class="verdict" data-verdict="${esc(verdict)}" data-testid="verdict">${icon}` +
    `<span class="verdict-word">${esc(label || verdict)}</span></span>`;
}

function money(v) {
  return `$${Number(v || 0).toFixed(4)}`;
}

export function renderVisitList(ul, visits, currentId, onOpen) {
  ul.innerHTML = "";
  for (const v of visits) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "visit-item";
    btn.dataset.visit = v.id;
    btn.dataset.testid = "visit-item";
    if (v.id === currentId) btn.setAttribute("aria-current", "true");
    btn.innerHTML =
      `<span class="row">${verdictHtml(v.verdict, v.verdict_label)}` +
      `<span class="when">${esc(v.clock)} · Scenario ${esc(v.scenario)}</span></span>` +
      `<p>${esc(v.first_sentence)}</p>` +
      (v.gaps && v.gaps.length ? `<span class="when">${v.gaps.map(esc).join(" · ")}</span>` : "");
    btn.addEventListener("click", () => onOpen(v.id));
    li.appendChild(btn);
    ul.appendChild(li);
  }
}

function chipHtml(c) {
  return `<button type="button" class="chip" data-testid="citation-chip" data-event="${esc(c.event_id)}"` +
    ` data-t="${c.t}" data-camera="${esc(c.camera_id)}" title="Seek every camera to ${esc(c.clock)}">` +
    `${esc(c.event_id)} · ${esc(c.clock)} · ${esc(c.camera_name)}</button>`;
}

function badgeHtml(b) {
  const call = b.call_id ? ` data-call="${esc(b.call_id)}"` : "";
  const model = b.model ? ` data-model="${esc(b.model)}"` : "";
  return `<span class="source-badge" data-testid="source-badge" data-kind="${esc(b.kind)}"${model}${call}>${esc(b.label)}</span>`;
}

export function sentencesHtml(sentences) {
  return sentences.map((s) => {
    const gapChip = s.gap
      ? `<button type="button" class="chip gap-chip" data-testid="citation-chip" data-gap="${esc(s.gap.id)}"` +
        ` data-t="${s.gap.t0}" title="Seek to where the subject left view">${esc(s.gap.label)}</button>`
      : "";
    return `<li class="sentence" data-source="${esc(s.source)}" data-index="${s.index}">` +
      `<span class="text">${esc(s.text)}</span>` +
      `<span class="chips">${s.citations.map(chipHtml).join("")}${gapChip}</span>` +
      `${badgeHtml(s.badge)}</li>`;
  }).join("");
}

function gapBarsHtml(visit) {
  const span = Math.max(1, visit.t1 - visit.t0);
  return visit.gaps.map((g) => {
    const left = ((g.t0 - visit.t0) / span) * 100;
    const width = ((g.t1 - g.t0) / span) * 100;
    return `<div class="gapbar" data-testid="gap-bar"><div class="track">` +
      `<span class="obs" style="left:0;width:${left.toFixed(2)}%"></span>` +
      `<span class="gap" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%"></span>` +
      `<span class="obs" style="left:${(left + width).toFixed(2)}%;right:0"></span></div>` +
      `<span class="gap-label">${esc(g.label)} · ${esc(g.region_name || "")} · ${esc(g.clock_t0)} to ${esc(g.clock_t1)}</span></div>`;
  }).join("") || `<p class="card-meta">No gaps: the subject stayed in view.</p>`;
}

function timelineHtml(visit) {
  return `<ol class="timeline">` + visit.events.map((e) =>
    `<li><button type="button" data-t="${e.t}" data-camera="${esc(e.camera_id)}" data-event="${esc(e.event_id)}">` +
    `<span class="ev-type">${esc(e.type)}</span> ${esc(e.clock)} · ${esc(e.camera_name)}` +
    `${e.target ? " · " + esc(e.target) : ""} <span class="card-meta">${esc(e.event_id)}</span></button></li>`,
  ).join("") + `</ol>`;
}

const APPLIES_SHORT = { anyone: "anyone", non_household: "non-household", external_visitor_only: "outsiders only" };

export function appliesBadge(appliesTo) {
  return `<span class="applies-badge" data-testid="applies-badge" data-applies="${esc(appliesTo)}">` +
    `Applies to: ${esc(APPLIES_SHORT[appliesTo] || appliesTo)}</span>`;
}

function roleChip(s) {
  return `<span class="role-chip" data-testid="role-chip" data-role="${esc(s.actor_role)}">${esc(s.role_label)}</span>`;
}

function subjectsHtml(t) {
  const subjects = (t.subjects || []).map((s) =>
    `<li data-testid="role-basis">Subject ${esc(s.id)}: ${roleChip(s)} role_basis ` +
    `<code class="role-basis">${esc(s.role_basis)}</code>: ${esc(s.basis_label)}</li>`).join("");
  const excluded = (t.rules_excluded || []).map((r) =>
    `<li class="excluded" data-testid="rule-excluded">Rule <b>${esc(r.rule_id)}</b> not fired: ${esc(r.reason)}</li>`).join("");
  if (!subjects && !excluded) return "";
  return `<p class="section-title">Where each person came from (no identification)</p>` +
    `<ul class="trace-list">${subjects}${excluded}</ul>`;
}

function traceHtml(visit) {
  const t = visit.trace;
  const vi = t.verdict_inputs || {};
  const rules = t.rules_fired.length
    ? t.rules_fired.map((r) => `<li>Rule <b>${esc(r.rule_id)}</b> fired: ${esc(r.rule_name)} (event ${esc(r.event_id)}; applies to ${esc(APPLIES_SHORT[r.applies_to] || r.applies_to || "anyone")})</li>`).join("")
    : "<li>No rule fired.</li>";
  const tri = t.triage
    ? `<li>Triage: ${t.triage.escalate ? "escalated" : "not escalated"} by ${esc(t.triage.source)}` +
      `${t.triage.forced ? " (forced by code)" : ""}: ${esc(t.triage.reason)}` +
      `${t.triage.call_id ? ` <span class="source-badge" data-kind="model">${esc(t.triage.call_id)}</span>` : ""}</li>`
    : "";
  const drafts = (t.drafts || []).map((d) => {
    const fails = (d.failures || []).map((f) =>
      `<li class="fail">Rejected: ${esc(f.check)}${f.sentence_index != null ? ` (sentence ${f.sentence_index + 1})` : ""}: ${esc(f.detail)}</li>`).join("");
    const sents = (d.sentences || []).map((s) => `<li>${esc(s.text)} <span class="card-meta">[${(s.event_ids || []).map(esc).join(", ") || "no citation"}]</span></li>`).join("");
    return `<div class="draft ${d.passed ? "" : "rejected"}" data-testid="draft">` +
      `<b>Wonder draft ${d.attempt}</b> · ${d.passed ? "passed the validator" : "rejected by the validator"}` +
      ` <span class="source-badge" data-kind="model">${esc(d.call_id || "")}</span>` +
      `<ol class="trace-list">${sents}</ol>${fails ? `<ul class="trace-list">${fails}</ul>` : ""}</div>`;
  }).join("");
  const cal = (t.calibration || []).map((c) =>
    `<li>${esc(c.name)}: ${c.intrinsics_source ? `${esc(c.intrinsics_source)} intrinsics, ` : ""}` +
    `${c.landmarks ? `${esc(c.landmarks)}-landmark PnP, ` : ""}reprojection ${esc(c.reproj_mean_px)} px, ` +
    `held-out ground error ${esc(c.heldout_ground_m)} m (${esc(c.method)})${c.synthetic ? " · synthetic" : ""}</li>`).join("");
  const loop = (t.watch_proposals || []).map((w) =>
    `<li>Watch proposal "${esc(w.phrase)}" on ${esc(w.camera_id)}: ${w.accepted ? "accepted" : "rejected"} (${esc(w.reason || "")})</li>`).join("");
  return `<details class="trace" data-testid="trace"><summary>How this was decided</summary>` +
    `<ul class="trace-list">${rules}${tri}<li>Rule floor: ${esc(t.floor)}` +
    `${vi.floor_reason ? ` (${esc(vi.floor_reason)})` : ""}</li></ul>` + subjectsHtml(t) +
    `${drafts || `<p class="card-meta">Not escalated: the story is a template written by code.</p>`}` +
    `<p class="section-title">Verdict inputs</p><ul class="trace-list">` +
    `<li>floor = ${esc(vi.floor)}, unresolved gap = ${esc(vi.unresolved_gap)}, proposal = ${esc(vi.proposal)}, proposal cited = ${esc(vi.proposal_cited)}</li>` +
    `<li>verdict = <b>${esc(vi.result)}</b> (computed by code; Wonder can never lower the floor)</li></ul>` +
    (loop ? `<p class="section-title">Closed loop</p><ul class="trace-list">${loop}</ul>` : "") +
    (cal ? `<p class="section-title">Calibration of the cameras involved</p><ul class="trace-list">${cal}</ul>` : "") +
    `</details>`;
}

export function telemetryHtml(tel, open = false) {
  const rows = tel.groups.map((g) =>
    `<tr><td>${esc(g.model)}</td><td>${esc(g.purpose)}</td><td class="num">${g.count}</td>` +
    `<td class="num">${(g.latency_ms / Math.max(1, g.count)).toFixed(0)} ms</td><td class="num">${money(g.cost_usd)}</td></tr>`).join("");
  const calls = tel.calls.map((c) =>
    `<tr><td class="mono">${esc(c.id)}</td><td>${esc(c.model)}</td><td>${esc(c.purpose)}</td>` +
    `<td class="num">${c.latency_ms ?? ""} ms</td><td class="num">${money(c.cost_usd)}</td><td>${c.cached ? "cached" : "live"}</td><td>${c.ok ? "ok" : "failed"}</td></tr>`).join("");
  const t = tel.totals;
  return `<details class="telemetry-panel" data-testid="telemetry" ${open ? "open" : ""}>` +
    `<summary>Telemetry · ${t.count} model calls · ${money(t.cost_usd)} · ${t.cached} cached, ${t.live} live</summary>` +
    `<table class="telemetry"><thead><tr><th>Model</th><th>Purpose</th><th class="num">Calls</th><th class="num">Mean latency</th><th class="num">Cost</th></tr></thead>` +
    `<tbody>${rows}</tbody><tfoot><tr><th colspan="2">Total (matches the ledger)</th><th class="num">${t.count}</th><th></th><th class="num" data-testid="telemetry-total">${money(t.cost_usd)}</th></tr></tfoot></table>` +
    `<details><summary>Every call</summary><table class="telemetry"><thead><tr><th>Call</th><th>Model</th><th>Purpose</th><th class="num">Latency</th><th class="num">Cost</th><th>Mode</th><th>Result</th></tr></thead><tbody>${calls}</tbody></table></details>` +
    `</details>`;
}

export function telemetryLine(t) {
  if (!t) return "";
  const parts = [t.cached ? "Cached" : "Live", t.model, t.call_id, t.latency_ms != null ? `${t.latency_ms} ms` : null,
    t.cost_usd != null ? money(t.cost_usd) : null].filter(Boolean);
  return `<span class="telemetry-line" data-testid="telemetry-line">${parts.map(esc).join(" · ")}</span>`;
}

export function renderVisitDetail(section, visit, handlers) {
  const watches = (visit.watches || []).filter((w) => w.notice).map((w) =>
    `<div class="watch-notice" data-testid="watch-notice">◉ ${esc(w.notice)}` +
    ` <span class="card-meta">expires ${esc((w.expires_at || "").slice(0, 16).replace("T", " "))}</span>` +
    ` <button type="button" class="btn small" data-undo="${esc(w.id)}">Undo</button></div>`).join("");
  const rules = visit.rule_hits.length
    ? `<p class="rules-fired">${visit.rule_hits.map((h) => `<b>Rule ${esc(h.rule_id)} fired</b>: ${esc(h.rule_name)}`).join("; ")}</p>`
    : "";
  const subjects = visit.subjects || [];
  const roles = subjects.length
    ? `<p class="roles" data-testid="roles">Came from: ${subjects.map((s) =>
      `${roleChip(s)}<code class="role-basis">${esc(s.role_basis)}</code>`).join(" ")}</p>`
    : "";
  const windows = (visit.expected_windows || []).map((w) =>
    `<span class="window-chip" data-testid="window-chip">Expected Window ${esc(w.id)}` +
    `${w.label ? ` "${esc(w.label)}"` : ""} · ${esc((w.start || "").slice(11, 16))}–${esc((w.end || "").slice(11, 16))}` +
    `${w.cameras && w.cameras.length ? ` · ${w.cameras.map(esc).join(", ")}` : ""}</span>`).join(" ");
  section.innerHTML =
    `<article class="card" data-visit="${esc(visit.id)}" data-testid="visit-card">` +
    `<header class="card-head">${verdictHtml(visit.verdict, visit.verdict_label)}` +
    `<span class="card-meta">${esc(visit.scenario_title)} · ${esc(visit.clock)} to ${esc(visit.clock_t1)}` +
    ` · ${visit.escalated ? "escalated" : "not escalated"}</span>` +
    `<span class="pill subtle">${visit.synthetic ? "Synthetic · cached" : "Cached"}</span></header>` +
    `<ol class="story" data-testid="story">${sentencesHtml(visit.sentences)}</ol>` +
    roles + windows + watches + rules +
    `<p class="section-title">Gaps</p>${gapBarsHtml(visit)}` +
    `<p class="section-title">Events</p>${timelineHtml(visit)}` +
    `<div class="btn-row"><button type="button" class="btn live" data-testid="rerun-live" data-rerun="live">Re-run story live</button>` +
    `<button type="button" class="btn" data-rerun="cached">Show recorded re-run</button>` +
    `<button type="button" class="btn small" data-testid="feedback-expected" data-feedback="expected">This was expected</button></div>` +
    `<div class="rerun-out" data-testid="rerun-out" aria-live="polite"></div>` +
    traceHtml(visit) + telemetryHtml(visit.telemetry) +
    `</article>`;

  // Delegated, so chips in a re-run story rendered later also seek the players.
  section.onclick = (ev) => {
    const el = ev.target.closest("[data-t]");
    if (!el || !section.contains(el)) return;
    handlers.onCite({
      t: Number(el.dataset.t), camera: el.dataset.camera || null,
      event: el.dataset.event || null, gap: el.dataset.gap || null,
    });
  };
  section.querySelectorAll("[data-rerun]").forEach((el) => {
    el.addEventListener("click", () => handlers.onRerun(el.dataset.rerun === "live", el));
  });
  section.querySelectorAll("[data-feedback]").forEach((el) => {
    el.addEventListener("click", () => handlers.onFeedback && handlers.onFeedback(el.dataset.feedback, el));
  });
  section.querySelectorAll("[data-undo]").forEach((el) => {
    el.addEventListener("click", () => {
      el.closest(".watch-notice").innerHTML = "Watch undone for this session (the sandbox does not save changes).";
    });
  });
}

export function renderRerun(target, visit, job) {
  const out = job.result;
  const r = out.result || {};
  const left = `<div><b>Recorded story</b><ol class="story">${sentencesHtml(visit.sentences)}</ol></div>`;
  const right = `<div><b>${out.live ? "Live re-run" : "Recorded re-run"}</b> · ${verdictHtml(r.verdict, r.verdict_label)}` +
    `<ol class="story">${sentencesHtml(r.story || [])}</ol>` +
    `<span class="card-meta">Validator: ${r.validation && r.validation.passed ? "passed" : "failed"}${r.note ? " · " + esc(r.note) : ""}</span></div>`;
  target.innerHTML =
    (out.notice ? `<span class="notice" data-testid="fallback-notice">${esc(out.notice)}</span>` : "") +
    `<div class="side-by-side">${left}${right}</div>${telemetryLine(out.telemetry)}`;
}
