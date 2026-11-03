import type {ChatMessage} from '../contracts';
export interface OverlayFrame {t:number;box:number[];outline:number[][]}
const clockFormatter=new Intl.DateTimeFormat('en-US',{timeZone:'UTC',hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true});
const dateFormatter=new Intl.DateTimeFormat('en-US',{timeZone:'UTC',month:'short',day:'numeric',year:'numeric'});
/** Match server citation clocks, preserving the offset declared in session_start. */
export function recordedClock(start:string,time:number){
  const match=typeof start==='string'?start.match(/(Z|([+-])(\d{2}):(\d{2}))$/):null;
  const base=Date.parse(start);
  if(!match||!Number.isFinite(base)||!Number.isFinite(time))return {text:Number.isFinite(time)?`${time.toFixed(1)} s`:'Time unavailable',date:'',zone:'Timezone unavailable'};
  const offset=match[1]==='Z'?0:(match[2]==='-'?-1:1)*(Number(match[3])*60+Number(match[4]));
  const stamp=new Date(base+time*1000+offset*60_000);
  return {text:clockFormatter.format(stamp).replace(/[\u202f\u00a0]/g,' '),date:dateFormatter.format(stamp),zone:match[1]==='Z'?'UTC':`UTC${match[1]}`};
}
export function cameraTime(absolute:number,start:number,duration:number) {return Math.max(0,Math.min(absolute-start,Number.isFinite(duration)?duration:Infinity));}
/** Display an observed sample only; never invent motion between sparse detections. */
export function frameAt(frames:OverlayFrame[],time:number):OverlayFrame|null {
  return frames.reduce<OverlayFrame|null>((best,frame)=>Math.abs(frame.t-time)<=.25&&(!best||Math.abs(frame.t-time)<Math.abs(best.t-time))?frame:best,null);
}
/** People-to-people messaging is local-only. There are no fabricated incoming users. */
export function localThreads(raw:string|null):Record<string,ChatMessage[]> {
  try {
    const value=JSON.parse(raw??'{}');const messages=value.household;
    if(!Array.isArray(messages)||!messages.every(m=>typeof m.id==='string'&&m.author==='you'&&typeof m.text==='string'&&Array.isArray(m.citations)&&(m.clip_id===null||typeof m.clip_id==='string')))return {};
    return {household:messages};
  } catch{return {};}
}
export function readableError(error:unknown) {return error instanceof TypeError?'The home box could not be reached. Check the connection and try again.':error instanceof Error?error.message:'The request could not be completed.';}
