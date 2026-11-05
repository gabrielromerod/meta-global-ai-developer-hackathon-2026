import {useQueries, useQuery} from '@tanstack/react-query';
import {ArrowRight, Camera, EyeOff, Filter, Route as RouteIcon, Users} from 'lucide-react';
import type {Camera as CameraType, UIState, VisitRow} from '../../contracts';
import {Chip, VerdictBadge} from '../../components/ui';
import {api} from '../../app/api';

/* Shared rich-visit pieces for Home and Attention. Everything shown comes from the state, the
 * visit detail (cited sentences) or the positions endpoint; nothing here infers a role or a verdict. */

type Rec = Record<string, unknown>;
export interface CitedSentence {index:number;text:string;citations:{event_id:string;clock:string;camera_name:string}[]}
interface VisitDetailLite {sentences?:CitedSentence[]}
interface Point {x:number;z:number;t:number;track:string}
interface PathData {points:Point[];gaps:{t0:number;t1:number;from:[number,number]|null;to:[number,number]|null;label:string}[]}

export type OpenVisit = (id:string, eventId?:string) => void;

const ROLE_LABEL:Record<string,string> = {
  household_insider:'Household', expected_visitor:'Expected visitor',
  external_visitor:'External visitor', unknown:'Unknown origin',
};
const ROLE_TONE:Record<string,'success'|'warning'|'danger'|'unknown'|'default'> = {
  household_insider:'success', expected_visitor:'default', external_visitor:'warning', unknown:'unknown',
};

/** The role badge comes from the visit's recorded roles only (FR-044). */
export function RoleBadge({visit}:{visit:VisitRow}) {
  const role = visit.roles[0] ?? 'unknown';
  return <Chip tone={ROLE_TONE[role] ?? 'unknown'} className="ins-role">{ROLE_LABEL[role] ?? visit.role_label}</Chip>;
}

/** Cameras in the order they first saw the visit (from its events), then any without events. */
export function cameraChain(visit:VisitRow, cameras:CameraType[], events:UIState['events'] = []):string[] {
  const seen = events.filter(e => e.visit_id === visit.id).sort((a, b) => a.t - b.t).map(e => e.camera_id);
  const order = [...new Set([...seen, ...visit.cameras])];
  return order.map(id => cameras.find(c => c.id === id)?.name ?? id);
}

/** Illustration for authored demo visits, matching the clip grid's picture for the same visit. */
export function visitIllustration(state:UIState, visit:VisitRow):string|undefined {
  if (visit.thumbnail_url) return visit.thumbnail_url;
  if (state.evidence.kind !== 'fixture') return undefined;
  const index = state.clips.findIndex(clip => clip.visit_id === visit.id);
  const n = index >= 0 ? index : state.visits.findIndex(v => v.id === visit.id);
  return `${import.meta.env.BASE_URL}illustrations/scene-${(Math.max(n, 0) % 6) + 1}.jpg`;
}

export function useVisitDetails(ids:string[]) {
  const results = useQueries({queries: ids.map(id => ({
    queryKey: ['visit', id],
    queryFn: () => api<VisitDetailLite>('/api/ui/visits/' + encodeURIComponent(id)),
    staleTime: 60_000,
  }))});
  return Object.fromEntries(ids.map((id, i) => [id, results[i]?.data])) as Record<string, VisitDetailLite|undefined>;
}

function parsePath(data:Rec|undefined):PathData|null {
  if (!data) return null;
  const pos = Array.isArray(data.positions) ? data.positions as Rec[] : [];
  const points = pos.filter(p => typeof p.x === 'number' && typeof p.z === 'number')
    .map(p => ({x:p.x as number, z:p.z as number, t:Number(p.t ?? 0), track:String(p.track_id ?? '')}));
  const xy = (v:unknown):[number,number]|null => Array.isArray(v) && typeof v[0] === 'number' && typeof v[1] === 'number' ? [v[0], v[1]] : null;
  const gaps = (Array.isArray(data.gaps) ? data.gaps as Rec[] : []).map(g => ({
    t0:Number(g.t0 ?? 0), t1:Number(g.t1 ?? 0), from:xy(g.from), to:xy(g.to), label:String(g.label ?? 'Not observed'),
  }));
  return {points, gaps};
}

