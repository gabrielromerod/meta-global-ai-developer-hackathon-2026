import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {BellRing, Car, PersonStanding, ScanFace} from 'lucide-react';
import {useEffect, useRef, useState, type SyntheticEvent} from 'react';
import {Modal, VerdictBadge} from '../components/ui';
import type {Verdict} from '../contracts';
import {api} from './api';
import './captures.css';

/** One clip recorded by `vigil reolink guard` from a camera alert (`GET /api/ui/captures`). */
export type Capture = {id:string; camera_id:string; camera_name:string|null; kind:string; started_at:string; ended_at:string|null; partial:boolean; clip_url:string|null; masked:boolean|null; analysis:'not_analysed'|'analysed'; layer:'camera_ai'};

const KIND_LABEL: Record<string,string> = {person:'Person', vehicle:'Vehicle', pet:'Pet', doorbell_press:'Doorbell pressed', motion:'Motion'};

export function kindLabel(kind: string): string { return KIND_LABEL[kind] ?? kind; }

/** "5:07 PM" today, "Nov 3, 5:07 PM" otherwise. */
export function clockLabel(iso: string, now = Date.now()): string {
  const t = new Date(iso);
  const time = t.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
  return new Date(now).toDateString() === t.toDateString() ? time : `${t.toLocaleDateString([], {month: 'short', day: 'numeric'})}, ${time}`;
}

