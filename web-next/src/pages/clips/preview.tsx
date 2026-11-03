// Isolated fixture review harness; production API and shared state remain lead-owned.
import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import '../../styles/tokens.css';
import '../../styles/base.css';
import fixture from '../../fixtures/state.json';
import type {Route,UIState} from '../../contracts';
import {AppShell} from '../../shell';
import {Button,EmptyState,Modal,VerdictBadge} from '../../components/ui';
import {ClipsPage} from './index';
import {MediaPage} from '../media';
import './preview.css';

declare global {interface Window {clipsReview?:{lastClipId:string|null;lastVisitId:string|null;lastSearch:Record<string,string>|null}}}
function Preview() {
  const query=new URLSearchParams(location.search);
  const [route,setRoute]=useState<Route>(query.get('route')==='media'?'media':'clips');
  const [theme,setTheme]=useState<'dark'|'light'>(query.get('theme')==='light'?'light':'dark');
  const [clipId,setClipId]=useState<string|null>(null);
  const [visitId,setVisitId]=useState<string|null>(null);
  const [lastSearch,setLastSearch]=useState<Record<string,string>|null>(null);
  const state=fixture as unknown as UIState;
  const displayed=query.get('empty')==='1'?{...state,clips:[]}:state;
  const clip=state.clips.find(item=>item.id===clipId);
  const visit=state.visits.find(item=>item.id===(visitId??clip?.visit_id));
  window.clipsReview={lastClipId:clipId,lastVisitId:visitId,lastSearch};
  document.body.dataset.ready='1';
  const props={state:displayed,onOpenClip:setClipId,onOpenVisit:setVisitId,onSearch:setLastSearch};
  return <><AppShell state={displayed} route={route} onNavigate={setRoute} theme={theme} onThemeChange={setTheme} onOpenVisit={setVisitId}>
    {route==='clips'?<ClipsPage {...props}/>:route==='media'?<MediaPage {...props}/>:<EmptyState title="This page is reviewed separately" description="Use Clips or Media library for this preview."/>}
  </AppShell><Modal open={Boolean(clipId||visitId)} title={clipId?'Clip evidence':'Visit evidence'} onClose={()=>{setClipId(null);setVisitId(null);}}>
    <div className="clips-preview-evidence">{clip && <p>{state.cameras.find(camera=>camera.id===clip.camera_id)?.name}</p>}
      {visit && <><VerdictBadge verdict={visit.verdict}/><h3>{visit.title}</h3><p>{visit.story}</p><p>{visit.role_basis}</p><p>{visit.reason}</p></>}
      <EmptyState title="Media unavailable" description="This authored fixture has no recorded video or camera snapshots."/>
      {clip && <Button variant="outline" onClick={()=>{setVisitId(clip.visit_id);setClipId(null);}}>Open visit evidence</Button>}
    </div>
  </Modal></>;
}
createRoot(document.getElementById('root')!).render(<Preview/>);