export function useVisitPaths(ids:string[]) {
  const results = useQueries({queries: ids.map(id => ({
    queryKey: ['positions', id],
    queryFn: () => api<Rec>('/api/ui/visits/' + encodeURIComponent(id) + '/positions'),
    staleTime: 60_000,
  }))});
  return Object.fromEntries(ids.map((id, i) => [id, parsePath(results[i]?.data)])) as Record<string, PathData|null>;
}

/** Small top-down sketch of the estimated route. Segments never join across a gap; a gap is a
 *  grey dotted link between the last and next sighting, as in the 3D replay. */
export function MiniPath({path, label}:{path:PathData|null|undefined;label:string}) {
  if (!path || path.points.length < 2) return <span className="ins-path ins-path-empty" aria-hidden="true"><RouteIcon/></span>;
  const xs = path.points.map(p => p.x), zs = path.points.map(p => p.z);
  path.gaps.forEach(g => { [g.from, g.to].forEach(p => { if (p) { xs.push(p[0]); zs.push(p[1]); } }); });
  const x0 = Math.min(...xs), x1 = Math.max(...xs), z0 = Math.min(...zs), z1 = Math.max(...zs);
  const span = Math.max(x1 - x0, z1 - z0, 1), W = 96, H = 64, pad = 6;
  const sx = (x:number) => pad + (x - x0) / span * (W - 2 * pad);
  const sz = (z:number) => pad + (z - z0) / span * (H - 2 * pad);
  const inGap = (t:number) => path.gaps.some(g => t > g.t0 && t < g.t1);
  const segments:Point[][] = [];
  let current:Point[] = [];
  path.points.filter(p => !inGap(p.t)).forEach((p, i, all) => {
    const prev = all[i - 1];
    if (prev && (prev.track !== p.track || path.gaps.some(g => prev.t <= g.t0 && p.t >= g.t1))) { segments.push(current); current = []; }
    current.push(p);
  });
  if (current.length) segments.push(current);
  const last = path.points[path.points.length - 1];
  return <svg className="ins-path" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
    {segments.filter(s => s.length > 1).map((s, i) => <polyline key={i} points={s.map(p => `${sx(p.x)},${sz(p.z)}`).join(' ')} className="ins-path-line"/>)}
    {path.gaps.map((g, i) => g.from && g.to ? <line key={`g${i}`} x1={sx(g.from[0])} y1={sz(g.from[1])} x2={sx(g.to[0])} y2={sz(g.to[1])} className="ins-path-gap"/> : null)}
    <circle cx={sx(last.x)} cy={sz(last.z)} r="3" className="ins-path-head"/>
  </svg>;
}

/** One visit as a story card: picture, verdict, role, camera chain, cited sentences, path. */
export function StoryCard({state, visit, detail, path, onOpenVisit, sentences = 3}:{state:UIState;visit:VisitRow;
  detail?:VisitDetailLite;path?:PathData|null;onOpenVisit:OpenVisit;sentences?:number}) {
  const picture = visitIllustration(state, visit);
  const chain = cameraChain(visit, state.cameras, state.events);
  const cited = (detail?.sentences ?? []).slice(0, sentences);
  return <article className="ins-card" data-verdict={visit.verdict}>
    <button type="button" className="ins-card-open" aria-label={`Open visit ${visit.title}`} onClick={() => onOpenVisit(visit.id)}>
      <span className="ins-thumb">{picture ? <img src={picture} alt="" loading="lazy"/> : <Camera aria-hidden="true"/>}
        {state.evidence.kind === 'fixture' && !visit.thumbnail_url && <span className="ins-thumb-tag">Illustration</span>}</span>
      <span className="ins-head">
        <span className="ins-badges"><VerdictBadge verdict={visit.verdict}/><RoleBadge visit={visit}/><time>{visit.clock}</time></span>
        <strong className="ins-title">{visit.title}</strong>
        <span className="ins-chain"><Camera aria-hidden="true"/>{chain.length ? chain.join(' → ') : 'Camera not recorded'}</span>
        {visit.gaps.map((gap, i) => <span className="ins-gap" key={i}><EyeOff aria-hidden="true"/>{gap}</span>)}
      </span>
      <MiniPath path={path} label={`Estimated route for ${visit.title}`}/>
    </button>
    {cited.length > 0 ? <ol className="ins-sentences">
      {cited.map(s => <li key={s.index}><span>{s.text}</span>
        {s.citations.map(c => <button type="button" key={c.event_id} className="ins-cite" aria-label={`Open event ${c.event_id} at ${c.clock}`}
          onClick={() => onOpenVisit(visit.id, c.event_id)}>{c.event_id} · {c.clock}</button>)}</li>)}
    </ol> : <p className="ins-story">{visit.first_sentence || visit.story}</p>}
  </article>;
}

