import type {Citation, Evidence, Verdict, VisitEvent} from '../contracts';
import type {OverlayFrame} from './model';
export interface PlaybackCamera {id:string;name:string;clip_t0:number;clip_url:string|null;width:number;height:number;source_label:string}
export interface VisitDetail {
  id:string;scenario:string;scenario_title:string;verdict:Verdict;verdict_label:string;t0:number;t1:number;first_sentence:string;
  evidence:Evidence;sentences:{index:number;text:string;source:string;gap_id:string|null;citations:(Citation&VisitEvent)[];badge:{kind:string;label:string;model:string|null;call_id:string|null}}[];
  events:VisitEvent[];gaps:{id:string;label:string;t0:number;t1:number;resolved:boolean;clock_t0?:string;clock_t1?:string;region_name?:string}[];
  subjects:{id:string;role_label:string;role_basis:string;basis_label:string}[];
  rule_hits:{rule_id:string;rule_name:string;event_id:string;applies_to?:string}[];
  expected_windows:{id:string;label:string;start:string;end:string}[];
  watches:{id:string;notice:string|null;status?:string;origin_label?:string;can_undo?:boolean}[];
  trace:{triage:{forced?:boolean;reason?:string}|null;rules_excluded:{reason:string}[];drafts:{attempt:number;passed:boolean;failures:{detail:string}[]}[];verdict_inputs:Record<string,unknown>};
  telemetry:{totals:{count:number;cost_usd:number;latency_ms:number};calls:{id:string;model:string;purpose:string;cached:boolean;cost_usd:number}[]};
  playback_cameras:PlaybackCamera[];overlays:Record<string,Record<string,{frames:OverlayFrame[];label:string;cls:string}>>;
  playback_t0:number;playback_t1:number;
}
export function ownerToken() {return sessionStorage.getItem('vigil_owner_token')||'';}
/** On this machine only (VIGIL_OWNER_AUTOLOGIN), the home box hands its owner token to the browser. */
let localTried=false;
export async function adoptLocalOwner():Promise<void> {
  if(localTried)return;localTried=true;
  try{const r=await fetch('/api/owner/local-session',{credentials:'same-origin',cache:'no-store'});if(!r.ok)return;const d=await r.json();if(typeof d.token==='string'&&d.token)sessionStorage.setItem('vigil_owner_token',d.token);}catch{/* not offered: owner controls stay locked */}
}
export async function api<T>(path:string,body?:unknown,method?:string):Promise<T> {
  const headers:Record<string,string>={};
  const token=ownerToken();if(token)headers['X-Vigil-Owner']=token;
  if(body!==undefined)headers['Content-Type']='application/json';
  const response=await fetch(path,{method:method??(body===undefined?'GET':'POST'),headers,credentials:'same-origin',body:body===undefined?undefined:JSON.stringify(body)});
  let data;try{data=await response.json();}catch{throw new Error('The home box returned an unreadable response.');}
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:`Request failed (${response.status}).`);
  return data as T;
}
