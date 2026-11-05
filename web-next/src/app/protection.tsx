import {useEffect,useId,useState,type CSSProperties,type MouseEvent,type ReactNode} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {LockKeyhole,MousePointerClick,Plus} from 'lucide-react';
import {Button,EmptyState,Modal} from '../components/ui';
import {Field} from '../pages/settings/controls';
import {api} from './api';
import {readableError} from './model';
import './protection.css';

interface Frame {camera_id:string;name:string;url:string;frame_ts:number;width:number;height:number;still_id?:string;capture_id?:string;source?:'capture'|'bundle';visible?:number[]}

/** `#/rules?still=<capture_id>&t=<s>` preselects a recorded clip's masked frame (the clip view links here). */
function readStillParam():{still:string|null;t:number|null}{
  const query=(window.location.hash.split('?')[1]??'')||window.location.search.slice(1);
  const params=new URLSearchParams(query);const still=params.get('still');const t=Number(params.get('t'));
  return {still:still&&/^[a-z0-9_-]{1,128}$/.test(still)?still:null,t:params.get('t')!==null&&Number.isFinite(t)?t:null};
}
function useStillParam(){
  const [value,setValue]=useState(readStillParam);
  useEffect(()=>{const update=()=>setValue(readStillParam());window.addEventListener('hashchange',update);window.addEventListener('popstate',update);return()=>{window.removeEventListener('hashchange',update);window.removeEventListener('popstate',update);};},[]);
  return value;
}
const frameKey=(f:Frame)=>f.still_id??f.camera_id;

