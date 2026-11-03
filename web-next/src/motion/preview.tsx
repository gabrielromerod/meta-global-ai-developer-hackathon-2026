import {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {MessageCircle} from 'lucide-react';
import '../styles/tokens.css';
import '../styles/base.css';
import stateFixture from '../fixtures/state.json';
import twinFixture from '../fixtures/twin.json';
import positionsFixture from '../fixtures/positions.json';
import chatFixture from '../fixtures/chat.json';
import type {ChatMessage, Route, Thread, UIState} from '../contracts';
import {Button, EmptyState, Modal, VerdictBadge} from '../components/ui';
import {AppShell} from '../shell';
import {HomePage} from '../pages/home';
import {AttentionPage} from '../pages/attention';
import {ChatPopup, MessagesPage} from '../chat';
import {HouseView} from '../twin';
import {MotionProvider, PageTransition, PanelEntrance, PanelTransition, useMotionPolicy} from './index';
import './preview.css';

const state=stateFixture as unknown as UIState;
const initialThreads=chatFixture.threads as Thread[];
const query=new URLSearchParams(location.search);
const capabilities={...state.capabilities,ask_home:false};

function Preview() {
  const [route,setRoute]=useState<Route>((query.get('route')||'home') as Route);
  const [theme,setTheme]=useState<'dark'|'light'>(query.get('theme')==='light'?'light':'dark');
  const [visitId,setVisitId]=useState<string|null>(null);
  const [clipId,setClipId]=useState<string|null>(null);
  const [popup,setPopup]=useState(false);
  const [threadId,setThreadId]=useState('household');
  const [threads,setThreads]=useState(initialThreads);
  const [drafts,setDrafts]=useState<Record<string,string>>({});
  const [cameraId,setCameraId]=useState<string|null>(null);
  const [view,setView]=useState(state.views[0]?.id||'');
  const [time,setTime]=useState(state.visits.find(v=>v.id===positionsFixture.visit_id)?.t1||0);
  const [panel,setPanel]=useState(false);
  const policy=useMotionPolicy();
  const visit=state.visits.find(v=>v.id===visitId);
  const clip=state.clips.find(c=>c.id===clipId);
  const positionData={...positionsFixture,events:state.events.filter(e=>e.visit_id===positionsFixture.visit_id)};

  useEffect(()=>{
    // Task-only inspection controls use the actual supplied record clock; no synthetic video.
    const target=window as unknown as {vigilMotionReview?:unknown};
    target.vigilMotionReview={navigate:setRoute,seek:setTime,setPanel,policy,route,time,drafts};
    document.body.dataset.ready='1';
    return ()=>{delete target.vigilMotionReview;delete document.body.dataset.ready;};
  },[policy,route,time,drafts]);

  const onSend=(id:string,text:string)=>{
    if(id!=='household')return;
    const message:ChatMessage={id:crypto.randomUUID(),author:'you',text,citations:[],clip_id:null};
    setThreads(items=>items.map(t=>t.id===id?{...t,messages:[...t.messages,message]}:t));
  };
  const shareClip=(id:string)=>{
    const selected=state.clips[0];if(!selected)return;
    const message:ChatMessage={id:crypto.randomUUID(),author:'you',text:selected.title,citations:[],clip_id:selected.id};
    setThreads(items=>items.map(t=>t.id===id?{...t,messages:[...t.messages,message]}:t));
  };
  const chatProps={threads,selectedThreadId:threadId,onSelectThread:setThreadId,onSend,
    capabilities,drafts,onDraftChange:(id:string,text:string)=>setDrafts(values=>({...values,[id]:text})),
    onShareClip:shareClip,onOpenVisit:setVisitId,onOpenClip:setClipId};
  const pageProps={state,onOpenVisit:setVisitId,onOpenClip:setClipId,activeView:view,
    onViewChange:(id:string)=>{setView(id);const selected=state.views.find(v=>v.id===id);setCameraId(selected?.camera_ids.length===1?selected.camera_ids[0]:null);},
    twinSlot:<HouseView twin={twinFixture} positions={positionData} time={time} activeCameraId={cameraId} onCameraSelect={id=>{
      setCameraId(id);const selected=state.views.find(v=>v.camera_ids.length===1&&v.camera_ids[0]===id);if(selected)setView(selected.id);
    }}/>};
  return <>
    <AppShell route={route} onNavigate={id=>{setRoute(id);setPopup(false);}} state={state} theme={theme}
      onThemeChange={setTheme} onOpenVisit={setVisitId}
      chatSlot={<><Button className="motion-review-messages" variant="secondary" onClick={()=>setPopup(v=>!v)} aria-label="Open floating Messages"><MessageCircle aria-hidden="true"/>Messages</Button><ChatPopup {...chatProps} open={popup} onClose={()=>setPopup(false)}/></>}>
      <PageTransition viewKey={route} label={`${route} view`}>
        {route==='home'?<HomePage {...pageProps}/>:route==='attention'?<AttentionPage {...pageProps}/>:route==='messages'?<MessagesPage {...chatProps}/>:<EmptyState title="Page outside this motion review" description="Home, Attention and Messages are available in this isolated component preview."/>}
      </PageTransition>
    </AppShell>
    <Modal open={Boolean(visit)} title="Visit evidence" onClose={()=>setVisitId(null)}>
      {visit&&<PanelEntrance key={visit.id} className="motion-review-detail"><VerdictBadge verdict={visit.verdict}/><h3>{visit.title}</h3><p>{visit.story}</p><p>{visit.role_basis}</p><p>{visit.reason}</p>
        <Button variant="outline" onClick={()=>setPanel(v=>!v)} aria-expanded={panel}>Recorded observations</Button>
        <PanelTransition open={panel} label="Recorded observations"><div className="motion-review-observations">{state.events.filter(e=>e.visit_id===visit.id).map(event=><Button variant="ghost" key={event.event_id} onClick={()=>{setTime(event.t);setVisitId(null);}}>{event.clock} · {event.type.replaceAll('_',' ')}</Button>)}</div></PanelTransition>
        {visit.gaps.map(gap=><p key={gap}>{gap}</p>)}<p>Media unavailable in this authored fixture.</p>
      </PanelEntrance>}
    </Modal>
    <Modal open={Boolean(clip)} title="Clip evidence" onClose={()=>setClipId(null)}><PanelEntrance><p>{clip?.title}</p><p>Media unavailable in this authored fixture.</p></PanelEntrance></Modal>
  </>;
}
createRoot(document.getElementById('root')!).render(<MotionProvider><Preview/></MotionProvider>);
