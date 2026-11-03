import type {ChatMessage} from '../contracts';
export interface OverlayFrame {t:number;box:number[];outline:number[][]}
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
