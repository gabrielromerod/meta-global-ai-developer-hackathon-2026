import {useEffect,useId,useState,type FormEvent} from 'react';
import {Camera as CameraIcon,Clock3,House,LockKeyhole,Wifi} from 'lucide-react';
import type {Camera,PageProps} from '../../contracts';
import {Button,Card,Chip,EmptyState,Modal,Tabs} from '../../components/ui';
import {Field,formatRecordedTime,PageHeading,StatusChip} from './controls';
import './controls.css';

const tabs=[{id:'cameras',label:'Cameras'},{id:'privacy',label:'Privacy'},{id:'household',label:'Household'},{id:'owner',label:'Owner controls'}];
export function SettingsPage(props:PageProps){
  const [tab,setTab]=useState('cameras');
  return <div className="controls-page settings-page"><PageHeading title="Home setup" description="Cameras, privacy and owner access." action={<Chip>{props.state.cameras.length} configured cameras</Chip>}/>
    <Tabs items={tabs} value={tab} onChange={setTab} label="Settings sections" className="controls-tabs"><div className="controls-scroll" tabIndex={0} aria-label={`${tabs.find(t=>t.id===tab)?.label} settings`}>
      {tab==='cameras'?<Cameras cameras={props.state.cameras}/>:tab==='privacy'?<Privacy cameras={props.state.cameras}/>:tab==='household'?<Household {...props}/>:props.ownerSlot??<OwnerControls {...props}/>}
    </div></Tabs>
  </div>;
}
function Cameras({cameras}:{cameras:Camera[]}){
  return cameras.length?<div className="controls-grid">{cameras.map(camera=><article className="v-card" key={camera.id} aria-label={`${camera.name} camera`}><h3 className="controls-card-title"><CameraIcon aria-hidden="true"/>{camera.name}</h3><p className="controls-note">{camera.model||'Model not confirmed'}</p><div className="controls-inline"><StatusChip value={camera.status}/>{camera.source_label.toLowerCase()!==camera.status.replaceAll("_"," ").toLowerCase()&&<Chip>{camera.source_label}</Chip>}</div><dl className="controls-definition"><dt>Power</dt><dd>{camera.power_profile==='battery_wifi'?'Battery':camera.power_profile==='import'?'Battery / imported clips':'AC power'}</dd><dt><Wifi aria-hidden="true" className="controls-small-icon"/> Wi-Fi</dt><dd>{camera.wifi_signal_dbm===null?'Not measured':`${camera.wifi_signal_dbm} dBm`}</dd><dt><Clock3 aria-hidden="true" className="controls-small-icon"/> Clock offset</dt><dd>{camera.clock_offset_s===null?'Not measured':`${camera.clock_offset_s.toFixed(2)} s`}</dd><dt>Home Hub</dt><dd>{camera.hub_present===null?'Not confirmed':camera.hub_present?'Present':'Not present'}</dd></dl>{camera.clock_offset_s!==null&&Math.abs(camera.clock_offset_s)>2&&<p className="controls-error">Clock sync required before linking cameras.</p>}{['battery_wifi','import'].includes(camera.power_profile)&&<p className="controls-hint">Battery cameras never hold a stream open.</p>}</article>)}</div>:<EmptyState title="No cameras configured" description="Cameras appear after the home configuration is loaded."/>;
}
function Privacy({cameras}:{cameras:Camera[]}){
  return <div className="controls-grid"><Card title="Review every camera"><p className="controls-note">Ingest stays blocked until the owner approves a real still and its exact privacy masks.</p><ul className="controls-list">{cameras.map(camera=><li className="controls-window" key={camera.id}><div className="controls-inline"><strong>{camera.name}</strong><Chip tone="warning">{camera.status==='privacy_blocked'?'Review required':'Review not confirmed'}</Chip></div></li>)}</ul></Card><div className="controls-stack"><Card title="Front panorama masks"><ul className="controls-policy-list"><li>Sky and mountain ridgeline</li><li>Opposite houses and cars</li><li>Neighbouring driveways and cars</li><li>Curb numbers and distant street furniture</li><li>On-screen timestamp and camera watermark</li></ul><p className="controls-note">The near street, sidewalk and owned property remain visible.</p></Card><Card title="Silent, metadata-free evidence"><p className="controls-note">Camera audio is never used. Ingest rejects any audio stream, and exported assets lose EXIF and GPS metadata.</p><p className="controls-hint">Mask coverage requires owner review on the home box. Templates are not field acceptance.</p></Card></div></div>;
}
function Household({state}:PageProps){
  return <div className="controls-grid"><Card title="Household"><div className="controls-inline"><span className="controls-avatar">{state.household.avatar_url?<img src={state.household.avatar_url} alt=""/>:<House aria-hidden="true"/>}</span><strong>{state.household.name}</strong></div><p className="controls-note">Household messages stay local to this browser. No people-to-people messaging server is connected.</p></Card><Card title="Roles follow observed routes"><p className="controls-note">Vigil does not identify people. Household and visitor roles come from where a subject was observed to arrive, an owner check-in or an expected window.</p><p className="controls-hint">An unknown origin is treated as non-household. A later label does not change a recorded verdict.</p></Card></div>;
}
function OwnerControls({state,ownerActions}:PageProps){
  const id=useId();
  const [token,setToken]=useState('');
  const [label,setLabel]=useState('');
  const [start,setStart]=useState('');
  const [end,setEnd]=useState('');
  const [camera,setCamera]=useState('');
  const [error,setError]=useState<string|null>(null);
  const [windowOpen,setWindowOpen]=useState(false);
  const [now,setNow]=useState(()=>Date.now());
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
    ownerActions?.createWindow?.({label:label.trim(),start:a.toISOString(),end:b.toISOString(),cameras:camera?[camera]:[],zones:[]});
  }
  const failure=error||ownerActions?.error;
  const feedback=<>{failure&&<p className="controls-error" role="alert">{failure}</p>}{pending&&<p className="controls-status" role="status">Saving owner changes…</p>}</>;
  return <div className="controls-stack">
    <div className="controls-inline"><LockKeyhole aria-hidden="true"/>{!owner?<p className="controls-status">Owner-only on the home box</p>:<Chip tone="success">Owner session active</Chip>}</div>
    {!windowOpen&&feedback}
    <div className="controls-grid">
      <div className="controls-stack">
        <Card title="Owner access"><p className="controls-note">The token stays in this tab. It is never put in a URL or shared in messages.</p>
          <form onSubmit={save} className="controls-form">
            <Field label="Owner token" id={`${id}-token`}><input id={`${id}-token`} className="controls-input" type="password" value={token} onChange={e=>setToken(e.target.value)} disabled={!tokenAllowed} autoComplete="off" spellCheck={false}/></Field>
            <Button type="submit" disabled={!tokenAllowed||!token.trim()}>Save owner token</Button>
          </form>
        </Card>
        <Card title="Check in"><p className="controls-note">Single-use and never retroactive. A check-in can bind one observed subject chain within {state.owner.checkin_duration_s} seconds.</p>
          <Button onClick={()=>ownerActions?.checkIn?.()} disabled={!owner||!ownerActions?.checkIn||pending}>I'm outside</Button>
          {remaining!==null&&<p className="controls-status" role="status">{remaining>0?`${remaining} s remaining`:'Check-in window ended'}</p>}
        </Card>
      </div>
      <Card title="Expected windows" actions={<Button variant="outline" disabled={!createAllowed} onClick={()=>{setError(null);setWindowOpen(true);}}>New expected window</Button>}>
        <p className="controls-note">Recorded examples stay unchanged. Owners can cancel their active or scheduled windows.</p>
        {state.owner.windows.length?<div className="controls-list">{state.owner.windows.map(window=><article className="controls-window" key={window.id} aria-label={window.label||'Expected window'}>
          <header><h3>{window.label||'Expected window'}</h3><div className="controls-inline"><StatusChip value={window.state}/>{window.recorded&&<Chip>Recorded example</Chip>}</div></header>
          <p>{formatRecordedTime(window.start)} – {formatRecordedTime(window.end)}</p>
          <p>{window.cameras.length?window.cameras.map(cid=>state.cameras.find(c=>c.id===cid)?.name||cid).join(', '):'All configured cameras'}</p>
          <Button variant="outline" onClick={()=>ownerActions?.cancelWindow?.(window.id)} disabled={!owner||!ownerActions?.cancelWindow||pending||!!window.recorded||!['scheduled','active'].includes(window.state)}>Cancel window</Button>
        </article>)}</div>:<EmptyState title="No expected windows" description="New windows appear after the owner saves them."/>}
      </Card>
    </div>
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
