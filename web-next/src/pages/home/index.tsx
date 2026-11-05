import {BellRing, Camera, ChevronRight, Maximize2, Minimize2, ShieldCheck} from 'lucide-react';
import {useState} from 'react';
import type {PageProps} from '../../contracts';
import {Chip, EmptyState, VideoTile} from '../../components/ui';
import {attentionVisits, summaryText, viewCameras} from './model';
import {FunnelBar, PeopleSeen, StoryCard, useVisitDetails, useVisitPaths, type OpenVisit} from './insights';
import './home.css';
import './insights.css';

export function HomePage({state, onOpenVisit, onOpenClip, activeView,
  twinSlot, houseSwitchSlot, playerSlot, capturesSlot}: PageProps) {
  const selectedView = activeView ?? state.views[0]?.id ?? '';
  const cameras = viewCameras(state, selectedView);
  const cameraClip = cameras.length === 1 ? state.clips.find(clip =>
    clip.camera_id === cameras[0].id && (!cameras[0].clip_url || clip.clip_url === cameras[0].clip_url)) : undefined;
  const ranked = attentionVisits(state);
  const ids = ranked.map(v => v.id);
  const details = useVisitDetails(ids);
  const paths = useVisitPaths(ids);
  const open = onOpenVisit as OpenVisit;
  const [focus, setFocus] = useState(false);
  return <div className="home-page" data-focus={focus || undefined}>
    <FunnelBar state={state} onOpenVisit={open}/>
    <section className="home-main" aria-label="Your home">
      <header className="pv-section-head"><h2>Your home</h2>{houseSwitchSlot}<Chip>{state.cameras.length} cameras</Chip>
        <button type="button" className="home-focus" aria-pressed={focus} onClick={() => setFocus(f => !f)}>{focus ? <Minimize2 aria-hidden="true"/> : <Maximize2 aria-hidden="true"/>}{focus ? 'Show visits' : 'Expand house'}</button></header>
      <div className="home-stage">
        {state.views.length > 0 ? <div className="home-twin" aria-label="House view">
            {twinSlot ?? <EmptyState title="House view unavailable" description="A house model has not been loaded."/>}
          </div> : <EmptyState title="No camera views configured" description="Camera views appear after the home configuration is loaded."/>}
        <div className="home-player">
          {playerSlot ?? (cameras.length === 1
            ? <VideoTile camera={cameras[0]} clip={cameraClip} onOpen={cameraClip ? onOpenClip : undefined}/>
            : <p className="home-camera-hint"><Camera aria-hidden="true"/>Tap a camera in the house view to see what it recorded.</p>)}
        </div>
      </div>
    </section>
    <aside className="home-side" aria-label="Today" hidden={focus}>
      <section className="home-today pv-section" aria-labelledby="home-attention-title">
        <div className={`home-summary home-hero${ranked.length?' home-hero-alert':''}`} aria-label="Activity summary" role="group">
          <span className="pv-bubble home-hero-icon" aria-hidden="true">{ranked.length?<BellRing/>:<ShieldCheck/>}</span>
          <div className="pv-row-body">
            <h2 id="home-attention-title">{ranked.length?`${ranked.length} ${ranked.length===1?'visit':'visits'} to review`:'All clear'}</h2>
            <span className="pv-meta">{summaryText(state.summary)}</span>
          </div>
        </div>
        {ranked.length > 0 ? <ul className="pv-list pv-scroll ins-list" tabIndex={0} aria-label="Visits to review">
            {ranked.map(visit => <li key={visit.id}><StoryCard state={state} visit={visit} detail={details[visit.id]} path={paths[visit.id]} onOpenVisit={open} sentences={2}/></li>)}
          </ul>
          : <EmptyState title="No visits to review" description="New visits appear here when there is evidence to look at."/>}
        <a className="home-see-all" href="#/attention">See all visits<ChevronRight aria-hidden="true"/></a>
        <p className="pv-hint home-note">{state.summary.note}{state.summary.street_events !== null && ` ${state.summary.street_events} street ${state.summary.street_events === 1 ? 'event' : 'events'} counted outside the property.`}</p>
      </section>
      <PeopleSeen limit={3}/>
      {capturesSlot}
    </aside>
  </div>;
}
