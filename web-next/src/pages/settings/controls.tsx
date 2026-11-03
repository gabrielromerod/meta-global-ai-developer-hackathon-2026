import type {ReactNode} from 'react';
import {Chip} from '../../components/ui';
import type {Rule, Verdict} from '../../contracts';

export function PageHeading({title,description,action}:{title:string;description:string;action?:ReactNode}) {
  return <header className="controls-heading"><div><h2>{title}</h2><p>{description}</p></div>{action}</header>;
}
export function Field({label,id,children,hint}:{label:string;id:string;children:ReactNode;hint?:string}) {
  return <div className="controls-field"><label htmlFor={id}>{label}</label>{children}{hint&&<p className="controls-hint">{hint}</p>}</div>;
}
export function StatusChip({value}:{value:string}) {
  return <Chip tone={value==='active'?'success':value==='privacy_blocked'?'warning':'default'}>{words(value)}</Chip>;
}
export function words(value:unknown):string {return typeof value==='string'?value.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase()):'Not provided';}
export function scopeLabel(rule:Rule):string {
  return ({anyone:'Everyone',non_household:'Everyone except household',external_visitor_only:'Arrivals from outside only'} as Record<string,string>)[rule.applies_to]||'Scope not provided';
}
export function ruleVerdict(rule:Rule):Verdict|null {
  return ['normal','noteworthy','needs_attention','cant_confirm'].includes(rule.severity)?rule.severity as Verdict:null;
}
export function formatRecordedTime(value:string):string {
  const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::[^Z+-]*)?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if(!match)return value;
  const [,year,month,day,hour,minute,offset]=match;
  const date=new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(Date.UTC(+year,+month-1,+day)));
  return `${date}, ${+hour%12||12}:${minute} ${+hour<12?'AM':'PM'} (${offset==='Z'?'UTC':`UTC${offset}`})`;
}
