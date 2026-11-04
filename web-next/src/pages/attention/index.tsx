import {useState} from 'react';
import {ChevronLeft, ChevronRight, Lightbulb} from 'lucide-react';
import type {PageProps, Verdict} from '../../contracts';
import {EmptyState, Tabs} from '../../components/ui';
import {attentionVisits, touchComparison} from '../home/model';
import {TouchCard, VisitCard} from '../home/visit-card';
import '../home/home.css';
import './attention.css';

const PAGE_SIZE = 8;
const filters = [
  {id:'all',label:'All visits'}, {id:'needs_attention',label:'Needs attention'},
  {id:'noteworthy',label:'Noteworthy'}, {id:'cant_confirm',label:"Can't confirm"},
  {id:'normal',label:'Normal'},
];

function Pager({page,count,onChange}:{page:number;count:number;onChange:(page:number)=>void}){
  if(count<=1)return null;
  return <nav className="pv-pager" aria-label="Visit pages"><button type="button" className="pv-icon-btn" aria-label="Previous page" disabled={page===0} onClick={()=>onChange(page-1)}><ChevronLeft aria-hidden="true"/></button><span>{page+1} / {count}</span><button type="button" className="pv-icon-btn" aria-label="Next page" disabled={page>=count-1} onClick={()=>onChange(page+1)}><ChevronRight aria-hidden="true"/></button></nav>;
}

export function AttentionPage({state,onOpenVisit,visitSlot,capturesSlot}: PageProps) {
  const [filter,setFilter] = useState<Verdict|'all'>('all');
  const [page,setPage] = useState(0);
  const urgent = attentionVisits(state, state.attention_ids.length);
  const comparison = touchComparison(state);
  const ranked = [...urgent,...state.visits.filter(visit=>!state.attention_ids.includes(visit.id)).sort((a,b)=>b.t0-a.t0)];
  const shown = ranked.filter(visit => filter === 'all' || visit.verdict === filter);
  const pageCount = Math.max(1, Math.ceil(shown.length/PAGE_SIZE));
  const safePage = Math.min(page, pageCount-1);
  const visible = shown.slice(safePage*PAGE_SIZE, (safePage+1)*PAGE_SIZE);
  return <div className="attention-page">
    {capturesSlot&&<div className="attention-real">{capturesSlot}</div>}
    <Tabs className="pv-tabs attention-tabs" items={filters} value={filter} label="Filter visits by verdict"
      onChange={value=>{setFilter(value as Verdict|'all');setPage(0);}}>
      <div className="attention-workspace">
        <section className="pv-section attention-list-panel" aria-labelledby="attention-visits-title">
          <header className="pv-section-head"><h2 id="attention-visits-title">Visits</h2>
            <span className="pv-meta">{urgent.length} to review · {shown.length} shown</span></header>
          {comparison && <details className="att-explainer">
            <summary><Lightbulb aria-hidden="true"/>Why did two {comparison.label} touches get different verdicts?</summary>
            <section className="pv-section" aria-label="Same action, different context">
              <p className="pv-hint">Vigil judges the route someone took, never how they look.</p>
              <ul className="pv-list"><li><TouchCard evidence={comparison.household} label={comparison.label} context="household" onOpen={onOpenVisit}/></li>
                <li><TouchCard evidence={comparison.external} label={comparison.label} context="external" onOpen={onOpenVisit}/></li></ul>
            </section>
          </details>}
          {shown.length ? <ul className="pv-list pv-scroll vc-list" tabIndex={0} aria-label="Filtered visits">
              {visible.map(visit=><li key={visit.id}><VisitCard visit={visit} cameras={state.cameras} onOpen={onOpenVisit}/></li>)}
            </ul>
            : <EmptyState title="No matching visits" description="No recorded visit has this verdict. Try another filter."/>}
          <Pager page={safePage} count={pageCount} onChange={setPage}/>
        </section>
        {visitSlot && <section className="pv-section attention-evidence" aria-label="Visit evidence">
          <header className="pv-section-head"><h2>Visit evidence</h2></header>
          <div className="pv-scroll attention-evidence-body" tabIndex={0} aria-label="Visit evidence details">{visitSlot}</div>
        </section>}
      </div>
    </Tabs>
  </div>;
}