/** Seconds as m:ss, the way video players show time. */
export function mmss(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

const isPerson = (c: Capture) => c.kind === 'person' || c.kind === 'doorbell_press';
const endOf = (c: Capture) => Date.parse(c.ended_at ?? c.started_at);
const lengthOf = (c: Capture) => (endOf(c) - Date.parse(c.started_at)) / 1000;

export type CaptureGroup = {id:string; start:string; end:string; items:Capture[]; lead:Capture; cameras:string[]; hasPerson:boolean; hasVehicle:boolean};

function toGroup(items: Capture[]): CaptureGroup {
  const sorted = [...items].sort((a, b) => a.started_at.localeCompare(b.started_at));
  const people = sorted.filter(isPerson);
  const lead = [...people].sort((a, b) => Number(b.analysis === 'analysed') - Number(a.analysis === 'analysed') || lengthOf(b) - lengthOf(a))[0] ?? sorted[0];
  return {
    id: sorted[0].id,
    start: sorted[0].started_at,
    end: sorted.map(x => x.ended_at ?? x.started_at).sort().at(-1)!,
    items: sorted,
    lead,
    cameras: [...new Set(sorted.map(x => x.camera_name ?? x.camera_id))],
    hasPerson: people.length > 0,
    hasVehicle: sorted.some(x => x.kind === 'vehicle'),
  };
}

/**
 * Moments with a person, newest first. Person/doorbell clips that start within ``gapMs`` of the
 * previous one's end form one moment; a vehicle clip joins only when it overlaps the moment
 * (from ``leadMs`` before its first person clip to its end). Passing cars never chain moments.
 */
export function groupCaptures(captures: Capture[], gapMs = 60_000, leadMs = 60_000): CaptureGroup[] {
  const people = captures.filter(isPerson).sort((a, b) => a.started_at.localeCompare(b.started_at));
  const clusters: Capture[][] = [];
  for (const c of people) {
    const last = clusters.at(-1);
    if (last && Date.parse(c.started_at) - Math.max(...last.map(endOf)) <= gapMs) last.push(c); else clusters.push([c]);
  }
  return clusters.map(cluster => {
    const from = Date.parse(cluster[0].started_at) - leadMs;
    const to = Math.max(...cluster.map(endOf));
    const cars = captures.filter(c => c.kind === 'vehicle' && endOf(c) >= from && Date.parse(c.started_at) <= to);
    return toGroup([...cluster, ...cars]);
  }).reverse();
}

function groupTitle(g: CaptureGroup): string {
  if (g.items.some(x => x.kind === 'doorbell_press')) return 'Doorbell';
  return g.hasVehicle ? 'Car and person' : 'Person';
}

/** LAN-only list of real captured clips; empty (and quiet) where the route is refused. */
export function useCaptures(): Capture[] {
  const query = useQuery({
    queryKey: ['ui-captures'],
    queryFn: () => api<{captures: Capture[]}>('/api/ui/captures'),
    refetchInterval: 10_000,
    retry: false,
  });
  return query.data?.captures ?? [];
}

/* ------------------------------------------------------------------------------------------ */
/* Analysis: what Vigil made of a capture                                                      */

type Kind = 'person' | 'vehicle' | string;

/** What Vigil made of one capture (`GET /api/ui/captures/{id}/analysis`). Times are seconds into the camera clip. */
export type CaptureAnalysis = {
  id:string; verdict:Verdict|null; story_source:string|null; visits:number;
  clip:{duration:number}|null;
  story:{text:string; source:'wonder'|'template'|'code'|string; event_ids:string[]; gap_id:string|null; at:number|null; kind:Kind|null}[];
  subjects:{id:string; actor_role:string; role_basis:string; kind:Kind|null}[];
  gaps:{id:string; kind:string; resolved:boolean}[];
  tracks:{tag:string; phrase:string|null; class:string|null; upper_color:string|null; lower_color:string|null; vehicle_color:string|null; vehicle_body:string|null; carrying:string[]|null; from:number|null; to:number|null}[];
  tagged:{window_id:string; url:string; offset:number|null}[];
  moment?:{id:string; clips:string[]; cameras:string[]; verdict:Verdict|null; story:string[]}|null;
};
type Track = CaptureAnalysis['tracks'][number];

const known = (v: string|null|undefined) => v && v !== 'unknown' ? v : null;

/** A track as plain words: its kind (SAM's phrase, Spark's class) and Spark's notes, unknowns left out. */
export function describeTrack(t: Track): {kind: Kind; notes: string} {
  const kind = t.class ?? (t.phrase === 'car' ? 'vehicle' : t.phrase) ?? 'object';
  const notes = kind === 'vehicle'
    ? [known(t.vehicle_color), known(t.vehicle_body)].filter(Boolean).join(' ')
    : [known(t.upper_color) && `${t.upper_color} top`, known(t.lower_color) && `${t.lower_color} bottom`, ...(t.carrying ?? [])].filter(Boolean).join(', ');
  return {kind, notes};
}

/** Tracks with the same description, shown once with all their tags (same look, not the same person). */
export function groupTracks(tracks: Track[]): {kind: Kind; notes: string; tags: string[]; colors: string[]}[] {
  const rows = new Map<string, {kind: Kind; notes: string; tags: string[]; colors: string[]}>();
  for (const t of tracks) {
    const {kind, notes} = describeTrack(t);
    const colors = (kind === 'vehicle' ? [t.vehicle_color] : [t.upper_color, t.lower_color]).filter((c): c is string => Boolean(known(c)));
    const key = `${kind}|${notes}`;
    const row = rows.get(key) ?? {kind, notes, tags: [], colors};
    row.tags.push(t.tag);
    rows.set(key, row);
  }
  return [...rows.values()];
}

/** Identical sentences (one per track fragment) shown once, with every moment they cite. */
export function storyRows(story: CaptureAnalysis['story']): {text: string; times: number[]; kind: Kind|null}[] {
  const rows: {text: string; times: number[]; kind: Kind|null}[] = [];
  for (const s of story) {
    if (s.source === 'code') continue;
    const row = rows.find(r => r.text === s.text);
    if (row) { if (s.at !== null) row.times.push(s.at); continue; }
    rows.push({text: s.text, times: s.at === null ? [] : [s.at], kind: s.kind});
  }
  return rows;
}

/** Why a person got their role, in the owner's words (FR-044 role_basis). */
export function roleNote(subjects: CaptureAnalysis['subjects']): string | null {
  const people = subjects.filter(s => s.kind === 'person');
  if (!people.length) return null;
  const basis = people.map(s => s.role_basis.split(':')[0]);
  if (basis.includes('perimeter')) return 'Came in from the street, so rules for visitors apply.';
  if (basis.every(b => b === 'egress' || b === 'group')) return 'Came out of the house, so Vigil treats them as household.';
  if (basis.includes('window')) return 'Arrived during an expected visit.';
  if (basis.includes('checkin')) return 'Matched a household check-in.';
  return 'First seen in the yard rather than at a door or the street, so Vigil does not assume they live here.';
}

const SWATCH: Record<string,string> = {black: '#1d1f23', white: '#f4f5f7', grey: '#8d939c', gray: '#8d939c', red: '#d2423c', orange: '#e8833a', yellow: '#e8c547', green: '#4f9d5d', blue: '#3f76c9', brown: '#7b5537', beige: '#d8c4a0', purple: '#7d55b8', pink: '#e48fb1', silver: '#bfc5cc'};

function KindIcon({kind}: {kind: Kind|null}) {
  return kind === 'vehicle' ? <Car aria-hidden="true"/> : kind === 'doorbell_press' ? <BellRing aria-hidden="true"/> : <PersonStanding aria-hidden="true"/>;
}

function useCaptureAnalysis(capture: Capture|null) {
  return useQuery({
    queryKey: ['ui-capture-analysis', capture?.id],
    queryFn: () => api<CaptureAnalysis>(`/api/ui/captures/${encodeURIComponent(capture!.id)}/analysis`),
    enabled: capture?.analysis === 'analysed',
    retry: false,
  });
}

/** Lanes of when each kind of subject was in view, with the story's moments on top. */
function Timeline({a, duration, now, onSeek}: {a: CaptureAnalysis; duration: number; now: number; onSeek: (t: number) => void}) {
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / duration) * 100))}%`;
  const lanes = (['vehicle', 'person'] as const).map(kind => ({kind, spans: a.tracks.filter(t => describeTrack(t).kind === kind && t.from !== null)})).filter(l => l.spans.length);
  const marks = a.story.filter(s => s.source !== 'code' && s.at !== null);
  return <div className="ev-timeline">
    <div className="ev-lanes" onClick={e => { const r = e.currentTarget.getBoundingClientRect(); onSeek(((e.clientX - r.left) / r.width) * duration); }} aria-hidden="true">
      {lanes.map(lane => <div className="ev-lane" key={lane.kind} data-kind={lane.kind}>
        {lane.spans.map(t => <span key={t.tag} className="ev-span" style={{left: pct(t.from!), width: `max(4px, ${pct((t.to ?? t.from!) - t.from!)})`}}/>)}
      </div>)}
      <div className="ev-marks">
        {marks.map((s, i) => <span key={i} className="ev-mark" data-kind={s.kind ?? undefined} style={{left: pct(s.at!)}}/>)}
      </div>
      <span className="ev-playhead" style={{left: pct(now)}}/>
    </div>
    <div className="ev-legend">
      {lanes.map(l => <span key={l.kind} data-kind={l.kind}><KindIcon kind={l.kind}/>{l.kind === 'vehicle' ? 'Car in view' : 'Person in view'}</span>)}
      <time className="ev-clock">{mmss(now)} / {mmss(duration)}</time>
    </div>
  </div>;
}

/** The capture with what Vigil found: video and timeline left, verdict and story right. */
function EvidenceViewer({capture, all = [], onOpenCapture}: {capture: Capture; all?: Capture[]; onOpenCapture?: (c: Capture) => void}) {
  const analysis = useCaptureAnalysis(capture);
  const video = useRef<HTMLVideoElement>(null);
  const [layer, setLayer] = useState<'camera'|'sam'>('camera');
  const [now, setNow] = useState(0);
  const a = analysis.data;
  const tagged = a?.tagged[0];
  const offset = layer === 'sam' && tagged ? (tagged.offset ?? 0) : 0;
  const src = layer === 'sam' && tagged ? tagged.url : capture.clip_url!;
  const duration = a?.clip?.duration ?? Math.max(1, lengthOf(capture));
  const gap = a?.story.find(s => s.source === 'code');
  const rows = a ? storyRows(a.story) : [];
  const role = a ? roleNote(a.subjects) : null;
  const seek = (t: number) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = Math.max(0, t - offset);
    void v.play()?.catch(() => undefined);
  };
  return <div className="ev">
    <div className="ev-stage">
      <div className="ev-video">
        <video ref={video} key={src} src={src} controls autoPlay muted playsInline onTimeUpdate={e => setNow(e.currentTarget.currentTime + offset)}/>
        {tagged && <div className="ev-layer" role="group" aria-label="Video">
          <button type="button" aria-pressed={layer === 'camera'} onClick={() => setLayer('camera')}>Camera</button>
          <button type="button" aria-pressed={layer === 'sam'} onClick={() => setLayer('sam')}>What the models saw</button>
        </div>}
      </div>
      {a && <Timeline a={a} duration={duration} now={now} onSeek={seek}/>}
      {a && a.tracks.length > 0 && <section className="ev-section" aria-labelledby="ev-seen">
          <h3 id="ev-seen">Seen</h3>
          <ul className="ev-seen">
            {groupTracks(a.tracks).map(g => <li key={`${g.kind}${g.notes}`}>
              <span className="ev-seen-icon" data-kind={g.kind}><KindIcon kind={g.kind}/></span>
              <span className="ev-seen-text"><strong>{g.kind === 'vehicle' ? 'Vehicle' : g.kind === 'person' ? 'Person' : g.kind}</strong>{g.notes ? <span>{g.notes}</span> : <span>No colours visible</span>}</span>
              <span className="ev-swatches" aria-hidden="true">{g.colors.map((c, i) => <span key={i} style={{background: SWATCH[c] ?? 'var(--v-raised)'}}/>)}</span>
              <span className="ev-tags" title="SAM track tags">{g.tags.join(' ')}</span>
            </li>)}
          </ul>
        </section>}
      <p className="ev-source">{layer === 'sam' ? 'Masked copy with SAM\'s tags, as sent to the models.' : capture.masked === false ? 'Original camera video, only shown on your home network.' : 'Masked camera video.'}{capture.partial ? ' The camera stopped recording before the event ended.' : ''}</p>
    </div>
    <div className="ev-side">
      {!a && <p className="ev-pending">{capture.analysis === 'analysed' ? (analysis.isError ? 'The analysis could not be loaded. Close and open the clip to try again.' : 'Loading what Vigil found.') : 'Vigil has not analysed this clip yet. This is what the camera saved when it detected someone.'}</p>}
      {a && <>
        <section className="ev-verdict" aria-label="Verdict">
          {a.verdict && <VerdictBadge verdict={a.verdict}/>}
          {gap && <p>{gap.text}</p>}
          {role && <p>{role}</p>}
        </section>
        {a.moment && <section className="ev-section ev-moment" aria-labelledby="ev-moment">
          <h3 id="ev-moment">Seen by {a.moment.clips.length} cameras</h3>
          <div className="ev-moment-cams" role="group" aria-label="Switch camera">
            {a.moment.clips.map(id => { const c = all.find(x => x.id === id); return <button type="button" key={id} aria-pressed={id === capture.id} disabled={!c?.clip_url || id === capture.id} onClick={() => c && onOpenCapture?.(c)}>{c?.camera_name ?? c?.camera_id ?? 'Other camera'}</button>; })}
          </div>
          <p className="ev-moment-note">Vigil joined both clips on one clock and followed the person from one camera to the other.</p>
          <ol className="ev-moment-story">{a.moment.story.map(t => <li key={t}>{t}</li>)}</ol>
        </section>}
        <section className="ev-section" aria-labelledby="ev-story">
          <h3 id="ev-story">What happened</h3>
          <ol className="ev-story">
            {rows.map(r => <li key={r.text} data-kind={r.kind ?? undefined}>
              <span className="ev-times">{r.times.map(t => <button type="button" key={t} onClick={() => seek(t)} aria-label={`Play from ${mmss(t)}`}>{mmss(t)}</button>)}</span>
              <p>{r.text}</p>
            </li>)}
          </ol>
        </section>
        <FaceProfiles capture={capture}/>
        <p className="ev-foot">{a.story_source === 'wonder' ? 'Written by Muse Wonder' : 'Written by Vigil\'s code, no model,'} from the events SAM tracked. Tap a time to see that moment.</p>
      </>}
    </div>
  </div>;
}

/** A recurring-visitor profile from local face templates (`GET /api/ui/captures/{id}/faces`). */
export type FaceProfile = {id:string; name:string|null; flagged:boolean; count:number; seen_label:string; basis?:'face'|'clothing'; label?:string|null; sightings:{capture_id:string; seen_at:string}[]; crops:string[]};
type FaceList = {enabled:boolean; models_ready:boolean; profiles:FaceProfile[]; note:string};

function FaceCard({p, captureId}: {p: FaceProfile; captureId: string}) {
  const queries = useQueryClient();
  const [draft, setDraft] = useState(p.name ?? '');
  const refresh = () => queries.invalidateQueries({queryKey: ['ui-capture-faces', captureId]});
  const save = useMutation({mutationFn: (name: string) => api(`/api/faces/${p.id}/name`, {name: name.trim() || null}), onSuccess: refresh});
  const forget = useMutation({mutationFn: () => api(`/api/faces/${p.id}`, undefined, 'DELETE'), onSuccess: refresh});
  const error = save.error ?? forget.error;
  const earlier = p.sightings.filter(s => s.capture_id !== captureId).slice(0, 4);
  return <li className="ev-face" data-recurring={p.count > 1 || undefined}>
    <div className="ev-face-crops" data-basis={p.basis}>{p.crops.slice(0, 4).map(src => <img key={src} src={src} alt=""/>)}</div>
    <div className="ev-face-body">
      <strong>{p.name ?? (p.count > 1 ? 'Recurring visitor' : p.basis === 'clothing' ? 'Visitor' : 'New face')}</strong>
      <span>{p.seen_label}</span>
      {p.basis === 'clothing' && <span className="ev-face-basis">Matched by clothing ({p.label}), not by face. People dressed alike are grouped together.</span>}
      {earlier.length > 0 && <span className="ev-face-when">Other times: {[...new Set(earlier.map(s => clockLabel(s.seen_at)))].join(', ')}</span>}
    </div>
    <form className="ev-face-name" onSubmit={e => { e.preventDefault(); save.mutate(draft); }}>
      <label className="sr-only" htmlFor={`face-${p.id}`}>Name for this face</label>
      <input id={`face-${p.id}`} value={draft} maxLength={40} placeholder="Give it a name" onChange={e => setDraft(e.target.value)}/>
      <button type="submit" disabled={save.isPending || draft === (p.name ?? '')}>Save</button>
      <button type="button" className="ev-face-forget" disabled={forget.isPending} onClick={() => forget.mutate()}>Forget</button>
    </form>
    {error && <p className="ev-face-error" role="alert">{/40[13]|owner/i.test(error.message) ? 'Only the owner can change this. Add your owner token in Settings.' : error.message}</p>}
  </li>;
}

function FaceProfiles({capture}: {capture: Capture}) {
  const faces = useQuery({
    queryKey: ['ui-capture-faces', capture.id],
    queryFn: () => api<FaceList>(`/api/ui/captures/${encodeURIComponent(capture.id)}/faces`),
    retry: false,
  });
  const d = faces.data;
  if (!d?.enabled) return null;
  return <section className="ev-section" aria-labelledby="ev-faces">
    <h3 id="ev-faces"><ScanFace aria-hidden="true"/>Seen before</h3>
    {d.profiles.length > 0
      ? <ul className="ev-faces">{d.profiles.map(p => <FaceCard key={p.id} p={p} captureId={capture.id}/>)}</ul>
      : <p className="ev-pending">{d.models_ready ? 'No face was large enough to keep, and the clothing notes were too vague to match. People far from the camera are skipped.' : 'Face matching is on, but the face models are not installed on this home box yet.'}</p>}
    <p className="ev-foot">Kept only on this home box. Faces need to be at least 24 pixels wide; otherwise Vigil matches by clothing. Names stay on this card; stories never use them.</p>
  </section>;
}

/* ------------------------------------------------------------------------------------------ */
/* Cards                                                                                       */

/** Clips can open before the first keyframe (green frame); use a frame from the middle as poster. */
function seekMiddle(event: SyntheticEvent<HTMLVideoElement>) {
  const v = event.currentTarget;
  if (Number.isFinite(v.duration) && v.duration > 0) v.currentTime = v.duration / 2;
}

/** A clip thumbnail that only starts loading once it is near the viewport (keeps Wi-Fi light). */
export function LazyClip({src}: {src: string}) {
  const box = useRef<HTMLSpanElement>(null);
  const [near, setNear] = useState(typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    const el = box.current;
    if (near || !el) return;
    const io = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) { setNear(true); io.disconnect(); } }, {rootMargin: '200px'});
    io.observe(el);
    return () => io.disconnect();
  }, [near]);
  return <span ref={box} className="capture-lazy">{near && <video src={src} preload="metadata" muted playsInline onLoadedMetadata={seekMiddle}/>}</span>;
}

function Thumb({c, onOpen, large = false}: {c: Capture; onOpen: (c: Capture) => void; large?: boolean}) {
  const seconds = c.ended_at && lengthOf(c) >= 1 ? lengthOf(c) : null;
  return <button type="button" className="capture-thumb" data-large={large || undefined} disabled={!c.clip_url} onClick={() => onOpen(c)} aria-label={`${kindLabel(c.kind)} at ${c.camera_name ?? c.camera_id}, ${clockLabel(c.started_at)}${c.analysis === 'analysed' ? ', story ready' : ''}`}>
    {c.clip_url ? <LazyClip src={c.clip_url}/> : <span className="capture-missing">No clip</span>}
    {!large && <span className="capture-kind"><KindIcon kind={c.kind}/></span>}
    {large && c.analysis === 'analysed' && <span className="capture-story">Story ready</span>}
    {seconds !== null && <span className="capture-duration">{mmss(seconds)}</span>}
  </button>;
}

type Filter = 'people' | 'all';

/**
 * Real camera clips. ``rail`` is the Home side rail: moments with a person only, one large
 * lead clip each; ``page`` adds an "All clips" grid for passing cars and other alerts.
 */
export function CapturedClips({captures, variant = 'page', all}: {captures: Capture[]; variant?: 'page' | 'rail' | 'analysed'; all?: Capture[]}) {
  const [open, setOpen] = useState<Capture|null>(null);
  const [filter, setFilter] = useState<Filter>('people');
  if (!captures.length) return null;
  const rail = variant !== 'page';
  const moments = groupCaptures(captures).slice(0, rail ? 10 : 20);
  const flat = [...captures].sort((a, b) => b.started_at.localeCompare(a.started_at)).slice(0, 48);
  const showMoments = rail || filter === 'people';
  return <section className="captures" data-variant={variant} aria-labelledby={`captures-title-${variant}`}>
    <header className="captures-head">
      <h2 id={`captures-title-${variant}`}>{variant === 'analysed' ? 'Recorded at your home' : rail ? 'Recent recordings' : 'Recorded by your cameras'}</h2>
      {variant === 'analysed' && <p className="captures-note">Real camera clips Vigil has analysed, with their stories. The visits below are demo data.</p>}
      {!rail && <div className="captures-filters" role="group" aria-label="Show">
        <button type="button" aria-pressed={filter === 'people'} onClick={() => setFilter('people')}>People</button>
        <button type="button" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All clips</button>
      </div>}
      {!rail && <p className="captures-note">Clips your cameras saved when they detected something. Vigil has not analysed them unless they say Story ready.</p>}
    </header>
    <div className="captures-body">
      {showMoments && moments.length === 0 && <p className="captures-empty">No person recorded yet. Passing cars are under All clips in Media.</p>}
      {showMoments && moments.map(g => <article className="capture-moment" key={g.id}>
        <Thumb c={g.lead} onOpen={setOpen} large/>
        <div className="capture-moment-text">
          <h3>{groupTitle(g)}</h3>
          <time dateTime={g.start}>{clockLabel(g.start)}</time>
          <p>{g.cameras.join(', ')}</p>
        </div>
        {g.items.length > 1 && <ul className="captures-mini" aria-label="Other clips of this moment">
          {g.items.filter(x => x.id !== g.lead.id).slice(0, 4).map(c => <li key={c.id}><Thumb c={c} onOpen={setOpen}/></li>)}
        </ul>}
      </article>)}
      {!showMoments && <ul className="captures-grid">{flat.map(c => <li key={c.id}><Thumb c={c} onOpen={setOpen}/><span className="capture-grid-meta">{c.camera_name ?? c.camera_id}<time dateTime={c.started_at}>{clockLabel(c.started_at)}</time></span></li>)}</ul>}
    </div>
    <Modal className="ev-dialog" open={open !== null} title={open ? `${open.camera_name ?? open.camera_id}, ${clockLabel(open.started_at)}` : 'Clip'} onClose={() => setOpen(null)}>
      {open?.clip_url && <EvidenceViewer key={open.id} capture={open} all={all ?? captures} onOpenCapture={setOpen}/>}
    </Modal>
  </section>;
}
