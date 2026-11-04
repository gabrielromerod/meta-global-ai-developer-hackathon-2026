import {useId,useState,type MouseEvent,type ReactNode} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {Plus} from 'lucide-react';
import {Button,EmptyState,Modal} from '../components/ui';
import {Field} from '../pages/settings/controls';
import {api} from './api';
import {readableError} from './model';

interface Frame {camera_id:string;name:string;url:string;frame_ts:number;width:number;height:number}
interface Frames {frames:Frame[];reason:string|null;live?:{available:boolean;reason:string|null;estimate_usd:number}}
interface Telemetry {model?:string|null;latency_ms?:number|null;cost_usd?:number|null;cached?:boolean;funding?:string|null}
interface MaskResult {live:boolean;notice:string|null;hint?:string;telemetry?:Telemetry;result:{object:{id:string;label:string;footprint?:unknown};outline:number[][]}|null}

/** What the call really took, from the server's ledger telemetry. Nothing is shown that was not recorded. */
function callFacts(t:Telemetry|undefined,live:boolean){
  if(!t)return null;
  const parts:string[]=[t.model==='sam-3.1'||!t.model?'SAM 3.1':t.model];
  if(typeof t.latency_ms==='number'&&t.latency_ms>0)parts.push(`${(t.latency_ms/1000).toFixed(1)} s`);
  if(live&&typeof t.cost_usd==='number')parts.push(`$${t.cost_usd.toFixed(4)}`);
  if(!live)parts.push('recorded earlier, no new spend');
  else if(t.funding)parts.push(t.funding==='credit'?'paid from credits':'paid');
  return parts.join(' · ');
}

function Step({n,title,done,children}:{n:number;title:string;done?:boolean;children:ReactNode}){
  return <section className="pv-step" data-done={done||undefined} aria-label={`Step ${n}: ${title}`}><header><span className="pv-step-n" aria-hidden="true">{n}</span><h3>{title}</h3></header>{children}</section>;
}

