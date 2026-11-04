import {useEffect,useId,useState,type FormEvent} from 'react';
import {ChevronLeft,ChevronRight,Clock,Info,Mic,Pencil,Plus,ShieldCheck,Sparkles,Tag} from 'lucide-react';
import type {PageProps,Rule} from '../../contracts';
import {Button,Card,Chip,EmptyState,Modal,VerdictBadge} from '../../components/ui';
import {Field,ruleVerdict,scopeLabel,StatusChip,words} from '../settings/controls';
import {OwnerControls} from '../settings';
import '../settings/controls.css';


const PAGE_SIZE=8,OBJECT_PAGE_SIZE=4;
const SUGGESTIONS=['Alert me if someone opens the side gate at night','Tell me if a package is removed from the porch','Alert me if a non-household person enters the backyard after 23:00'];

function Pager({page,count,onChange,label}:{page:number;count:number;onChange:(page:number)=>void;label:string}){
  if(count<=1)return null;
  return <nav className="pv-pager" aria-label={label}><button type="button" className="pv-icon-btn" aria-label="Previous page" disabled={page===0} onClick={()=>onChange(page-1)}><ChevronLeft aria-hidden="true"/></button><span>{page+1} / {count}</span><button type="button" className="pv-icon-btn" aria-label="Next page" disabled={page>=count-1} onClick={()=>onChange(page+1)}><ChevronRight aria-hidden="true"/></button></nav>;
}
function hoursOf(rule:Rule){const a=rule.active;return a&&typeof a.start==='string'&&typeof a.end==='string'?`${a.start} – ${a.end}`:'Always';}

