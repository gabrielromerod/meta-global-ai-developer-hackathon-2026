// Standalone task review harness. Shared application state is integrated by the lead.
import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '../../styles/tokens.css';
import '../../styles/base.css';
import fixture from '../../fixtures/state.json';
import type {UIState, Route} from '../../contracts';
import {EmptyState, Modal, VerdictBadge} from '../../components/ui';
import {AppShell} from '../../shell';
import {HomePage} from './index';
import {AttentionPage} from '../attention/index';
import './preview.css';

function Preview() {
  const [route,setRoute] = useState<Route>((new URLSearchParams(location.search).get('route') ?? 'home') as Route);
  const [theme,setTheme] = useState<'dark'|'light'>(new URLSearchParams(location.search).get('theme')==='light'?'light':'dark');
  const [visitId,setVisitId] = useState<string|null>(null);
  const [clipId,setClipId] = useState<string|null>(null);
  const state = fixture as unknown as UIState;
  document.documentElement.dataset.theme = theme;
  const visit = state.visits.find(item=>item.id===visitId);
  const props = {state,onOpenVisit:setVisitId,onOpenClip:setClipId};
  return <><AppShell route={route} onNavigate={setRoute} state={state} theme={theme}
    onThemeChange={setTheme} onOpenVisit={setVisitId}>
    {route==='attention' ? <AttentionPage {...props}/> : route==='home' ? <HomePage {...props}/>
      : <EmptyState title="This page is reviewed separately" description="Use Home or Attention to continue this task preview."/>}
  </AppShell>
    <Modal open={Boolean(visit)} title="Visit evidence" onClose={()=>setVisitId(null)}>
      {visit && <div className="home-review-detail"><VerdictBadge verdict={visit.verdict}/><h3>{visit.title}</h3><p>{visit.story}</p><p>{visit.role_basis}</p><p>{visit.reason}</p>{visit.gaps.map(gap=><p key={gap}>{gap}</p>)}<p>Media unavailable in this authored fixture.</p></div>}
    </Modal>
    <Modal open={Boolean(clipId)} title="Clip evidence" onClose={()=>setClipId(null)}><p>Media unavailable in this authored fixture.</p></Modal>
  </>;
}
createRoot(document.getElementById('root')!).render(<Preview/>);