export function ProtectionPanel({enabled}:{enabled:boolean}){
  const id=useId(),queries=useQueryClient();
  const frames=useQuery({queryKey:['protection-frames'],queryFn:()=>api<Frames>('/api/ui/protection-frames'),enabled});
  const [open,setOpen]=useState(false),[selected,setSelected]=useState(''),[x,setX]=useState(''),[y,setY]=useState(''),[label,setLabel]=useState('');
  const [loaded,setLoaded]=useState(false),[confirm,setConfirm]=useState(false),[imageError,setImageError]=useState(false);
  const frame=frames.data?.frames.find(f=>f.camera_id===selected)??frames.data?.frames[0];
  const point={x:Number(x),y:Number(y)};
  const valid=Boolean(frame&&loaded&&x!==''&&y!==''&&Number.isFinite(point.x)&&Number.isFinite(point.y)&&point.x>=0&&point.y>=0&&point.x<frame.width&&point.y<frame.height);
  const request=useMutation({mutationFn:(live:boolean)=>api<MaskResult>('/api/protect',{camera_id:frame!.camera_id,frame_ts:frame!.frame_ts,point,frame_width:frame!.width,frame_height:frame!.height,label:label.trim()||undefined,live}),onSuccess:result=>{if(result.live)void queries.invalidateQueries({queryKey:['ui-state']});}});
  function selectPoint(event:MouseEvent<HTMLImageElement>){if(!loaded||!frame||request.isPending)return;const box=event.currentTarget.getBoundingClientRect();setX(String(Math.min(frame.width-1,Math.max(0,Math.round((event.clientX-box.left)*frame.width/box.width)))));setY(String(Math.min(frame.height-1,Math.max(0,Math.round((event.clientY-box.top)*frame.height/box.height)))));request.reset();}
  function pickCamera(cameraId:string){setSelected(cameraId);setLoaded(false);setImageError(false);setX('');setY('');request.reset();}
  const live=frames.data?.live;
  const mask=request.data?.live?request.data.result:null;
  const unavailable=enabled&&!frames.isPending&&!frames.isError&&!frame;
  return <div className="pv-protect">
    <Button disabled={!enabled||!frame} onClick={()=>setOpen(true)}><Plus aria-hidden="true"/>Add object</Button>
    {enabled&&frames.isPending&&<p className="pv-hint" role="status">Loading camera stills…</p>}
    {enabled&&frames.isError&&<p className="pv-hint" role="alert">{readableError(frames.error)}</p>}
    {unavailable&&<p className="pv-hint">{frames.data?.reason||'No reviewed camera still is available yet.'}</p>}
    <Modal open={open} title="Protect an object" onClose={()=>{setOpen(false);setConfirm(false);}} description="Uses a saved camera still, never a live stream.">
      {frame&&<div className="pv-flow">
        <Step n={1} title="Choose a camera" done>
          <div className="pv-pills" role="radiogroup" aria-label="Camera still">{frames.data?.frames.map(f=><button key={f.camera_id} type="button" role="radio" aria-checked={f.camera_id===frame.camera_id} className="pv-pill" disabled={request.isPending} onClick={()=>pickCamera(f.camera_id)}>{f.name}</button>)}</div>
        </Step>
        <Step n={2} title="Tap the object" done={x!==''&&y!==''}>
          <div className="protection-frame"><img key={frame.url} src={frame.url} alt={`${frame.name} exported still`} onLoad={()=>setLoaded(true)} onError={()=>{setLoaded(false);setImageError(true);}} onClick={selectPoint}/><svg viewBox={`0 0 ${frame.width} ${frame.height}`} aria-hidden={!mask} aria-label={mask?'Point model mask':undefined}>{mask&&mask.outline.length>0&&<polygon points={mask.outline.map(p=>p.join(',')).join(' ')}/>}{x!==''&&y!==''&&<circle className="pv-marker" cx={point.x} cy={point.y} r={Math.max(frame.width,frame.height)/80}/>}</svg></div>
          {imageError&&<p role="alert" className="controls-error">This still could not be loaded. Choose another camera.</p>}
          <details className="pv-coords"><summary>Enter coordinates instead</summary><div className="controls-form-row"><Field label="Pixel X" id={`${id}-x`}><input disabled={request.isPending} id={`${id}-x`} type="number" className="controls-input" min={0} max={frame.width-1} value={x} onChange={event=>{setX(event.target.value);request.reset();}}/></Field><Field label="Pixel Y" id={`${id}-y`}><input disabled={request.isPending} id={`${id}-y`} type="number" className="controls-input" min={0} max={frame.height-1} value={y} onChange={event=>{setY(event.target.value);request.reset();}}/></Field></div></details>
        </Step>
        <Step n={3} title="Name it and find it">
          <Field label="Object label" id={`${id}-label`}><input disabled={request.isPending} id={`${id}-label`} className="controls-input" placeholder="For example: Side gate" maxLength={60} value={label} onChange={event=>setLabel(event.target.value)}/></Field>
          <div className="pv-actions"><Button variant="outline" disabled={!valid||request.isPending} onClick={()=>request.mutate(false)}>Check recorded result</Button><Button className="protection-request" disabled={!valid||!live?.available} aria-disabled={request.isPending} onClick={()=>{if(!request.isPending)setConfirm(true);}}>Detect with SAM 3.1</Button></div>
          {!valid&&<p className="pv-hint">Tap the object in the image first.</p>}
          {valid&&!live?.available&&<p className="pv-hint">{live?.reason||'New detections are unavailable in this session; recorded results still work.'}</p>}
        </Step>
        {request.isPending&&<p role="status" className="pv-hint">Finding the object…</p>}{request.isError&&<p role="alert" className="controls-error">{readableError(request.error)}</p>}
        {request.data&&(request.data.result?<div className="pv-result" role="status"><strong>{request.data.result.object.label}</strong><p>{request.data.live?'Protected. Added to this server session; you can now use it in rules.':'Recorded example result; it is not drawn over this still.'}</p>
          {callFacts(request.data.telemetry,request.data.live)&&<p className="pv-meta">{callFacts(request.data.telemetry,request.data.live)}</p>}
          {request.data.live&&<p className="pv-meta">{Array.isArray(request.data.result.object.footprint)&&request.data.result.object.footprint.length>=3?'Placed on the house model.':'Not placed on the house model: this camera\'s position has not been measured.'}</p>}
          {request.data.notice&&<p>{request.data.notice}</p>}</div>:<EmptyState title="Nothing recorded at this point" description={request.data.notice||request.data.hint||'Try tapping closer to the object.'}/>)}
      </div>}
    </Modal>
    <Modal open={confirm} title="Confirm detection" onClose={()=>setConfirm(false)} description="This may use Meta API credits. The home box checks its budget before sending."><p>Run SAM 3.1 at the point you tapped. Estimated cost: <strong>${live?.estimate_usd.toFixed(4)??'unavailable'}</strong>.</p><div className="pv-actions"><Button variant="outline" onClick={()=>setConfirm(false)}>Cancel</Button><Button disabled={!enabled||!valid||!live?.available||request.isPending} onClick={()=>{setConfirm(false);request.mutate(true);}}>Approve and run</Button></div></Modal>
  </div>;
}
