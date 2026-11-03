import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {useLocation,useNavigate} from 'react-router-dom';
import type {ChatMessage,ChatProps,PageProps,Route,Rule,Thread,UIState} from '../contracts';
import {AppShell} from '../shell';
import {Button,EmptyState,Modal,VideoTile,VerdictBadge} from '../components/ui';
import {HomePage} from '../pages/home';
import {AttentionPage} from '../pages/attention';
import {ClipsPage} from '../pages/clips';
import {MediaPage} from '../pages/media';
import {RulesPage} from '../pages/rules';
import {SettingsPage} from '../pages/settings';
import {BenchmarkPage} from '../pages/benchmark';
import {ChatPopup,MessagesPage} from '../chat';
import {HouseView} from '../twin';
import {MotionProvider,PageTransition} from '../motion';
import {api} from './api';
import {localThreads,readableError} from './model';
import {VisitReview} from './visit';
import {VoiceDialog} from './voice-dialog';
import './app.css';

const routes:Route[]=['home','attention','clips','media','messages','rules','benchmark','settings'];
export function VigilApp(){
  const state=useQuery({queryKey:['ui-state'],queryFn:()=>api<UIState>('/api/ui/state')});
  if(state.isPending)return <main className="app-start" role="status"><h1>Vigil</h1><p>Loading home evidence…</p></main>;
  if(state.isError)return <main className="app-start"><h1>Vigil</h1><p role="alert">{readableError(state.error)}</p><Button onClick={()=>void state.refetch()}>Try again</Button></main>;
  return <MotionProvider><Workspace state={state.data}/></MotionProvider>;
}
function Workspace({state:original}:{state:UIState}){
  const navigate=useNavigate(),location=useLocation(),queries=useQueryClient();
  const parts=location.pathname.split('/').filter(Boolean);
  const route:Route=routes.includes(parts[0] as Route)?parts[0] as Route:'home';
  const visitId=parts[0]==='visit'?decodeURIComponent(parts[1]??''):null;
  const [theme,setTheme]=useState<'dark'|'light'>(()=>localStorage.getItem('vigil_theme')==='light'?'light':'dark');
  const [view,setView]=useState(original.views[0]?.id??'');
  const [activeCamera,setActiveCamera]=useState<string|null>(null);
  const [chatOpen,setChatOpen]=useState(false),[threadId,setThreadId]=useState('ask-home');
  const [drafts,setDrafts]=useState<Record<string,string>>({});
  const [messages,setMessages]=useState(()=>localThreads(localStorage.getItem(`vigil_local_threads:${original.session.id}`)));
  const [read,setRead]=useState<string[]>([]),[shareThread,setShareThread]=useState<string|null>(null);
  const [selectedClip,setSelectedClip]=useState<string|null>(null);
  const [notice,setNotice]=useState<string|null>(null);
  const [expires,setExpires]=useState<string|null>(null);
  const [ruleDraft,setRuleDraft]=useState<Rule|null>(null),[transcript,setTranscript]=useState('');
  const [ruleNotice,setRuleNotice]=useState<string|null>(null);
  const [ruleExplanation,setRuleExplanation]=useState<{applies_label:string;basis_note:string;limits_note:string[]}|undefined>();
  const [voiceOpen,setVoiceOpen]=useState(false),[snapshotUrl,setSnapshotUrl]=useState<string|null>(null),[snapshotAvailable,setSnapshotAvailable]=useState(false);
  const snapshotter=useRef<(()=>Promise<Blob>)|null>(null);
  const snapshotReady=useCallback((capture:(()=>Promise<Blob>)|null)=>{snapshotter.current=capture;setSnapshotAvailable(Boolean(capture));},[]);
  useEffect(()=>()=>{if(snapshotUrl)URL.revokeObjectURL(snapshotUrl);},[snapshotUrl]);
  const twin=useQuery({queryKey:['ui-twin'],queryFn:()=>api<Record<string,unknown>>('/api/ui/twin')});
  const chat=useQuery({queryKey:['ui-chat'],queryFn:()=>api<{threads:Thread[]}>('/api/ui/chat')});
  const voices=useQuery({queryKey:['voice-fixtures'],queryFn:()=>api<{fixtures:{id:string;label:string;wav_url:string|null}[]}>('/api/voice/fixtures'),enabled:route==='rules'});
  const state={...original,notifications:original.notifications.map(n=>({...n,unread:n.unread&&!read.includes(n.id)}))};
  useEffect(()=>{document.body.dataset.ready='1';return()=>{delete document.body.dataset.ready;};},[]);
  useEffect(()=>{localStorage.setItem('vigil_theme',theme);},[theme]);
  useEffect(()=>{localStorage.setItem(`vigil_local_threads:${state.session.id}`,JSON.stringify({household:messages.household??[]}));},[messages.household,state.session.id]);
  const refresh=()=>queries.invalidateQueries({queryKey:['ui-state']});
  const owner=useMutation({mutationFn:({path,body,method}:{path:string;body?:unknown;method?:string})=>api<{checkin?:{start:string;expires:string};binds_within_s?:number}>(path,body,method),onSuccess:result=>{if(result.checkin)setExpires(new Date(Date.parse(result.checkin.start)+(result.binds_within_s??state.owner.checkin_duration_s)*1000).toISOString());void refresh();}});
  const rules=useMutation({mutationFn:({path,body}:{path:string;body:unknown})=>api<{result?:{rule?:Rule;text?:string;applies_label?:string;basis_note?:string;limits_note?:string[]};notice?:string;note?:string}>(path,body),onSuccess:result=>{if(result.result?.rule){setRuleDraft(result.result.rule);setRuleExplanation({applies_label:result.result.applies_label??'',basis_note:result.result.basis_note??'',limits_note:result.result.limits_note??[]});}setRuleNotice(result.notice||result.note||'Recorded result shown. No model request was made.');void refresh();}});
  const voice=useMutation({mutationFn:(id:string)=>api<{result:{transcript:string};notice?:string}>('/api/voice/transcribe',{fixture_id:id,live:false}),onSuccess:result=>{setTranscript(result.result.transcript);setRuleNotice(result.notice||'Cached transcript shown. Review the text before drafting.');}});
  const search=useMutation({mutationFn:(filters:Record<string,string>)=>api<{clips:unknown[]}>('/api/ui/search?'+new URLSearchParams(filters)),onSuccess:result=>setNotice(`${result.clips.length} matching clips confirmed by the home box.`)});
  const send=useMutation({mutationFn:(text:string)=>api<{message:ChatMessage}>('/api/chat/ask',{thread_id:'ask-home',session_id:state.session.id,text})});
  function openVisit(id:string){setRead(items=>[...new Set([...items,...state.notifications.filter(n=>n.visit_id===id).map(n=>n.id)])]);navigate('/visit/'+encodeURIComponent(id));}
  function openClip(id:string){const clip=state.clips.find(c=>c.id===id);if(!clip)return;setSelectedClip(id);openVisit(clip.visit_id);}
  function selectCamera(id:string){setActiveCamera(id);setView(state.views.find(v=>v.id===`camera-${id}`)?.id??view);}
  function changeView(id:string){setView(id);const ids=state.views.find(v=>v.id===id)?.camera_ids??[];setActiveCamera(ids.length===1?ids[0]:null);}
  function append(id:string,message:ChatMessage){setMessages(current=>({...current,[id]:[...(current[id]??[]),message]}));}
  const chatProps:ChatProps={threads:(chat.data?.threads??[]).map(thread=>({...thread,messages:[...thread.messages,...(messages[thread.id]??[])]})),selectedThreadId:threadId,onSelectThread:setThreadId,drafts,onDraftChange:(id,text)=>setDrafts(d=>({...d,[id]:text})),capabilities:{...state.capabilities,snapshot:snapshotAvailable,recording:false},pending:send.isPending,error:send.isError?readableError(send.error):chat.isError?readableError(chat.error):null,onOpenVisit:openVisit,onOpenClip:openClip,onShareClip:setShareThread,onSnapshot:async()=>{try{if(snapshotter.current)setSnapshotUrl(URL.createObjectURL(await snapshotter.current()));}catch(error){setNotice(readableError(error));}},onSend:async(id,text)=>{
    if(id==='household'){append(id,{id:crypto.randomUUID(),author:'you',text,citations:[],clip_id:null});return;}
    const result=await send.mutateAsync(text);
    append(id,{id:crypto.randomUUID(),author:'you',text,citations:[],clip_id:null});append(id,result.message);
  }};
  const house=useMemo(()=>twin.data?{...twin.data,cameras:(twin.data.cameras as Record<string,unknown>[]??[]).map(c=>({...c,source_label:state.cameras.find(cam=>cam.id===c.id)?.source_label??''}))}:null,[twin.data,original.cameras]);
  const selectedCamera=state.cameras.find(c=>c.id===activeCamera);
  const props:PageProps={state,onOpenVisit:openVisit,onOpenClip:openClip,onViewChange:changeView,activeView:view,
    twinSlot:house?<HouseView forceMap={new URLSearchParams(window.location.search).get('twin')==='2d'} twin={house} lighting={view==='day'||view==='night'?view:undefined} activeCameraId={activeCamera} onCameraSelect={selectCamera} preset={view==='left-passage'?'left':view==='backyard'?'backyard':view==='front-garden'||view==='porch'?'front':undefined}/>:<EmptyState title={twin.isError?'House view unavailable':'Loading house view'} description={twin.isError?readableError(twin.error):undefined}/>,
    playerSlot:view==='day'||view==='night'?<p className="home-camera-hint">{view==='day'?'Day':'Night'} schematic preview. Recorded clips keep their original lighting.</p>:selectedCamera?<VideoTile camera={selectedCamera} clip={state.clips.find(c=>c.camera_id===selectedCamera.id)} onOpen={openClip}/>:undefined,
    onSearch:filters=>search.mutate(filters),
    ownerActions:{pending:owner.isPending,error:owner.isError?readableError(owner.error):null,checkinExpiresAt:expires,saveToken:token=>{sessionStorage.setItem('vigil_owner_token',token);void refresh();},checkIn:()=>owner.mutate({path:'/api/checkin',body:{}}),createWindow:window=>owner.mutate({path:'/api/windows',body:window}),cancelWindow:id=>owner.mutate({path:'/api/windows/'+encodeURIComponent(id),method:'DELETE'})},
    ruleActions:{explanation:ruleExplanation,draft:ruleDraft,transcript,notice:ruleNotice,pending:rules.isPending||voice.isPending,error:rules.isError?readableError(rules.error):voice.isError?readableError(voice.error):null,compile:text=>rules.mutate({path:'/api/rules/compile',body:{text,live:false}}),confirm:id=>rules.mutate({path:'/api/rules/'+encodeURIComponent(id)+'/confirm',body:{}}),voiceFixtures:(voices.data?.fixtures??[]).map(f=>({...f,url:f.wav_url})),transcribeFixture:id=>voice.mutate(id),recordVoice:()=>setVoiceOpen(true)},
  };
  return <><AppShell title={visitId?'Visit evidence':undefined} state={state} route={route} onNavigate={id=>{navigate('/'+id);if(id==='messages')setChatOpen(false);}} theme={theme} onThemeChange={setTheme} onOpenVisit={openVisit} chatSlot={route!=='messages'?<ChatPopup {...chatProps} open={chatOpen} onClose={()=>setChatOpen(false)}/>:undefined}>
    <PageTransition viewKey={visitId?'visit:'+visitId:route}>
      {visitId?<VisitReview id={visitId} state={state} twin={house} initialClipId={selectedClip} onBack={()=>navigate('/attention')} onShare={clip=>{setSelectedClip(clip);setShareThread(threadId);}} onSnapshotReady={snapshotReady}/>:route==='home'?<HomePage {...props}/>:route==='attention'?<AttentionPage {...props}/>:route==='clips'?<ClipsPage {...props}/>:route==='media'?<MediaPage {...props}/>:route==='messages'?<MessagesPage {...chatProps}/>:route==='rules'?<RulesPage {...props}/>:route==='settings'?<SettingsPage {...props}/>:<BenchmarkPage {...props}/>}
    </PageTransition>
  </AppShell>
  {route!=='messages'&&<Button className="app-messages-pill" hidden={chatOpen} aria-haspopup="dialog" aria-expanded={chatOpen} onClick={()=>setChatOpen(true)}>Messages</Button>}
  <Modal open={shareThread!==null} title="Share a clip" onClose={()=>setShareThread(null)} description="Shared cards stay in this browser. They are not delivered to other people."><div className="app-share-list">{state.clips.length?state.clips.map(clip=><Button key={clip.id} variant="outline" onClick={()=>{append(shareThread!,{id:crypto.randomUUID(),author:'you',text:clip.title,citations:[],clip_id:clip.id});setShareThread(null);setChatOpen(route!=='messages');}}><VerdictBadge verdict={clip.verdict}/><span>{state.cameras.find(c=>c.id===clip.camera_id)?.name} · {clip.clock}</span></Button>):<EmptyState title="No clips to share"/>}</div></Modal>
  <Modal open={Boolean(notice||search.isError)} title="Media search" onClose={()=>{setNotice(null);search.reset();}}><p role={search.isError?'alert':'status'}>{search.isError?readableError(search.error):notice}</p></Modal>
  <Modal open={Boolean(snapshotUrl)} title="Camera snapshot" onClose={()=>setSnapshotUrl(null)} description="Decoded from the selected exported video. No camera connection is opened.">{snapshotUrl&&<><img className="app-snapshot" src={snapshotUrl} alt="Selected camera video frame"/><Button asChild variant="outline"><a href={snapshotUrl} download="vigil-snapshot.png">Save PNG snapshot</a></Button></>}</Modal>
  <VoiceDialog open={voiceOpen} onClose={()=>setVoiceOpen(false)} onTranscript={(text,notice)=>{setTranscript(text);setRuleNotice(notice);}}/>
  </>;
}
