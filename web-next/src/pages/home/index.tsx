import {useState} from 'react';
import {Camera, ChevronRight, ShieldCheck} from 'lucide-react';
import type {PageProps} from '../../contracts';
import {Card, Chip, EmptyState, Tabs, VerdictBadge, VideoTile} from '../../components/ui';
import {attentionVisits, summaryText, touchComparison, viewCameras, type TouchEvidence} from './model';
import {VisitCard} from './visit-card';
import './home.css';

export function HomePage({state, onOpenVisit, onOpenClip, onViewChange, activeView,
  twinSlot, playerSlot}: PageProps) {
  const [localView, setLocalView] = useState(state.views[0]?.id ?? '');
  const selectedView = activeView ?? localView;
  const cameras = viewCameras(state, selectedView);
  const ranked = attentionVisits(state);
  const comparison = touchComparison(state);
  function changeView(id: string) {setLocalView(id); onViewChange?.(id);}
  return <div className="home-page">
    <section className="home-summary" aria-label="Activity summary">
      <div><p className="home-eyebrow">{state.evidence.kind === 'fixture' ? 'Recorded activity' : 'Activity'}</p>
        <h2>{summaryText(state.summary)}</h2>
        <p className="home-summary-note">{state.summary.note}</p>
      </div>
      {state.summary.street_events !== null && <p className="home-street-count"><ShieldCheck aria-hidden="true"/>
        <span>{state.summary.street_events} street {state.summary.street_events === 1 ? 'event' : 'events'} counted outside the property</span>
      </p>}
    </section>
    <div className="home-workspace">
      {comparison && <section className="home-context" aria-label="Same action, different context">
          <header><h2>Same action, different context</h2><p>Roles follow the observed route.</p></header>
          <div className="home-context-grid">
            <TouchCard evidence={comparison.household} label={comparison.label} context="household" onOpen={onOpenVisit}/>
            <TouchCard evidence={comparison.external} label={comparison.label} context="external" onOpen={onOpenVisit}/>
          </div>
      </section>}
      <Card title="Attention center" className="home-attention" actions={<Chip>{ranked.length} to review</Chip>}>
        <p className="home-section-note">Visits worth a closer look, in relevance order.</p>
        <div className="home-attention-list" tabIndex={0} aria-label="Visits to review">
          {ranked.length > 0 ? ranked.map(visit => <VisitCard key={visit.id} visit={visit}
            cameras={state.cameras} onOpen={onOpenVisit}/>)
            : <EmptyState title="No visits to review" description="New visits will appear when there is evidence to review."/>}
        </div>
      </Card>
      <Card title="Your home" className="home-house" actions={<Chip>{state.cameras.length} configured cameras</Chip>}>
        {state.views.length > 0 ? <Tabs className="home-view-tabs" items={state.views} value={selectedView}
          onChange={changeView} label="House views">
          <div className="home-twin" aria-label="House view">
            {twinSlot ?? <EmptyState title="House view unavailable" description="A house model has not been loaded."/>}
          </div>
        </Tabs> : <EmptyState title="No camera views configured" description="Camera views appear after the home configuration is loaded."/>}
        <div className="home-player">
          {playerSlot ?? (cameras.length === 1
            ? <VideoTile camera={cameras[0]} onOpen={onOpenClip}/>
            : <p className="home-camera-hint"><Camera aria-hidden="true"/>Select a camera in the house view to inspect its recorded evidence.</p>)}
        </div>
      </Card>
    </div>
  </div>;
}

function TouchCard({evidence, label, context, onOpen}: {evidence:TouchEvidence;label:string;
  context:'household'|'external';onOpen:(id:string)=>void}) {
  const {visit, event} = evidence;
  return <button type="button" className="home-touch-card" data-verdict={visit.verdict}
    aria-label={`Open ${context} ${label} visit`} onClick={()=>onOpen(visit.id)}>
    <div className="home-touch-top"><VerdictBadge verdict={visit.verdict}/><time>{event.clock}</time></div>
    <div className="home-touch-title"><strong>{label} touched</strong><ChevronRight aria-hidden="true"/></div>
    <p className="home-touch-role"><span>{visit.role_label}</span> · <span>{visit.role_basis}</span></p>
    <p className="home-touch-reason">{visit.reason}</p>
  </button>;
}