/** Alert-fatigue funnel from the session's own counts; the filtered share is computed, never typed. */
export function FunnelBar({state, onOpenVisit}:{state:UIState;onOpenVisit:OpenVisit}) {
  const {motion_triggers: triggers, visits, needs_attention: urgent} = state.summary;
  const filtered = triggers ? Math.round((1 - urgent / triggers) * 1000) / 10 : null;
  const stages = [
    ...(triggers != null ? [{n:triggers, label:triggers === 1 ? 'motion trigger' : 'motion triggers'}] : []),
    {n:visits, label:visits === 1 ? 'visit' : 'visits'},
    {n:urgent, label:'needs attention'},
  ];
  const order = [...state.attention_ids, ...state.visits.map(v => v.id)];
  const pills = [...new Set(order)].map(id => state.visits.find(v => v.id === id)).filter((v):v is VisitRow => Boolean(v));
  return <section className="ins-funnel" aria-label="Alert funnel">
    <div className="ins-funnel-stats">
      <span className="ins-funnel-icon" aria-hidden="true"><Filter/></span>
      <ol className="ins-stages">{stages.map((s, i) => <li key={s.label} data-last={i === stages.length - 1 || undefined}>
        <strong>{s.n}</strong><span>{s.label}</span>{i < stages.length - 1 && <ArrowRight aria-hidden="true"/>}</li>)}</ol>
      {filtered != null && <p className="ins-filtered"><strong>{filtered}%</strong> of motion never reached you</p>}
      {state.evidence.kind === 'fixture' && <Chip className="ins-demo">{state.evidence.label}</Chip>}
    </div>
    {pills.length > 0 && <div className="ins-pills" role="group" aria-label="Open a visit">
      {pills.map(v => <button type="button" key={v.id} className="ins-pill" data-verdict={v.verdict} onClick={() => onOpenVisit(v.id)}>
        <span className="ins-pill-dot" aria-hidden="true"/>{v.title}{v.gaps.length > 0 && <span className="ins-pill-gap">{v.gaps[0]}</span>}
      </button>)}
    </div>}
  </section>;
}

interface Profile {id:string;name:string|null;count:number;basis:string;label:string|null;seen_label:string;crops:string[];sightings:{capture_id:string;seen_at:string}[]}

/** Recurring people from /api/ui/faces (opt-in, LAN only). Real counts; labels are clothing, never roles. */
export function PeopleSeen({limit = 4}:{limit?:number}) {
  const faces = useQuery({queryKey:['faces'], queryFn:() => api<{enabled:boolean;profiles:Profile[]}>('/api/ui/faces'), retry:false, staleTime:60_000});
  const profiles = (faces.data?.profiles ?? []).slice(0, limit);
  if (!faces.data?.enabled || !profiles.length) return null;
  return <section className="ins-people pv-section" aria-labelledby="ins-people-title">
    <header className="pv-section-head"><h2 id="ins-people-title"><Users aria-hidden="true"/>People seen on the property</h2></header>
    <ul className="ins-people-list">{profiles.map(p => {
      const last = p.sightings[0]?.seen_at;
      return <li key={p.id} className="ins-person">
        <span className="ins-person-crop">{p.crops[0] ? <img src={p.crops[0]} alt="" loading="lazy"/> : <Users aria-hidden="true"/>}</span>
        <span className="ins-person-body"><strong>{p.name ?? (p.count > 1 ? 'Recurring visitor' : 'Visitor')}</strong>
          <span className="ins-person-seen">{p.seen_label}</span>
          <span className="pv-meta">{p.basis === 'clothing' ? `By clothing: ${p.label}` : 'By face'}{last ? ` · last ${new Date(last).toLocaleString([], {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'})}` : ''}</span></span>
      </li>;
    })}</ul>
    <p className="pv-hint">Grouped inside the property only. Rules and roles never use these profiles.</p>
  </section>;
}
