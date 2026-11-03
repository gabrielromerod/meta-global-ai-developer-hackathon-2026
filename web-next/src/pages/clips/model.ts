import type {Clip, UIState} from '../../contracts';
export interface EvidenceFilters {q:string;camera:string;verdict:string;kind:string;start:string;end:string}
export const EMPTY_FILTERS: EvidenceFilters={q:'',camera:'',verdict:'',kind:'',start:'',end:''};
function dateRange(filters:EvidenceFilters) {
  const start=filters.start?Date.parse(filters.start):null;
  const end=filters.end?Date.parse(filters.end):null;
  const error=(start!==null && !Number.isFinite(start)) || (end!==null && !Number.isFinite(end))
    ? 'Choose valid dates and times.'
    : start!==null && end!==null && start>end ? 'Choose an end time on or after the start time.' : null;
  return {start,end,error};
}
export function filterEvidence(state:UIState,filters:EvidenceFilters):{clips:Clip[];error:string|null} {
  const range=dateRange(filters);
  if(range.error) return {clips:[],error:range.error};
  const base=Date.parse(state.session.start);
  if((range.start!==null || range.end!==null) && !Number.isFinite(base)) {
    return {clips:[],error:'The recording date is unavailable; time filters cannot be applied.'};
  }
  const query=filters.q.trim().toLowerCase();
  const visits=new Map(state.visits.map(visit=>[visit.id,visit]));
  const clips=state.clips.filter(clip=>{
    const visit=visits.get(clip.visit_id);
    const text=[clip.title,visit?.title,visit?.story,visit?.reason].filter(Boolean).join(' ').toLowerCase();
    const at=base+clip.t0*1000;
    return (!query || text.includes(query)) && (!filters.camera || clip.camera_id===filters.camera)
      && (!filters.verdict || clip.verdict===filters.verdict) && (!filters.kind || clip.kind===filters.kind)
      && (range.start===null || at>=range.start) && (range.end===null || at<=range.end);
  }).sort((a,b)=>b.t0-a.t0 || a.id.localeCompare(b.id));
  return {clips,error:null};
}
export function toSearchParams(filters:EvidenceFilters):{params:Record<string,string>;error:string|null} {
  const range=dateRange(filters);
  if(range.error) return {params:{},error:range.error};
  return {params:{q:filters.q.trim(),camera:filters.camera,verdict:filters.verdict,kind:filters.kind,
    start:range.start===null?'':new Date(range.start).toISOString(),
    end:range.end===null?'':new Date(range.end).toISOString()},error:null};
}
