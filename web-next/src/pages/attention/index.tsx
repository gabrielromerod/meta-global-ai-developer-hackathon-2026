import {useState} from 'react';
import type {PageProps, Verdict} from '../../contracts';
import {Card, Chip, EmptyState, Tabs} from '../../components/ui';
import {attentionVisits} from '../home/model';
import {VisitCard} from '../home/visit-card';
import '../home/home.css';
import './attention.css';

const filters = [
  {id:'all',label:'All visits'}, {id:'needs_attention',label:'Needs attention'},
  {id:'noteworthy',label:'Noteworthy'}, {id:'cant_confirm',label:"Can't confirm"},
  {id:'normal',label:'Normal'},
];

export function AttentionPage({state,onOpenVisit,visitSlot}: PageProps) {
  const [filter,setFilter] = useState<Verdict|'all'>('all');
  const ranked = attentionVisits(state, state.attention_ids.length);
  const shown = ranked.filter(visit => filter === 'all' || visit.verdict === filter);
  return <div className="attention-page">
    <header className="attention-intro"><div><h2>Attention center</h2>
      <p>Review the evidence behind each visit.</p></div><Chip>{ranked.length} to review</Chip></header>
    <Tabs className="attention-tabs" items={filters} value={filter} label="Filter visits by verdict"
      onChange={value=>setFilter(value as Verdict|'all')}>
      <div className="attention-workspace">
        <Card className="attention-list-panel" title="Visits" actions={<span className="attention-count">{shown.length} shown</span>}>
          <div className="attention-visit-list" tabIndex={0} aria-label="Filtered visits">
            {shown.length ? shown.map(visit=><VisitCard key={visit.id} visit={visit} cameras={state.cameras} onOpen={onOpenVisit}/>)
              : <EmptyState title="No matching visits" description="There are no recorded visits with this verdict."/>}
          </div>
        </Card>
        {visitSlot && <Card title="Visit evidence" className="attention-evidence">{visitSlot}</Card>}
      </div>
    </Tabs>
  </div>;
}
