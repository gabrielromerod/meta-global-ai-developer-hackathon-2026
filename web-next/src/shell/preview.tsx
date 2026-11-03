import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {MessagesSquare} from 'lucide-react';
import {AppShell} from './index';
import {Button,Card,VerdictBadge,Modal,EmptyState,ClipCard} from '../components/ui';
import {HomePage} from '../pages/home';
import {AttentionPage} from '../pages/attention';
import fixture from '../fixtures/state.json';
import twinFixture from '../fixtures/twin.json';
import {HouseView} from '../twin';
import type {Route,UIState} from '../contracts';
import '../styles/tokens.css';
import '../styles/base.css';
import './preview.css';
const state:UIState=fixture as UIState;
function Preview(){
  const [route,setRoute]=useState<Route>('home');
  const [theme,setTheme]=useState<'dark'|'light'>('dark');
  const [activeView,setActiveView]=useState('overview');
  const [visit,setVisit]=useState<string|null>(null);
  const [chat,setChat]=useState(false);
  const [cameraId,setCameraId]=useState<string|null>(null);
  const font=new URLSearchParams(location.search).get('font')||'inter';
  useEffect(()=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.font=font;},[theme,font]);
  const selected=state.visits.find(item=>item.id===visit);
  const openClip=(id:string)=>setVisit(state.clips.find(item=>item.id===id)?.visit_id||null);
  return <AppShell route={route} onNavigate={setRoute} state={state} theme={theme} onThemeChange={setTheme} onOpenVisit={setVisit}
    chatSlot={<Button className="v-preview-message" variant="secondary" onClick={()=>setChat(true)}><MessagesSquare aria-hidden="true"/>Messages</Button>}>
    {route==='home'?<HomePage state={state} onOpenVisit={setVisit} onOpenClip={openClip} activeView={activeView} onViewChange={id=>{setActiveView(id);setCameraId(id.startsWith('camera_')?id.slice(7):null);}} twinSlot={<HouseView twin={twinFixture} activeCameraId={cameraId} onCameraSelect={id=>{setCameraId(id);setActiveView(`camera_${id}`);}}/>}/>
    :route==='attention'?<AttentionPage state={state} onOpenVisit={setVisit} onOpenClip={openClip}/>
    :route==='clips'||route==='media'?<div className="v-preview-clips">{state.clips.map(clip=><ClipCard key={clip.id} clip={clip} onOpen={openClip}/>)}</div>
    :<Card title={route==='messages'?'Messages':route==='rules'?'Rules and protected objects':route==='benchmark'?'Benchmark':'Settings'}><EmptyState title={route==='benchmark'?'No measured benchmark yet':route==='settings'?'Owner-only on the home box':route==='messages'?'No messages yet':'No further evidence in this shell preview'} description={route==='benchmark'?state.benchmark.note:undefined}/></Card>}
    <Modal title={selected?.title||'Visit evidence'} open={!!visit} onClose={()=>setVisit(null)}>{selected&&<><VerdictBadge verdict={selected.verdict}/><p>{selected.story}</p><p>{selected.role_basis}</p><p>{selected.reason}</p></>}</Modal>
    <Modal title="Messages" open={chat} onClose={()=>setChat(false)}><EmptyState title="No messages yet" description="The full Messages interface is reviewed separately."/></Modal>
  </AppShell>;
}
createRoot(document.getElementById('root')!).render(<Preview/>);
