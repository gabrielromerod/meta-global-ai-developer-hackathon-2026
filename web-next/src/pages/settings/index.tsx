import {useEffect,useId,useRef,useState,type FormEvent,type ReactNode} from 'react';
import {Box,CalendarClock,Camera as CameraIcon,ChevronRight,Clock3,DoorOpen,EyeOff,FileX,Film,House,Info,KeyRound,LockKeyhole,MicOff,Plug,Plus,Router,ShieldAlert,ShieldCheck,Video,Wifi,X} from 'lucide-react';
import {api} from '../../app/api';
import {CroppedStill} from '../../app/protection';
import type {Camera,ExpectedWindow,NewExpectedWindow,PageProps,UIState} from '../../contracts';
import {Button,Chip,EmptyState,Modal,Tabs} from '../../components/ui';
import {Field,formatRecordedTime,PageHeading,StatusChip,words} from './controls';
import './controls.css';

const tabs=[{id:'cameras',label:'Cameras'},{id:'privacy',label:'Privacy'},{id:'owner',label:'Owner access'}];
export function SettingsPage(props:PageProps){
  const [tab,setTab]=useState('cameras');
  return <div className="controls-page settings-page"><PageHeading title="Home setup" description="Cameras, privacy and owner access." action={<Chip>{props.state.cameras.length} configured cameras</Chip>}/>
    <Tabs items={tabs} value={tab} onChange={setTab} label="Settings sections" className="controls-tabs pv-tabs"><div className="pv-body st-body">
      {tab==='cameras'?<Cameras cameras={props.state.cameras}/>:tab==='privacy'?<Privacy cameras={props.state.cameras}/>:props.ownerSlot??<div className="st-col st-narrow"><OwnerControls {...props} section="access" notice={false}/></div>}
    </div></Tabs>
  </div>;
}
interface CameraFacts {id:string;captures:number;privacy_reviewed:boolean;placement_measured:boolean;zones:number}
interface Preview {width:number;height:number;still:{url:string;width:number;height:number;frame_ts:number;capture_id:string;camera_id:string;name:string;visible?:number[]}|null;zones:{name:string;kind:string|null;points:number[][]}[]}
/** LAN-only facts from the home box; null in the hosted sandbox or when unreachable. */
function useCameraFacts(){
  const [facts,setFacts]=useState<Record<string,CameraFacts>|null>(null);
  useEffect(()=>{let live=true;api<{cameras:CameraFacts[]}>('/api/ui/cameras/overview').then(r=>{if(live)setFacts(Object.fromEntries(r.cameras.map(c=>[c.id,c])));}).catch(()=>{});return()=>{live=false;};},[]);
  return facts;
}
/** Badges state only what is true: a reviewed mask, captured clips, a measured position. */
function CameraBadges({camera,facts}:{camera:Camera;facts?:CameraFacts}){
  const reviewed=facts?facts.privacy_reviewed:camera.privacy_reviewed===true;
  return <>{camera.status==='privacy_blocked'||camera.privacy_reviewed===false?<Chip tone="warning">Privacy review required</Chip>:reviewed&&<Chip tone="success">Street mask enforced</Chip>}
    {facts&&facts.captures>0?<Chip tone="success">{facts.captures} event clips</Chip>:camera.status==='not_connected'?<Chip>No live stream</Chip>:camera.status!=='privacy_blocked'&&<StatusChip value={camera.status}/>}</>;
}
function CameraPreview({camera}:{camera:Camera}){
  const [preview,setPreview]=useState<Preview|null|undefined>(undefined);
  useEffect(()=>{let live=true;setPreview(undefined);api<Preview>(`/api/ui/cameras/${encodeURIComponent(camera.id)}/preview`).then(r=>{if(live)setPreview(r);}).catch(()=>{if(live)setPreview(null);});return()=>{live=false;};},[camera.id]);
  if(preview===undefined||preview===null)return null;
  if(!preview.still)return <p className="pv-hint">No recorded clip from this camera yet, so there is no masked preview.</p>;
  const still=preview.still,sx=still.width/preview.width,sy=still.height/preview.height;
  const kinds=[...new Set(preview.zones.map(z=>z.kind||'zone'))];
  const legend:Record<string,string>={perimeter:'Street edge (outside the property)',interior_yard:'Yard',egress:'Door or gate'};
  return <figure className="st-preview" aria-label={`${camera.name} masked preview with zones`}>
    <CroppedStill frame={{...still,source:'capture'}} alt={`${camera.name} masked preview`}>{preview.zones.map(z=><polygon key={z.name} className="st-zone" data-kind={z.kind||undefined} points={z.points.map(([x,y])=>`${x*sx},${y*sy}`).join(' ')}><title>{z.name}</title></polygon>)}</CroppedStill>
    {kinds.length>0&&<figcaption className="st-zone-legend">{kinds.map(k=><span key={k}><i style={{background:k==='perimeter'?'var(--v-warning)':k==='interior_yard'?'var(--v-success)':'var(--v-accent)'}}/>{legend[k]||k.replaceAll('_',' ')}</span>)}</figcaption>}
  </figure>;
}
function powerLabel(camera:Camera){return camera.power_profile==='battery_wifi'?'Battery':camera.power_profile==='import'?'Battery / imported clips':'AC power';}
function DetailRow({icon,label,value,tone}:{icon:ReactNode;label:string;value:string;tone?:'warning'}){
  return <li className="pv-row"><span className="pv-bubble" aria-hidden="true">{icon}</span><div className="pv-row-body"><span className="pv-meta">{label}</span><strong className={tone?'st-warn':undefined}>{value}</strong></div></li>;
}
function Cameras({cameras}:{cameras:Camera[]}){
  const [selectedId,setSelectedId]=useState(cameras[0]?.id??'');
  const selected=cameras.find(c=>c.id===selectedId)??cameras[0];
  const facts=useCameraFacts();
  if(!cameras.length)return <EmptyState title="No cameras configured" description="Cameras appear after the home configuration is loaded."/>;
  const clockWarn=selected.clock_offset_s!==null&&Math.abs(selected.clock_offset_s)>2;
  return <div className="st-layout">
    <section className="st-col" aria-labelledby="st-cameras-title">
      <header className="pv-section-head"><h2 id="st-cameras-title">Cameras</h2><span className="pv-meta">{cameras.length} configured</span></header>
      <ul className="pv-list pv-scroll st-list" tabIndex={0} aria-label="Camera list">{cameras.map(camera=>{const isSelected=camera.id===selected.id;const extra=camera.source_label.toLowerCase()!==camera.status.replaceAll('_',' ').toLowerCase();
        return <li key={camera.id}><article className="pv-row st-pick" data-selected={isSelected||undefined} aria-label={`${camera.name} camera`} onClick={()=>setSelectedId(camera.id)}>
          <span className="pv-bubble" aria-hidden="true"><CameraIcon/></span>
          <div className="pv-row-body"><strong>{camera.name}</strong><span className="pv-meta">{camera.model||'Model not confirmed'} · {powerLabel(camera)}</span></div>
          <div className="pv-row-end st-chips"><CameraBadges camera={camera} facts={facts?.[camera.id]}/>{extra&&camera.status!=='not_connected'&&<Chip>{camera.source_label}</Chip>}</div>
          <button type="button" className="pv-icon-btn" aria-pressed={isSelected} aria-label={`Show ${camera.name} details`} onClick={event=>{event.stopPropagation();setSelectedId(camera.id);}}><ChevronRight aria-hidden="true"/></button>
        </article></li>;})}</ul>
    </section>
    <section className="st-col" aria-label={`${selected.name} details`}>
      <header className="st-detail-head"><span className="pv-bubble st-bubble-lg" aria-hidden="true"><CameraIcon/></span><div className="pv-row-body"><h2>{selected.name}</h2><span className="pv-meta">{selected.model||'Model not confirmed'}</span></div></header>
      <div className="pv-scroll st-stack" tabIndex={0} aria-label="Camera details">
        <CameraPreview camera={selected}/>
        <ul className="pv-list st-list">
          <DetailRow icon={<ShieldCheck/>} label="Street privacy mask" value={selected.status==='privacy_blocked'||selected.privacy_reviewed===false?'Review required before ingest':selected.privacy_reviewed?'Enforced on every clip':'Review not confirmed'} tone={selected.status==='privacy_blocked'||selected.privacy_reviewed===false?'warning':undefined}/>
          {facts?.[selected.id]&&<DetailRow icon={<Video/>} label="Event clips captured" value={facts[selected.id].captures?`${facts[selected.id].captures} clips`:'None yet'}/>}
          <DetailRow icon={<Box/>} label="Position on the house model" value={facts?.[selected.id]?.placement_measured?'Measured':'Estimated, not measured'}/>
          <DetailRow icon={<Plug/>} label="Power" value={powerLabel(selected)}/>
          <DetailRow icon={<Wifi/>} label="Wi-Fi signal" value={selected.wifi_signal_dbm===null?'Not measured':`${selected.wifi_signal_dbm} dBm`}/>
          <DetailRow icon={<Clock3/>} label="Clock offset" value={selected.clock_offset_s===null?'Not measured':`${selected.clock_offset_s.toFixed(2)} s`} tone={clockWarn?'warning':undefined}/>
          <DetailRow icon={<Router/>} label="Home Hub" value={selected.hub_present===null?'Not confirmed':selected.hub_present?'Present':'Not present'}/>
          <DetailRow icon={<Film/>} label="Source" value={selected.status==='not_connected'?'Event clips from camera alerts (no live stream)':selected.source_label}/>
        </ul>
        {clockWarn&&<p className="controls-error">Clock sync required before linking cameras.</p>}
        {['battery_wifi','import'].includes(selected.power_profile)&&<p className="pv-footnote"><Info aria-hidden="true"/>Battery cameras never hold a stream open.</p>}
      </div>
    </section>
  </div>;
}
function reviewState(camera:Camera):{label:string;ok:boolean}{
  if(camera.status==='privacy_blocked'||camera.privacy_reviewed===false)return {label:'Review required',ok:false};
  return camera.privacy_reviewed===true?{label:'Reviewed',ok:true}:{label:'Review not confirmed',ok:false};
}
function Privacy({cameras}:{cameras:Camera[]}){
  const reviewed=cameras.filter(c=>reviewState(c).ok).length;
  const masks=['Sky and mountain ridgeline','Opposite houses and cars','Neighbouring driveways and cars','Curb numbers and distant street furniture','On-screen timestamp and camera watermark'];
  return <div className="st-layout">
    <section className="st-col" aria-labelledby="st-review-title">
      <header className="pv-section-head"><h2 id="st-review-title">Review every camera</h2><span className="pv-meta">{reviewed} of {cameras.length} reviewed</span></header>
      <p className="pv-hint">Ingest stays blocked until the owner approves a real still and its exact privacy masks.</p>
      <ul className="pv-list pv-scroll st-list" tabIndex={0} aria-label="Camera privacy reviews">{cameras.map(camera=>{const review=reviewState(camera);
        return <li className="pv-row" key={camera.id} aria-label={`${camera.name} privacy review`}><span className="pv-bubble" aria-hidden="true">{review.ok?<ShieldCheck/>:<ShieldAlert/>}</span><div className="pv-row-body"><strong>{camera.name}</strong><span className="pv-meta">{review.ok?'Masks approved on the home box':'Approve a still and its masks on the home box'}</span></div><Chip tone={review.ok?'success':'warning'}>{review.label}</Chip></li>;})}</ul>
    </section>
    <section className="st-col" aria-labelledby="st-masks-title">
      <header className="pv-section-head"><h2 id="st-masks-title">What stays private</h2></header>
      <div className="pv-scroll st-stack" tabIndex={0} aria-label="Privacy policy">
        <ul className="pv-list st-list" aria-label="Front panorama masks">{masks.map(mask=><li className="pv-row" key={mask}><span className="pv-bubble" aria-hidden="true"><EyeOff/></span><div className="pv-row-body"><strong>{mask}</strong><span className="pv-meta">Masked on the front panorama</span></div></li>)}</ul>
        <p className="pv-hint">The near street, sidewalk and owned property remain visible.</p>
        <ul className="pv-list st-list" aria-label="Evidence rules">
          <li className="pv-row"><span className="pv-bubble" aria-hidden="true"><MicOff/></span><div className="pv-row-body"><strong>Silent evidence</strong><span className="pv-meta">Camera audio is never used. Ingest rejects any audio stream.</span></div></li>
          <li className="pv-row"><span className="pv-bubble" aria-hidden="true"><FileX/></span><div className="pv-row-body"><strong>Metadata-free exports</strong><span className="pv-meta">Exported assets lose EXIF and GPS metadata.</span></div></li>
        </ul>
        <p className="pv-footnote"><Info aria-hidden="true"/>Mask coverage requires owner review on the home box. Templates are not field acceptance.</p>
      </div>
    </section>
  </div>;
}
export function Household({state}:PageProps){
  return <ul className="pv-list st-list" aria-label="Household"><li className="pv-row"><span className="pv-bubble st-avatar" aria-hidden="true">{state.household.avatar_url?<img src={state.household.avatar_url} alt=""/>:<House/>}</span><div className="pv-row-body"><strong>{state.household.name}</strong><span className="pv-meta">Household messages stay local to this browser. No people-to-people messaging server is connected.</span></div></li></ul>;
}
export function OwnerControls({state,ownerActions,section='access',notice=true}:PageProps & {section?:'access'|'visitors';notice?:boolean}){
  const id=useId();
  const [token,setToken]=useState('');
  const [label,setLabel]=useState('');
  const [start,setStart]=useState('');
  const [end,setEnd]=useState('');
  const [camera,setCamera]=useState('');
  const [error,setError]=useState<string|null>(null);
  const [windowOpen,setWindowOpen]=useState(false);
  const [now,setNow]=useState(()=>Date.now());
  const submission=useRef<{input:NewExpectedWindow;known:Set<string>}|null>(null);
  useEffect(()=>{
    const submitted=submission.current;
    if(!windowOpen||!submitted)return;
    const match=state.owner.windows.find(window=>!window.recorded&&!submitted.known.has(window.id)
      &&(window.label||'')===submitted.input.label
      &&Date.parse(window.start)===Date.parse(submitted.input.start)
      &&Date.parse(window.end)===Date.parse(submitted.input.end)
      &&[...window.cameras].sort().join('\0')===[...submitted.input.cameras].sort().join('\0')
      &&[...window.zones].sort().join('\0')===[...submitted.input.zones].sort().join('\0'));
    if(match){submission.current=null;setWindowOpen(false);setLabel('');setStart('');setEnd('');setCamera('');}
  },[state.owner.windows,windowOpen]);
  const edge=state.mode==='edge';
  const owner=edge&&state.owner.enabled;
  const pending=!!ownerActions?.pending;
  const tokenAllowed=edge&&!!ownerActions?.saveToken&&!pending;
  const createAllowed=owner&&!!ownerActions?.createWindow&&!pending;
  useEffect(()=>{
    if(!ownerActions?.checkinExpiresAt)return;
    setNow(Date.now());
    const timer=setInterval(()=>setNow(Date.now()),1000);
    return()=>clearInterval(timer);
  },[ownerActions?.checkinExpiresAt]);
  const expiry=ownerActions?.checkinExpiresAt?new Date(ownerActions.checkinExpiresAt).getTime():NaN;
  const remaining=Number.isFinite(expiry)?Math.max(0,Math.ceil((expiry-now)/1000)):null;
  function save(event:FormEvent){
    event.preventDefault();
    if(!tokenAllowed||!token.trim())return;
    ownerActions?.saveToken?.(token);
    setToken('');
  }
  function create(event:FormEvent){
    event.preventDefault();
    if(!createAllowed)return;
    const a=new Date(start),b=new Date(end);
    if(!start||!end||!Number.isFinite(a.getTime())||!Number.isFinite(b.getTime())){setError('Choose a valid start and end time.');return;}
    if(b<=a){setError('Window end must be after its start.');return;}
    if(b.getTime()-a.getTime()>12*3600000){setError('An expected window can last at most 12 hours.');return;}
    setError(null);
    const input={label:label.trim(),start:a.toISOString(),end:b.toISOString(),cameras:camera?[camera]:[],zones:[]};
    submission.current={input,known:new Set(state.owner.windows.map(window=>window.id))};
    ownerActions?.createWindow?.(input);
  }
  const failure=error||ownerActions?.error;
  const feedback=<>{failure&&<p className="controls-error" role="alert">{failure}</p>}{pending&&<p className="controls-status" role="status">Saving owner changes…</p>}</>;
  return <div className="controls-stack">
    {notice&&<div className="controls-inline"><LockKeyhole aria-hidden="true"/>{!owner?<p className="controls-status">Owner access is required. Open Settings → Owner access on the home box.</p>:<Chip tone="success">Owner session active</Chip>}</div>}
    {!windowOpen&&feedback}
    {section==='access'&&<section className="st-stack" aria-labelledby={`${id}-access`}>
      <header className="pv-section-head"><h2 id={`${id}-access`}>Owner access</h2></header>
      <ul className="pv-list st-list">
        <li className="pv-row"><span className="pv-bubble" aria-hidden="true">{owner?<ShieldCheck/>:<LockKeyhole/>}</span><div className="pv-row-body"><strong>Owner session</strong><span className="pv-meta">{!edge?'Owner-only on the home box':owner?'Active on this browser':'Not signed in on this browser'}</span></div>{owner?<Chip tone="success">Active</Chip>:<Chip>{edge?'Signed out':'Unavailable'}</Chip>}</li>
        <li className="pv-row st-form-row"><span className="pv-bubble" aria-hidden="true"><KeyRound/></span>
          <form onSubmit={save} className="st-token-form">
            <Field label="Owner token" id={`${id}-token`}><input id={`${id}-token`} className="controls-input" type="password" value={token} onChange={e=>setToken(e.target.value)} disabled={!tokenAllowed} autoComplete="off" spellCheck={false}/></Field>
            <Button type="submit" disabled={!tokenAllowed||!token.trim()}>Save owner token</Button>
          </form></li>
      </ul>
      <p className="pv-footnote"><Info aria-hidden="true"/>The token stays in this tab. It is never put in a URL or shared in messages.</p>
      <Household state={state} onOpenVisit={()=>{}} onOpenClip={()=>{}}/>
    </section>}
    {section==='visitors'&&<VisitorList state={state} owner={owner} pending={pending} remaining={remaining} canCheckIn={owner&&!!ownerActions?.checkIn&&!pending} createAllowed={createAllowed}
      onCheckIn={()=>ownerActions?.checkIn?.()} onNew={()=>{setError(null);submission.current=null;setWindowOpen(true);}}
      onCancel={ownerActions?.cancelWindow&&owner&&!pending?(windowId=>ownerActions.cancelWindow?.(windowId)):undefined}/>}
    <Modal open={windowOpen} title="New expected window" onClose={()=>setWindowOpen(false)} description="Set a delivery or guest window in advance. Maximum duration: 12 hours.">
      <div className="controls-stack">{feedback}<form className="controls-form" onSubmit={create} noValidate>
        <Field label="Window label" id={`${id}-label`}><input id={`${id}-label`} className="controls-input" value={label} onChange={e=>setLabel(e.target.value)} maxLength={60} disabled={!createAllowed}/></Field>
        <div className="controls-form-row">
          <Field label="Window starts" id={`${id}-start`}><input id={`${id}-start`} className="controls-input" type="datetime-local" value={start} onChange={e=>setStart(e.target.value)} disabled={!createAllowed}/></Field>
          <Field label="Window ends" id={`${id}-end`}><input id={`${id}-end`} className="controls-input" type="datetime-local" value={end} onChange={e=>setEnd(e.target.value)} disabled={!createAllowed}/></Field>
        </div>
        <p className="controls-hint">New times use this browser's time zone: {Intl.DateTimeFormat().resolvedOptions().timeZone}. Saved timestamps include the timezone.</p>
        <Field label="Window camera" id={`${id}-camera`}><select id={`${id}-camera`} className="controls-select" value={camera} onChange={e=>setCamera(e.target.value)} disabled={!createAllowed}><option value="">All configured cameras</option>{state.cameras.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></Field>
        <Button type="submit" disabled={!createAllowed}>Create expected window</Button>
      </form></div>
    </Modal>
  </div>;
}

const MUTABLE_WINDOW=['scheduled','active'];
function WindowRow({window,state,onCancel}:{window:ExpectedWindow;state:UIState;onCancel?:(id:string)=>void}){
  const scope=[window.cameras.map(cid=>state.cameras.find(c=>c.id===cid)?.name||words(cid)).join(', '),window.zones.map(words).join(', ')].filter(Boolean).join(' · ')||'All cameras';
  const mutable=!window.recorded&&MUTABLE_WINDOW.includes(window.state);
  return <li className="pv-subrow"><article aria-label={window.label||'Expected window'}>
    <div className="pv-row-body"><strong>{words(window.label||'Expected window')}</strong><span className="pv-meta">{formatRecordedTime(window.start)} – {formatRecordedTime(window.end)}</span><span className="pv-meta">{scope}{window.recorded?' · Recorded example':''}</span></div>
    <StatusChip value={window.state}/>
    {mutable&&onCancel&&<button type="button" className="pv-icon-btn" aria-label="Cancel window" onClick={()=>onCancel(window.id)}><X aria-hidden="true"/></button>}
  </article></li>;
}
function VisitorList({state,owner,pending,remaining,canCheckIn,createAllowed,onCheckIn,onNew,onCancel}:{state:UIState;owner:boolean;pending:boolean;remaining:number|null;canCheckIn:boolean;createAllowed:boolean;onCheckIn:()=>void;onNew:()=>void;onCancel?:(id:string)=>void}){
  const upcoming=state.owner.windows.filter(w=>MUTABLE_WINDOW.includes(w.state));
  const past=state.owner.windows.filter(w=>!MUTABLE_WINDOW.includes(w.state));
  const checking=remaining!==null&&remaining>0;
  return <ul className="pv-list">
    <li className="pv-row"><span className="pv-bubble" aria-hidden="true"><DoorOpen/></span>
      <div className="pv-row-body"><strong>Check in</strong><span className="pv-meta" role={remaining!==null?'status':undefined}>{remaining===null?`Tap as you step outside. You count as household for ${state.owner.checkin_duration_s} s.`:checking?`${remaining} s remaining`:'Check-in window ended'}</span></div>
      <Button size="sm" disabled={!canCheckIn||checking} onClick={onCheckIn}>I'm outside</Button></li>
    <li className="pv-row pv-row-group"><div className="pv-row-top"><span className="pv-bubble" aria-hidden="true"><CalendarClock/></span>
      <div className="pv-row-body"><strong>Expected visitors</strong><span className="pv-meta">Delivery or guest coming? Their visit is not flagged.</span></div>
      <button type="button" className="pv-icon-btn pv-icon-btn-accent" aria-label="New expected window" disabled={!createAllowed} onClick={onNew}><Plus aria-hidden="true"/></button></div>
      {upcoming.length>0?<ul className="pv-sublist">{upcoming.map(w=><WindowRow key={w.id} window={w} state={state} onCancel={onCancel}/>)}</ul>:<p className="pv-hint pv-indent">{owner?'Nothing scheduled.':'Nothing scheduled. Owners can add a window.'}</p>}
      {past.length>0&&<details className="pv-past pv-indent"><summary>Past windows ({past.length})</summary><ul className="pv-sublist">{past.map(w=><WindowRow key={w.id} window={w} state={state}/>)}</ul></details>}
      {pending&&<p className="pv-hint pv-indent" role="status">Saving…</p>}
    </li>
  </ul>;
}
