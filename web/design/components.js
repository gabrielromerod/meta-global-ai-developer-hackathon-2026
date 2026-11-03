// Shared primitive seed; Agent A owns the final accessible presentation.
import { html, useEffect, useRef } from "./runtime.js";
import { icons } from "../vendor/lucide.js";
export function Icon({ name, label, size }) {
  const nodes = icons[name];
  if (!nodes) throw new Error(`Unknown icon: ${name}`);
  return html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width=${size || "var(--v-icon)"} height=${size || "var(--v-icon)"} role=${label ? "img" : undefined} aria-label=${label} aria-hidden=${label ? undefined : "true"}>${nodes.map(([tag, attrs]) => html`<${tag} ...${attrs} />`)}</svg>`;
}
export function Card({ title, actions, className = "", children }) {
  return html`<section class=${`v-card ${className}`}>${title && html`<header><h2>${title}</h2>${actions}</header>`}${children}</section>`;
}
export function Chip({ children, tone }) { return html`<span class="v-chip" data-tone=${tone}>${children}</span>`; }
const verdicts = { normal: "Normal", noteworthy: "Noteworthy", needs_attention: "Needs attention", cant_confirm: "Can't confirm" };
export function VerdictBadge({ verdict, label }) {
  return html`<${Chip} tone=${verdict}><span aria-hidden="true">${verdict === "normal" ? "✓" : "!"}</span>${label || verdicts[verdict] || verdicts.cant_confirm}<//>`;
}
export function Tabs({ items, value, onChange, label }) {
  return html`<div class="v-tabs" role="group" aria-label=${label}>${items.map(item => html`<button type="button" aria-pressed=${item.id === value} onClick=${() => onChange(item.id)}>${item.label}</button>`)}</div>`;
}
export function EmptyState({ title, description, action }) {
  return html`<div class="v-empty"><h3>${title}</h3>${description && html`<p>${description}</p>`}${action}</div>`;
}
export function Skeleton({ label = "Loading" }) { return html`<div class="v-skeleton" role="status">${label}</div>`; }
export function VideoTile({ camera, clip, onOpen }) {
  return html`<${Card} title=${camera.name}>${clip?.clip_url ? html`<video muted playsinline controls src=${clip.clip_url}></video>` : html`<${EmptyState} title="No clip available" description=${camera.source_label} />`}${onOpen && html`<button onClick=${() => onOpen(camera.id)}>Open camera</button>`}<//>`;
}
export function ClipCard({ clip, onOpen }) {
  return html`<button class="v-clip" onClick=${() => onOpen(clip)}><${VerdictBadge} verdict=${clip.verdict} /><span>${clip.title}</span><time>${clip.clock}</time></button>`;
}
export function Timeline({ events, time, onSeek }) {
  return html`<div class="v-timeline" aria-label="Events">${events.map(event => html`<button aria-current=${event.t === time ? "true" : undefined} onClick=${() => onSeek(event.t)}>${event.clock} · ${event.type}</button>`)}</div>`;
}
export function Modal({ open, title, onClose, children }) {
  const ref = useRef();
  useEffect(() => { if (open && !ref.current.open) ref.current.showModal(); else if (!open && ref.current.open) ref.current.close(); }, [open]);
  return html`<dialog ref=${ref} aria-label=${title} onCancel=${onClose}><h2>${title}</h2>${children}<button onClick=${onClose}>Close</button></dialog>`;
}
