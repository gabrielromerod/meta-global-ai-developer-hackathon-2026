import {useEffect, useState} from 'react';
import './live-alerts.css';

/** One camera push alert from `/api/live/stream` (presence only: no pixels, no position). */
export type LiveAlert = {id:string; camera_id:string; camera_name:string; kind:string; started_at:string; ended_at:string|null; open:boolean};

const KIND_LABEL: Record<string,string> = {person:'Person', vehicle:'Vehicle', pet:'Pet', doorbell_press:'Doorbell pressed'};
const KEEP = 20;
const SHOW_CLOSED_MS = 12_000;

/** Upsert by id, newest first, bounded. Pure, so the stream order never duplicates a card. */
export function mergeAlert(list: LiveAlert[], row: LiveAlert): LiveAlert[] {
  const rest = list.filter(a => a.id !== row.id);
  return [row, ...rest].sort((a, b) => b.started_at.localeCompare(a.started_at)).slice(0, KEEP);
}

/** Alerts worth a card now: every open one, plus ones that closed in the last few seconds. */
export function visibleAlerts(list: LiveAlert[], now: number): LiveAlert[] {
  return list.filter(a => a.open || (a.ended_at !== null && now - Date.parse(a.ended_at) < SHOW_CLOSED_MS)).slice(0, 4);
}

/** Subscribes to the LAN live stream. Gives up quietly where it is refused (hosted sandbox). */
export function useLiveAlerts(): {alerts: LiveAlert[]; connected: boolean} {
  const [alerts, setAlerts] = useState<LiveAlert[]>([]);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (typeof EventSource === 'undefined') return;
    let opened = false;
    const source = new EventSource('/api/live/stream');
    source.addEventListener('hello', () => { opened = true; setConnected(true); });
    source.addEventListener('camera_ai', event => {
      try { setAlerts(list => mergeAlert(list, JSON.parse((event as MessageEvent).data) as LiveAlert)); } catch { /* malformed row: ignore */ }
    });
    source.onerror = () => { setConnected(false); if (!opened) source.close(); };
    return () => source.close();
  }, []);
  return {alerts, connected};
}

function ago(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  return s < 5 ? 'now' : s < 60 ? `${s}s ago` : `${Math.round(s / 60)} min ago`;
}

export function LiveAlerts({alerts, onSelect}: {alerts: LiveAlert[]; onSelect?: (cameraId: string) => void}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);
  const shown = visibleAlerts(alerts, now);
  if (!shown.length) return null;
  return <section className="live-alerts" aria-label="Live camera alerts" aria-live="polite">
    {shown.map(a => <button type="button" key={a.id} className="live-alert" data-open={a.open} onClick={() => onSelect?.(a.camera_id)}>
      <span className="live-alert-dot" aria-hidden="true"/>
      <span className="live-alert-text"><strong>{KIND_LABEL[a.kind] ?? a.kind}</strong><span>{a.camera_name}</span></span>
      <span className="live-alert-time">{a.open ? 'Live' : ago(a.ended_at ?? a.started_at, now)}</span>
    </button>)}
  </section>;
}

/**
 * Presence on the house: which camera sees someone right now. A camera alert only says *that*
 * the camera saw a person, not *where*; the 3D position needs SAM tracks and calibration.
 */
export function LivePresence({alerts, onSelect}: {alerts: LiveAlert[]; onSelect?: (cameraId: string) => void}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);
  const shown = visibleAlerts(alerts, now).slice(0, 3);
  if (!shown.length) return null;
  return <div className="live-presence" aria-live="polite" aria-label="Seen by your cameras now">
    {shown.map(a => <button type="button" key={a.id} className="live-presence-pill" data-open={a.open} onClick={() => onSelect?.(a.camera_id)}>
      <span className="live-alert-dot" aria-hidden="true"/>
      <strong>{KIND_LABEL[a.kind] ?? a.kind}</strong>
      <span>{a.camera_name} · {a.open ? 'live' : ago(a.ended_at ?? a.started_at, now)}</span>
    </button>)}
    <span className="live-presence-note">Camera alert · position not estimated</span>
  </div>;
}
