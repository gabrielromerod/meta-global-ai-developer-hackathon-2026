// Authored UI review fixture. Callbacks report invocation; they never simulate a server save.
import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import '../../styles/tokens.css';
import '../../styles/base.css';
import fixture from '../../fixtures/state.json';
import type {PageProps,Route,UIState} from '../../contracts';
import {AppShell} from '../../shell';
import {Button,EmptyState,Modal,VerdictBadge} from '../../components/ui';
import {SettingsPage} from './index';
import {RulesPage} from '../rules';
import {BenchmarkPage} from '../benchmark';
import './preview.css';

function Preview(){
  const params=new URLSearchParams(location.search);const context=params.get('context');
  const [route,setRoute]=useState<Route>((params.get('route')||'settings') as Route);
  const [theme,setTheme]=useState<'dark'|'light'>(params.get('theme')==='light'?'light':'dark');
  const [visitId,setVisitId]=useState<string|null>(null);const [callback,setCallback]=useState<string|null>(null);
  const [ruleStates,setRuleStates]=useState<Record<string,string>>({});const [cancelled,setCancelled]=useState<string[]>([]);
  const state=structuredClone(fixture) as unknown as UIState;
  if(params.get('many')==='1'){
    const rules=state.rules,objects=state.protected_objects;
    state.rules=Array.from({length:11},(_,i)=>({...rules[i%rules.length],id:`${rules[i%rules.length].id}-${i}`,name:i<rules.length?rules[i].name:`${rules[i%rules.length].name} (${Math.floor(i/rules.length)+1})`,state:i%4===3?'inactive':rules[i%rules.length].state}));
    state.protected_objects=Array.from({length:6},(_,i)=>({...objects[i%objects.length],id:i<objects.length?objects[i].id:`${String(objects[0].id)}-${i}`,label:['side gate','recycling bin','front porch','garage door','back gate','mailbox'][i]}));
  }
  if(params.get('many')==='1'&&state.owner.windows[0]){const w=state.owner.windows[0];state.owner.windows=[{...w,id:'preview-guest',label:'Plumber visit',start:'2026-11-04T10:00:00-08:00',end:'2026-11-04T12:00:00-08:00',state:'scheduled',recorded:false},{...w,id:'preview-parcel',label:'Parcel delivery',start:'2026-11-03T14:00:00-08:00',end:'2026-11-03T17:00:00-08:00',state:'active',recorded:false,cameras:[]},...state.owner.windows].filter(x=>!cancelled.includes(x.id));}
  state.rules=state.rules.map(rule=>ruleStates[rule.id]?{...rule,state:ruleStates[rule.id]}:rule);
  if(context?.startsWith('edge')){state.mode='edge';state.owner.enabled=context.includes('owner');state.capabilities.owner=state.owner.enabled;}
  if(context==='empty'){state.cameras=[];state.rules=[];state.protected_objects=[];state.owner.windows=[];}
  if(params.get('review')==='1'&&state.cameras.length>=3){state.cameras[0].privacy_reviewed=true;state.cameras[1].privacy_reviewed=false;state.cameras[2].privacy_reviewed=true;state.cameras[2].status='privacy_blocked';}
  const record=(label:string)=>setCallback(`${label} callback captured. This review fixture did not contact the home box or change stored state.`);
  const actionProps:Pick<PageProps,'ownerActions'|'ruleActions'>=context?.startsWith('edge')?{
    ownerActions:{saveToken:()=>record('Owner token (value not logged)'),checkIn:()=>record('Check-in'),createWindow:()=>record('Expected window'),cancelWindow:id=>setCancelled(current=>[...current,id])},
    ruleActions:{compile:()=>record('Compile draft'),confirm:()=>record('Confirm draft'),recordVoice:()=>record('Phone recording')},
  }:{};
  if(params.get('draft')==='1'&&actionProps.ruleActions&&state.rules[0])actionProps.ruleActions.draft={...state.rules[0],state:'draft'};
  if(params.get('notice')==='1'&&actionProps.ruleActions)actionProps.ruleActions.notice='Recorded result shown. This is an authored UI fixture, not a live compilation.';
  if(params.get('pending')==='1'&&actionProps.ownerActions)actionProps.ownerActions.pending=true;
  if(params.get('error')==='1'&&actionProps.ownerActions)actionProps.ownerActions.error='Authored error state: owner session unavailable.';
  const owner=context==='edge-owner';
  const props:PageProps={state,onOpenVisit:setVisitId,onOpenClip:()=>record('Open clip'),...actionProps,
    onRuleAction:owner?(id,action)=>setRuleStates(current=>({...current,[id]:action==='activate'?'active':'inactive'})):undefined,
    protectionSlot:<Button disabled={!owner} onClick={()=>record('Add object')}>Add object</Button>};
  document.body.dataset.ready='1';
  const visit=state.visits.find(v=>v.id===visitId);
  return <><AppShell route={route} onNavigate={setRoute} state={state} theme={theme} onThemeChange={setTheme} onOpenVisit={setVisitId}>
    {route==='settings'?<SettingsPage {...props}/>:route==='rules'?<RulesPage {...props}/>:route==='benchmark'?<BenchmarkPage {...props}/>:<EmptyState title="This page is reviewed separately" description="Use Settings, Rules or Benchmark for this task preview."/>}
  </AppShell><Modal open={!!visit} title={visit?.title||'Visit'} onClose={()=>setVisitId(null)}>{visit&&<><VerdictBadge verdict={visit.verdict}/><p>{visit.story}</p><p>{visit.reason}</p></>}</Modal>
  <Modal open={!!callback} title="Fixture callback verification" onClose={()=>setCallback(null)}>{callback}</Modal></>;
}
createRoot(document.getElementById('root')!).render(<Preview/>);
