import {useId,useState,type MouseEvent} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {Button,Card,EmptyState,Modal} from '../components/ui';
import {Field} from '../pages/settings/controls';
import {api} from './api';
import {readableError} from './model';

interface Frame {camera_id:string;name:string;url:string;frame_ts:number;width:number;height:number}
interface Frames {frames:Frame[];reason:string|null;live?:{available:boolean;reason:string|null;estimate_usd:number}}
interface MaskResult {live:boolean;notice:string|null;hint?:string;result:{object:{id:string;label:string};outline:number[][]}|null}
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
  const live=frames.data?.live;
  const mask=request.data?.live?request.data.result:null;
  return <Card title="Protect an object"><p className="controls-note">Select a point on an exported, reviewed still. Pixel fields provide the same selection by keyboard.</p>
    {!enabled?<><p className="controls-status">Owner-only on the home box</p><Button variant="outline" disabled>Select an object</Button></>:frames.isPending?<p role="status">Loading reviewed stills…</p>:frames.isError?<p role="alert">{readableError(frames.error)}</p>:<><Button variant="outline" disabled={!frame} onClick={()=>setOpen(true)}>Select an object</Button>{!frame&&<p className="controls-hint">{frames.data?.reason||'No reviewed exported still is available.'}</p>}</>}
    <Modal open={open} title="Select an object" onClose={()=>{setOpen(false);setConfirm(false);}} description="The image is an exported still, never a live camera stream.">
      {frame&&<div className="controls-stack"><Field label="Camera still" id={`${id}-camera`}><select disabled={request.isPending} id={`${id}-camera`} className="controls-select" value={frame.camera_id} onChange={event=>{setSelected(event.target.value);setLoaded(false);setImageError(false);setX('');setY('');request.reset();}}>{frames.data?.frames.map(f=><option key={f.camera_id} value={f.camera_id}>{f.name}</option>)}</select></Field>
        <div className="protection-frame"><img key={frame.url} src={frame.url} alt={`${frame.name} exported still`} onLoad={()=>setLoaded(true)} onError={()=>{setLoaded(false);setImageError(true);}} onClick={selectPoint}/>{mask&&mask.outline.length>0&&<svg viewBox={`0 0 ${frame.width} ${frame.height}`} aria-label="Point model mask"><polygon points={mask.outline.map(p=>p.join(',')).join(' ')}/></svg>}</div>
        {imageError&&<p role="alert">The exported still could not be loaded. Point selection is unavailable.</p>}
        <div className="controls-form-row"><Field label="Pixel X" id={`${id}-x`}><input disabled={request.isPending} id={`${id}-x`} type="number" className="controls-input" min={0} max={frame.width-1} value={x} onChange={event=>{setX(event.target.value);request.reset();}}/></Field><Field label="Pixel Y" id={`${id}-y`}><input disabled={request.isPending} id={`${id}-y`} type="number" className="controls-input" min={0} max={frame.height-1} value={y} onChange={event=>{setY(event.target.value);request.reset();}}/></Field></div>
        <Field label="Object label" id={`${id}-label`}><input disabled={request.isPending} id={`${id}-label`} className="controls-input" maxLength={60} value={label} onChange={event=>setLabel(event.target.value)}/></Field>
        <div className="controls-inline"><Button variant="outline" disabled={!valid||request.isPending} onClick={()=>request.mutate(false)}>Review recorded result</Button><Button className="protection-request" disabled={!valid||!live?.available} aria-disabled={request.isPending} onClick={()=>{if(!request.isPending)setConfirm(true);}}>Request point model</Button></div>
        {!live?.available&&<p className="controls-hint">{live?.reason||'A new model request is unavailable in this session.'}</p>}
        {request.isPending&&<p role="status">Preparing point result…</p>}{request.isError&&<p role="alert">{readableError(request.error)}</p>}
        {request.data&&(request.data.result?<div className="controls-status"><strong>{request.data.result.object.label}</strong><p>{request.data.live?'Point result for the selected still. Added to this server session.':'Recorded example result; it is not drawn over this frame.'}</p><p>{request.data.notice}</p></div>:<EmptyState title="No recorded mask at this point" description={request.data.notice||request.data.hint||'No result is available for this point.'}/>)}
      </div>}
    </Modal>
    <Modal open={confirm} title="Approve point model request" onClose={()=>setConfirm(false)} description="This action may use Meta API credits. The home box checks its budget before sending."><p>Run SAM 3.1 on this exported still at the selected point. Estimated cost: ${live?.estimate_usd.toFixed(4)??'unavailable'}.</p><div className="controls-inline"><Button variant="outline" onClick={()=>setConfirm(false)}>Cancel</Button><Button disabled={!enabled||!valid||!live?.available||request.isPending} onClick={()=>{setConfirm(false);request.mutate(true);}}>Approve and run</Button></div></Modal>
  </Card>;
}
