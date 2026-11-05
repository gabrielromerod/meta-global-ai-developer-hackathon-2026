/** Real-only home box (VIGIL_REAL_ONLY, owner decision Nov 4): only this home's clips, no demo bundle.
 *
 * Home opens on the house model. Each camera on it is a button: it opens that camera's latest masked
 * frame and its recent clips. Attention and Media list the analysed real clips. */
import {useQuery} from '@tanstack/react-query';
import {ArrowRight, Camera as CameraIcon, ChevronRight, Film, ScanSearch, X} from 'lucide-react';
import {useMemo, useState, type ReactNode} from 'react';
import type {UIState, Verdict} from '../contracts';
import {EmptyState, VerdictBadge} from '../components/ui';
import {api} from './api';
import {CaptureDialog, CapturedClips, PeopleStrip, Thumb, clockLabel, kindLabel, type Capture} from './captures';
import {CroppedStill} from './protection';
import './real-home.css';

const RANK: Record<string, number> = {needs_attention: 0, cant_confirm: 1, noteworthy: 2, normal: 3};

/** Analysed clips with a verdict, most serious first, then newest. */
export function reviewOrder(captures: Capture[]): Capture[] {
  return captures.filter(c => c.analysis === 'analysed' && c.verdict)
    .sort((a, b) => (RANK[a.verdict!] ?? 9) - (RANK[b.verdict!] ?? 9) || b.started_at.localeCompare(a.started_at));
}

export function RealFunnel({state}: {state: UIState}) {
  const s = state.summary;
  const n = (v: number|null|undefined) => v ?? 0;
  return <section className="real-funnel" aria-label="What your cameras saved">
    <span className="real-funnel-step"><strong>{n(s.motion_triggers)}</strong> clips saved by your cameras</span>
    <ArrowRight aria-hidden="true"/>
    <span className="real-funnel-step"><strong>{n(s.visits)}</strong> analysed by Vigil</span>
    <ArrowRight aria-hidden="true"/>
    <span className="real-funnel-step" data-alert={n(s.needs_attention) > 0 || undefined}><strong>{n(s.needs_attention)}</strong> {n(s.needs_attention) === 1 ? 'needs' : 'need'} your attention</span>
  </section>;
}

function ReviewCard({c, onOpen}: {c: Capture; onOpen: (c: Capture) => void}) {
  return <article className="real-review" data-verdict={c.verdict ?? undefined}>
    <Thumb c={c} onOpen={onOpen}/>
    <button type="button" className="real-review-text" onClick={() => onOpen(c)}>
      <span className="real-review-meta">{c.verdict && <VerdictBadge verdict={c.verdict as Verdict}/>}<time dateTime={c.started_at}>{clockLabel(c.started_at)}</time></span>
      <strong>{c.headline ?? `${kindLabel(c.kind)} at ${c.camera_name ?? c.camera_id}`}</strong>
      <span className="real-review-camera"><CameraIcon aria-hidden="true"/>{c.camera_name ?? c.camera_id}</span>
    </button>
  </article>;
}

type Preview = {camera_id: string; still: {url: string; width: number; height: number; visible?: number[]; capture_id?: string; frame_ts: number} | null};

/** What one camera sees: its latest masked frame and its recent clips (cameras' RTSP is off, so no live view). */
export function CameraPanel({cameraId, state, captures, onOpen, onClose}: {cameraId: string; state: UIState; captures: Capture[]; onOpen: (c: Capture) => void; onClose: () => void}) {
  const camera = state.cameras.find(c => c.id === cameraId);
  const preview = useQuery({queryKey: ['camera-preview', cameraId], queryFn: () => api<Preview>(`/api/ui/cameras/${encodeURIComponent(cameraId)}/preview`), retry: false});
  const mine = useMemo(() => captures.filter(c => c.camera_id === cameraId).sort((a, b) => b.started_at.localeCompare(a.started_at)), [captures, cameraId]);
  const still = preview.data?.still;
  const name = camera?.name ?? cameraId;
  const fromClip = still?.capture_id ? mine.find(c => c.id === still.capture_id) : undefined;
  return <section className="real-camera pv-section" aria-label={`${name} camera`}>
    <header className="real-camera-head">
      <span className="pv-bubble" aria-hidden="true"><CameraIcon/></span>
      <div><h2>{name}</h2><span className="pv-meta">{camera?.model ?? 'Camera'} · {mine.length} {mine.length === 1 ? 'clip' : 'clips'} recorded</span></div>
      <button type="button" className="pv-icon-btn" aria-label="Close camera" onClick={onClose}><X aria-hidden="true"/></button>
    </header>
    <div className="real-camera-body pv-scroll" tabIndex={0} aria-label={`${name}: latest frame and clips`}>
      <h3>Latest recorded frame</h3>
      {preview.isPending ? <p className="pv-hint" role="status">Loading the latest frame…</p>
        : still ? <figure className="real-camera-still">
            <CroppedStill frame={{camera_id: cameraId, name, url: still.url, frame_ts: still.frame_ts, width: still.width, height: still.height, visible: still.visible}} alt={`${name}: latest masked frame`}/>
            <figcaption>{fromClip ? <>From the clip at {clockLabel(fromClip.started_at)}. </> : null}Not live: the camera's live stream is off, so Vigil shows its newest recorded frame.</figcaption>
          </figure>
          : <p className="pv-hint">{camera?.status === 'privacy_blocked' ? 'This camera has no approved privacy review yet, so no frame is shown.' : 'No frame recorded by this camera yet.'}</p>}
      <h3>Recent clips</h3>
      {mine.length ? <ul className="real-camera-clips">
          {mine.slice(0, 12).map(c => <li key={c.id}>
            <Thumb c={c} onOpen={onOpen}/>
            <button type="button" className="real-camera-clip-text" onClick={() => onOpen(c)}>
              <span>{kindLabel(c.kind)} · <time dateTime={c.started_at}>{clockLabel(c.started_at)}</time></span>
              {c.verdict ? <><VerdictBadge verdict={c.verdict as Verdict}/>{c.headline && <small>{c.headline}</small>}</> : <small>Not analysed</small>}
            </button>
          </li>)}
        </ul>
        : <p className="pv-hint">No clips recorded by this camera yet.</p>}
    </div>
  </section>;
}