export function RulesPage(props:PageProps){
  const {state,ruleActions,onOpenVisit,protectionSlot,onRuleAction}=props;
  const owner=state.mode==='edge'&&state.owner.enabled;
  const [objectPage,setObjectPage]=useState(0);
  const [ruleFilter,setRuleFilter]=useState('all');
  const [ruleOpen,setRuleOpen]=useState(false);const [editing,setEditing]=useState(false);
  const [rulePage,setRulePage]=useState(0);
  const activeCount=state.rules.filter(rule=>rule.state==='active').length;
  const filteredRules=state.rules.filter(rule=>ruleFilter==='all'||(ruleFilter==='active'?rule.state==='active':rule.state!=='active'));
  const pageCount=Math.max(1,Math.ceil(filteredRules.length/PAGE_SIZE));
  const safePage=Math.min(rulePage,pageCount-1);
  const visibleRules=filteredRules.slice(safePage*PAGE_SIZE,(safePage+1)*PAGE_SIZE);
  const id=useId();const [text,setText]=useState(ruleActions?.transcript||'');
  useEffect(()=>{if(ruleActions?.transcript!==undefined)setText(ruleActions.transcript);},[ruleActions?.transcript]);
  const pending=!!ruleActions?.pending;const canConfirm=owner&&!!ruleActions?.confirm&&!pending;
  const canDraft=!!ruleActions?.compile&&!pending;
  function compile(event:FormEvent){event.preventDefault();if(text.trim()&&ruleActions?.compile&&!pending)ruleActions.compile(text.trim());}
  const filters=[{id:'all',label:'All',count:state.rules.length},{id:'active',label:'Active',count:activeCount},{id:'inactive',label:'Off',count:state.rules.length-activeCount}];
  const objectPages=Math.max(1,Math.ceil(state.protected_objects.length/OBJECT_PAGE_SIZE));
  const safeObjectPage=Math.min(objectPage,objectPages-1);
  const visibleObjects=state.protected_objects.slice(safeObjectPage*OBJECT_PAGE_SIZE,(safeObjectPage+1)*OBJECT_PAGE_SIZE);
  const canToggle=owner&&!!onRuleAction&&!pending;
  function openEditor(seed=''){setText(seed);setEditing(!!seed);setRuleOpen(true);}

  const rules=<section className="pv-section pv-main" aria-labelledby={`${id}-rules`}>
    <header className="pv-section-head"><h2 id={`${id}-rules`}>Rules</h2><Button onClick={()=>openEditor()}><Plus aria-hidden="true"/>New rule</Button></header>
    <div className="pv-toolbar">
      <div className="pv-chips" role="group" aria-label="Filter rules by status">{filters.map(filter=><button key={filter.id} type="button" aria-pressed={ruleFilter===filter.id} className="pv-pill" onClick={()=>{setRuleFilter(filter.id);setRulePage(0);}}>{filter.label} <span className="pv-count">{filter.count}</span></button>)}</div>
    </div>
    <section className="pv-fill" aria-label="Current rules">{filteredRules.length?<ul className="pv-list pv-scroll" tabIndex={0} aria-label="Rule list">{visibleRules.map(rule=>{
      const target=state.protected_objects.find(object=>object.id===rule.target.id);const verdict=ruleVerdict(rule);const hours=hoursOf(rule);
      return <li key={rule.id} className="pv-row"><span className="pv-bubble" aria-hidden="true">{hours==='Always'?<ShieldCheck/>:<Clock/>}</span>
        <div className="pv-row-body"><strong>{rule.name}</strong><span className="pv-meta">{words(rule.trigger)} · {words(target?.label||rule.target.id)} · {hours}</span><span className="pv-meta">{scopeLabel(rule)}</span></div>
        <div className="pv-row-end">{verdict?<VerdictBadge verdict={verdict}/>:<Chip>Not provided</Chip>}{rule.state!=='active'&&<StatusChip value={rule.state}/>}
          {owner&&<><button type="button" role="switch" className="pv-switch" aria-checked={rule.state==='active'} aria-label={`${rule.name} on`} disabled={!canToggle} title={onRuleAction?undefined:'Turning rules on or off is not available on this server yet'} onClick={()=>onRuleAction?.(rule.id,rule.state==='active'?'deactivate':'activate')}><span/></button>
          <button type="button" className="pv-icon-btn" aria-label={`Edit ${rule.name}`} disabled={!ruleActions?.compile||pending} onClick={()=>openEditor(rule.name)}><Pencil aria-hidden="true"/></button></>}</div></li>;})}</ul>
      :<EmptyState title={state.rules.length?'No matching rules':'No rules yet'} description={state.rules.length?'Choose another filter.':'Describe what should get your attention, in your own words.'} action={!state.rules.length?<Button onClick={()=>openEditor()}><Plus aria-hidden="true"/>New rule</Button>:undefined}/>}
      <Pager page={safePage} count={pageCount} onChange={setRulePage} label="Rule pages"/>
    </section>
    <Modal open={ruleOpen} title={editing?'Edit rule':'New rule'} onClose={()=>setRuleOpen(false)} description={editing?'Change the wording and review the new draft. Turn the old rule off once the new one is confirmed.':'Say it like you would to a neighbour. You review it before it is saved.'}>
      <div className="pv-flow">
        <form className="controls-form" onSubmit={compile}>
          <Field label="What should Vigil watch for?" id={`${id}-text`}><textarea id={`${id}-text`} className="controls-textarea" placeholder="Type it, tap a suggestion or dictate" value={text} onChange={e=>setText(e.target.value)} maxLength={500} disabled={!canDraft}/></Field>
          <div className="pv-suggest" aria-label="Suggestions"><Sparkles aria-hidden="true"/>{SUGGESTIONS.map(s=><button key={s} type="button" className="pv-pill" disabled={!canDraft} onClick={()=>setText(s)}>{s}</button>)}</div>
          {!!ruleActions?.voiceFixtures?.length&&<div className="pv-suggest" aria-label="Voice samples"><Mic aria-hidden="true"/>{ruleActions.voiceFixtures.map(fixture=><button type="button" className="pv-pill" key={fixture.id} onClick={()=>ruleActions?.transcribeFixture?.(fixture.id)} disabled={!ruleActions?.transcribeFixture||pending}>{fixture.label}</button>)}</div>}
          <div className="pv-actions pv-actions-split">
            <Button variant="outline" onClick={()=>ruleActions?.recordVoice?.()} disabled={!ruleActions?.recordVoice||pending} aria-label="Dictate rule"><Mic aria-hidden="true"/>Dictate</Button>
            <Button type="submit" disabled={!canDraft||!text.trim()}>{pending?'Preparing draft…':'Review rule draft'}</Button>
          </div>
        </form>
        <p className="pv-hint">{ruleActions?.compile?'Dictation uses your phone microphone only. A draft never changes an active rule.':'Rule drafting is not available in this view.'}</p>
        {ruleActions?.error&&<p className="controls-error" role="alert">{ruleActions.error}</p>}
        {ruleActions?.notice&&<p className="controls-status" role="status">{ruleActions.notice}</p>}
        {ruleActions?.draft&&<Card title="Rule draft"><RuleCard rule={ruleActions.draft} objects={state.protected_objects}/>
          {ruleActions.explanation&&<ul className="pv-notes"><li>{ruleActions.explanation.applies_label}</li><li>{ruleActions.explanation.basis_note}</li>{ruleActions.explanation.limits_note.map((note,index)=><li key={index}>{note}</li>)}</ul>}
          <Button disabled={!canConfirm} onClick={()=>ruleActions.confirm?.(ruleActions.draft!.id)}>Confirm rule</Button>
          {!canConfirm&&<p className="pv-hint">{owner?'Rule confirmation is not available in this view.':'Owner-only on the home box'}</p>}</Card>}
      </div>
    </Modal>
  </section>;

  const objects=<section className="pv-section pv-objects" aria-labelledby={`${id}-objects`}>
    <header className="pv-section-head"><h2 id={`${id}-objects`}>Protected objects</h2>{protectionSlot}</header>
    {state.protected_objects.length?<ul className="pv-list pv-scroll" tabIndex={0} aria-label="Protected object list">{visibleObjects.map(object=>{
      const visitIds=state.events.filter(event=>event.target===object.id).map(event=>event.visit_id);const visit=state.visits.find(v=>visitIds.includes(v.id));
      const ruleCount=state.rules.filter(rule=>rule.target.id===object.id).length;
      return <li key={String(object.id)} className="pv-row"><span className="pv-bubble" aria-hidden="true"><Tag/></span>
        <div className="pv-row-body"><h3>{String(object.label||'Protected object')}</h3><span className="pv-meta">{state.cameras.find(c=>c.id===object.camera_id)?.name||'Camera not provided'} · {ruleCount} {ruleCount===1?'rule':'rules'}</span></div>
        {visit&&<button type="button" className="pv-link" onClick={()=>onOpenVisit(visit.id)}>Last visit<ChevronRight aria-hidden="true"/></button>}</li>;})}</ul>
      :<EmptyState title="No protected objects yet" description="Tap a gate, bin or package spot in a camera still so rules can watch it."/>}
    <Pager page={safeObjectPage} count={objectPages} onChange={setObjectPage} label="Object pages"/>
  </section>;

  const visitors=<section className="pv-section pv-visitors" aria-labelledby={`${id}-visitors`}>
    <header className="pv-section-head"><h2 id={`${id}-visitors`}>Visitors</h2></header>
    <div className="pv-scroll" tabIndex={0} aria-label="Visitor controls">
    <OwnerControls {...props} section="visitors" notice={false}/>
    <p className="pv-footnote"><Info aria-hidden="true"/>Vigil never identifies people. Household and visitor roles come from where someone arrived, a check-in or an expected window. Unknown arrivals count as non-household.</p>
    </div>
  </section>;

  return <div className="controls-page rules-page pv-page">
    <div className="protection-content pv-body"><div className="pv-layout">{rules}<aside className="pv-side">{visitors}{objects}</aside></div></div>
  </div>;
}
function RuleCard({rule,objects}:{rule:Rule;objects:Record<string,unknown>[]}){
  const verdict=ruleVerdict(rule);const target=objects.find(o=>o.id===rule.target.id);
  return <article className="pv-row pv-row-flat" aria-label={rule.name}><span className="pv-bubble" aria-hidden="true"><ShieldCheck/></span><div className="pv-row-body"><strong>{rule.name}</strong><span className="pv-meta">{words(rule.trigger)} · {words(target?.label||rule.target.id)} · {hoursOf(rule)}</span><span className="pv-meta">{scopeLabel(rule)}</span></div><div className="pv-row-end">{verdict?<VerdictBadge verdict={verdict}/>:<Chip>Severity not provided</Chip>}</div></article>;
}
