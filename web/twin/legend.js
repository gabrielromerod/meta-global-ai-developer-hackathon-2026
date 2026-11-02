// Always-visible legend for the 3D view and its 2D fallback (spec 7, encoding table).
// Every entry is text plus a shape, never colour alone.

const ITEMS = [
  ["cone", "Camera view cone",
    '<svg viewBox="0 0 26 16"><path d="M2 8 24 2v12z" fill="rgba(79,195,247,.25)" stroke="#4fc3f7" stroke-width="1.4"/></svg>'],
  ["pending", "Presence on camera, position pending (cone pulses)",
    '<svg viewBox="0 0 26 16"><path d="M2 8 24 2v12z" fill="none" stroke="#4fc3f7" stroke-width="1.4" stroke-dasharray="2 2"/><path d="M5 4.5a5 5 0 0 1 0 7" fill="none" stroke="#4fc3f7"/></svg>'],
  ["coverage", "Camera coverage",
    '<svg viewBox="0 0 26 16"><rect x="2" y="2" width="22" height="12" rx="2" fill="rgba(110,160,220,.35)" stroke="rgba(110,160,220,.8)"/></svg>'],
  ["blind", "Blind region: no camera sees it",
    '<svg viewBox="0 0 26 16"><defs><pattern id="lg-hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" stroke="#9aa0a6" stroke-width="1.6"/></pattern></defs><rect x="2" y="2" width="22" height="12" fill="url(#lg-hatch)" stroke="#9aa0a6"/></svg>'],
  ["disc", "Estimated position (radius = 95% uncertainty)",
    '<svg viewBox="0 0 26 16"><circle cx="13" cy="8" r="6.5" fill="rgba(242,178,51,.3)" stroke="#f2b233" stroke-width="1.4" stroke-dasharray="2.5 2"/></svg>'],
  ["fused", "Estimated from 2 cameras",
    '<svg viewBox="0 0 26 16"><circle cx="13" cy="8" r="6.5" fill="none" stroke="#f2b233" stroke-width="1.4"/><circle cx="13" cy="8" r="4" fill="none" stroke="#f2b233" stroke-width="1.4"/></svg>'],
  ["low", "Low confidence (height prior)",
    '<svg viewBox="0 0 26 16"><circle cx="13" cy="8" r="6.5" fill="none" stroke="#f2b233" stroke-width="2"/></svg>'],
  ["path", "Observed path",
    '<svg viewBox="0 0 26 16"><line x1="2" y1="8" x2="24" y2="8" stroke="#f2b233" stroke-width="2.4"/></svg>'],
  ["gap", "Not observed (gap): no positions drawn",
    '<svg viewBox="0 0 26 16"><line x1="2" y1="8" x2="24" y2="8" stroke="#9aa0a6" stroke-width="2.4" stroke-dasharray="1 3.5" stroke-linecap="round"/></svg>'],
  ["protected", "Protected object footprint",
    '<svg viewBox="0 0 26 16"><rect x="6" y="3" width="14" height="10" fill="none" stroke="#f2b233" stroke-width="1.6" stroke-dasharray="3 2"/></svg>'],
];

export function renderLegend(el) {
  el.innerHTML = ITEMS.map(([key, text, svg]) =>
    `<span class="legend-item" data-legend="${key}">${svg.replace("<svg ", '<svg aria-hidden="true" ')}<span>${text}</span></span>`,
  ).join("");
}