/** A masked still cropped to the area the privacy mask leaves visible, with its overlay in full-frame pixels. */
export function CroppedStill({frame,alt,onLoad,onError,onClick,children,badge=true}:{frame:Frame;alt:string;onLoad?:()=>void;onError?:()=>void;onClick?:(event:MouseEvent<HTMLImageElement>)=>void;children?:ReactNode;badge?:boolean}){
  const [x0,y0,x1,y1]=frame.visible&&frame.visible.length===4&&frame.visible[2]>frame.visible[0]&&frame.visible[3]>frame.visible[1]?frame.visible:[0,0,1,1];
  const w=x1-x0,h=y1-y0,cropped=w<.98||h<.98;
  const layer:CSSProperties={position:'absolute',left:`${-x0/w*100}%`,top:`${-y0/h*100}%`,width:`${100/w}%`,height:`${100/h}%`};
  return <div className="pv-still" data-cropped={cropped||undefined} style={{aspectRatio:`${w*frame.width} / ${h*frame.height}`}}>
    <img key={frame.url} src={frame.url} alt={alt} style={layer} onLoad={onLoad} onError={onError} onClick={onClick} draggable={false}/>
    <svg viewBox={`0 0 ${frame.width} ${frame.height}`} style={layer} preserveAspectRatio="none" aria-hidden={!children} className="pv-still-overlay">{children}</svg>
    {badge&&cropped&&<span className="pv-still-badge"><LockKeyhole aria-hidden="true"/>Street masked · cropped to property</span>}
  </div>;
}
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
  const param=useStillParam();
  const frames=useQuery({queryKey:['protection-frames',param.still,param.t],queryFn:()=>api<Frames>('/api/ui/protection-frames'+(param.still?`?still=${encodeURIComponent(param.still)}${param.t!==null?`&t=${param.t}`:''}`:'')),enabled});
  const [open,setOpen]=useState(false),[selected,setSelected]=useState(''),[x,setX]=useState(''),[y,setY]=useState(''),[label,setLabel]=useState('');
  const [loaded,setLoaded]=useState(false),[confirm,setConfirm]=useState(false),[imageError,setImageError]=useState(false);
  const frame=frames.data?.frames.find(f=>frameKey(f)===selected)??frames.data?.frames[0];
  const capture=frame?.source==='capture';
  const point={x:Number(x),y:Number(y)};
  const valid=Boolean(frame&&loaded&&x!==''&&y!==''&&Number.isFinite(point.x)&&Number.isFinite(point.y)&&point.x>=0&&point.y>=0&&point.x<frame.width&&point.y<frame.height);
  const request=useMutation({mutationFn:(live:boolean)=>api<MaskResult>('/api/protect',{camera_id:frame!.camera_id,frame_ts:frame!.frame_ts,...(frame!.still_id?{still_id:frame!.still_id}:{}),point,frame_width:frame!.width,frame_height:frame!.height,label:label.trim()||undefined,live}),onSuccess:result=>{if(result.live)void queries.invalidateQueries({queryKey:['ui-state']});}});
  function selectPoint(event:MouseEvent<HTMLImageElement>,force=false){if((!loaded&&!force)||!frame||request.isPending)return;const box=event.currentTarget.getBoundingClientRect();setX(String(Math.min(frame.width-1,Math.max(0,Math.round((event.clientX-box.left)*frame.width/box.width)))));setY(String(Math.min(frame.height-1,Math.max(0,Math.round((event.clientY-box.top)*frame.height/box.height)))));request.reset();}
  function pickCamera(key:string){setSelected(key);setLoaded(false);setImageError(false);setX('');setY('');request.reset();}
  useEffect(()=>{if(param.still&&frames.data?.frames.some(f=>f.capture_id===param.still))setSelected(frames.data.frames.find(f=>f.capture_id===param.still)!.still_id!);},[param.still,frames.data]);
  const live=frames.data?.live;
  const mask=request.data?.live?request.data.result:null;
  const unavailable=enabled&&!frames.isPending&&!frames.isError&&!frame;
  const marker=(f:Frame)=><>{mask&&mask.outline.length>0&&<polygon points={mask.outline.map(p=>p.join(',')).join(' ')}/>}{x!==''&&y!==''&&<circle className="pv-marker" cx={point.x} cy={point.y} r={Math.max(f.width,f.height)/80}/>}</>;
  const altFor=(f:Frame)=>f.source==='capture'?`${f.name} masked still from a recorded clip`:`${f.name} exported still`;
  return <div className="pv-protect">
    <Button disabled={!enabled||!frame} onClick={()=>setOpen(true)}><Plus aria-hidden="true"/>Add object</Button>
    {enabled&&frame&&!open&&<figure className="pv-inline">
      {(frames.data?.frames.length??0)>1&&<div className="pv-pills" role="radiogroup" aria-label="Camera still for tapping">{frames.data?.frames.map(f=><button key={frameKey(f)} type="button" role="radio" aria-checked={frameKey(f)===frameKey(frame)} className="pv-pill" onClick={()=>pickCamera(frameKey(f))}>{f.name}</button>)}</div>}
      <CroppedStill frame={frame} alt={`${frame.name}: tap an object to protect it`} onLoad={()=>setLoaded(true)} onError={()=>setImageError(true)} onClick={event=>{selectPoint(event,true);setOpen(true);}}>{marker(frame)}</CroppedStill>
      <figcaption className="pv-hint"><MousePointerClick aria-hidden="true"/>Tap the gate, car or package spot. SAM 3.1 runs only after you approve the cost.{capture&&frame.capture_id?' Frame from a recorded clip.':''}</figcaption>
    </figure>}
    {enabled&&frames.isPending&&<p className="pv-hint" role="status">Loading camera stills…</p>}
    {enabled&&frames.isError&&<p className="pv-hint" role="alert">{readableError(frames.error)}</p>}
    {unavailable&&<p className="pv-hint">{frames.data?.reason||'No reviewed camera still is available yet.'}</p>}
    <Modal open={open} title="Protect an object" onClose={()=>{setOpen(false);setConfirm(false);}} description={capture?'Uses a masked frame from a recorded clip, never a live stream.':'Uses a saved camera still, never a live stream.'}>
      {frame&&<div className="pv-flow">
        <Step n={1} title="Choose a camera" done>
          <div className="pv-pills" role="radiogroup" aria-label="Camera still">{frames.data?.frames.map(f=><button key={frameKey(f)} type="button" role="radio" aria-checked={frameKey(f)===frameKey(frame)} className="pv-pill" disabled={request.isPending} onClick={()=>pickCamera(frameKey(f))}>{f.name}{f.source==='capture'?' · recorded clip':''}</button>)}</div>
        </Step>
        <Step n={2} title="Tap the object" done={x!==''&&y!==''}>
          <div className="protection-frame">{capture?<CroppedStill frame={frame} alt={altFor(frame)} onLoad={()=>setLoaded(true)} onError={()=>{setLoaded(false);setImageError(true);}} onClick={event=>selectPoint(event)}>{mask&&<title>Point model mask</title>}{marker(frame)}</CroppedStill>
            :<><img key={frame.url} src={frame.url} alt={altFor(frame)} onLoad={()=>setLoaded(true)} onError={()=>{setLoaded(false);setImageError(true);}} onClick={event=>selectPoint(event)}/><svg viewBox={`0 0 ${frame.width} ${frame.height}`} aria-hidden={!mask} aria-label={mask?'Point model mask':undefined}>{marker(frame)}</svg></>}</div>
          {imageError&&<p role="alert" className="controls-error">This still could not be loaded. Choose another camera.</p>}
          <details className="pv-coords"><summary>Enter coordinates instead</summary><div className="controls-form-row"><Field label="Pixel X" id={`${id}-x`}><input disabled={request.isPending} id={`${id}-x`} type="number" className="controls-input" min={0} max={frame.width-1} value={x} onChange={event=>{setX(event.target.value);request.reset();}}/></Field><Field label="Pixel Y" id={`${id}-y`}><input disabled={request.isPending} id={`${id}-y`} type="number" className="controls-input" min={0} max={frame.height-1} value={y} onChange={event=>{setY(event.target.value);request.reset();}}/></Field></div></details>
        </Step>
        <Step n={3} title="Name it and find it">
          <Field label="Object label" id={`${id}-label`}><input disabled={request.isPending} id={`${id}-label`} className="controls-input" placeholder="For example: Side gate" maxLength={60} value={label} onChange={event=>setLabel(event.target.value)}/></Field>
          <div className="pv-actions">{!capture&&<Button variant="outline" disabled={!valid||request.isPending} onClick={()=>request.mutate(false)}>Check recorded result</Button>}<Button className="protection-request" disabled={!valid||!live?.available} aria-disabled={request.isPending} onClick={()=>{if(!request.isPending)setConfirm(true);}}>Detect with SAM 3.1</Button></div>
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