export function RealHome({state, captures, houseSlot, activeCamera, onSelectCamera}: {state: UIState; captures: Capture[]; houseSlot: ReactNode; activeCamera: string|null; onSelectCamera: (id: string|null) => void}) {
  const [open, setOpen] = useState<Capture|null>(null);
  const review = reviewOrder(captures);
  const counts = useMemo(() => captures.reduce<Record<string, number>>((m, c) => ({...m, [c.camera_id]: (m[c.camera_id] ?? 0) + 1}), {}), [captures]);
  return <div className="real-home">
    <RealFunnel state={state}/>
    <section className="real-house pv-section" aria-label="Your home">
      <header className="pv-section-head"><h2>Your home</h2><span className="pv-meta">Tap a camera to see what it recorded</span></header>
      <div className="real-house-stage" data-camera={activeCamera ? 'open' : undefined}>
        <div className="real-house-model">{houseSlot}</div>
        {activeCamera && <CameraPanel cameraId={activeCamera} state={state} captures={captures} onOpen={setOpen} onClose={() => onSelectCamera(null)}/>}
      </div>
      <div className="real-camera-chips" role="group" aria-label="Cameras">
        {state.cameras.map(c => <button key={c.id} type="button" aria-pressed={c.id === activeCamera} onClick={() => onSelectCamera(c.id === activeCamera ? null : c.id)}>
          <CameraIcon aria-hidden="true"/>{c.name}<span className="real-chip-count">{counts[c.id] ?? 0}</span>
        </button>)}
      </div>
    </section>
    <aside className="real-side" aria-label="Today">
      <section className="pv-section real-review-list" aria-labelledby="real-review-title">
        <header className="pv-section-head"><h2 id="real-review-title">Needs your review</h2><span className="pv-meta">{review.length} analysed</span></header>
        {review.length ? <ul className="pv-scroll" tabIndex={0} aria-label="Analysed clips">
            {review.slice(0, 8).map(c => <li key={c.id}><ReviewCard c={c} onOpen={setOpen}/></li>)}
          </ul>
          : <EmptyState title="Nothing analysed yet" description="Clips appear here once Vigil has written their story."/>}
        <a className="home-see-all" href="#/attention">See all analysed clips<ChevronRight aria-hidden="true"/></a>
      </section>
      <PeopleStrip compact/>
    </aside>
    <CaptureDialog capture={open} all={captures} onClose={() => setOpen(null)} onOpenCapture={setOpen}/>
  </div>;
}

const FILTERS: {id: Verdict|'all'; label: string}[] = [
  {id: 'all', label: 'All analysed'}, {id: 'needs_attention', label: 'Needs attention'},
  {id: 'noteworthy', label: 'Noteworthy'}, {id: 'cant_confirm', label: "Can't confirm"}, {id: 'normal', label: 'Normal'},
];

export function RealAttention({captures}: {captures: Capture[]}) {
  const [filter, setFilter] = useState<Verdict|'all'>('all');
  const [open, setOpen] = useState<Capture|null>(null);
  const review = reviewOrder(captures);
  const shown = review.filter(c => filter === 'all' || c.verdict === filter);
  return <div className="real-attention">
    <div className="real-filters" role="group" aria-label="Filter clips by verdict">
      {FILTERS.map(f => <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
        {f.label}<span className="real-chip-count">{f.id === 'all' ? review.length : review.filter(c => c.verdict === f.id).length}</span></button>)}
    </div>
    <section className="pv-section real-attention-list" aria-labelledby="real-attention-title">
      <header className="pv-section-head"><h2 id="real-attention-title">Analysed clips</h2><span className="pv-meta">Stories written from what SAM tracked on your cameras</span></header>
      {shown.length ? <ul className="pv-scroll real-attention-grid" tabIndex={0} aria-label="Analysed clips">
          {shown.map(c => <li key={c.id}><ReviewCard c={c} onOpen={setOpen}/></li>)}
        </ul>
        : <EmptyState title={review.length ? 'No clip with this verdict' : 'Nothing analysed yet'} description={review.length ? 'Try another filter.' : 'Clips appear here once Vigil has written their story.'}/>}
    </section>
    <CaptureDialog capture={open} all={captures} onClose={() => setOpen(null)} onOpenCapture={setOpen}/>
  </div>;
}

export function RealMedia({captures, openId}: {captures: Capture[]; openId: string|null}) {
  if (!captures.length) return <div className="real-media"><EmptyState title="No clips yet" description="Clips your cameras save appear here."/></div>;
  return <div className="real-media">
    <p className="real-media-note"><Film aria-hidden="true"/>Every clip here was saved by one of your cameras. <ScanSearch aria-hidden="true"/>Clips marked Story ready were analysed by Vigil.</p>
    <CapturedClips captures={captures} all={captures} variant="page" openId={openId}/>
  </div>;
}
