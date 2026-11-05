import {BellOff,Coins,Cpu,Gauge,Info,Link2,Scale,Timer} from 'lucide-react';
import type {PageProps} from '../../contracts';
import {Chip} from '../../components/ui';
import {PageHeading} from '../settings/controls';
import '../settings/controls.css';

// What a field evaluation will report. Shown as plans only; values come solely from measured state.
const usd=(v:number)=>v===0?'$0':v<0.01?'<$0.01':`$${v.toFixed(2)}`;
const secs=(ms:number|null)=>ms===null?'—':`${(ms/1000).toFixed(1)} s`;

const PLANNED=[
  {id:'link_precision',label:'Link precision',description:'How often motion clips are joined into the right visit.',icon:Link2},
  {id:'alert_reduction',label:'Alert reduction',description:'Raw camera alerts compared with the visits that need your attention.',icon:BellOff},
  {id:'latency',label:'Latency',description:'Time from the last clip of a visit to its story.',icon:Timer},
  {id:'cost',label:'Cost per visit',description:'Model spend for one processed visit.',icon:Coins},
];

export function BenchmarkPage({state}:PageProps){
  const {measured,metrics,note,models,economics}=state.benchmark;
  const showMeasured=measured&&metrics.length>0;
  const realOnly=(state as typeof state&{real_only?:boolean}).real_only===true;
  return <div className="controls-page benchmark-page"><PageHeading title="Field benchmark" description="Measurements appear only after a labelled field evaluation." action={<Chip>{measured?'Measured results':'Not measured'}</Chip>}/>
    <div className="pv-body"><section className="st-col st-narrow" aria-labelledby="bench-title">
      <header className="pv-section-head"><h2 id="bench-title">{showMeasured?'Field benchmark':'No field benchmark yet'}</h2><Chip tone={showMeasured?'success':'default'}>{showMeasured?'Measured results':'Not measured'}</Chip></header>
      <p className="pv-hint">{showMeasured?'Values from a labelled field evaluation on the real cameras.':realOnly?'No labelled field evaluation has been run on your cameras yet. Accuracy, latency and cost per visit appear here after one.':'Recorded model examples are not measurements of real-camera accuracy, latency or cost. These appear after a labelled field evaluation.'}</p>
      <ul className="pv-list pv-scroll st-list" tabIndex={0} aria-label={showMeasured?'Measured results':'Planned measurements'}>
        {showMeasured?metrics.map((metric,index)=>{const value=typeof metric.value==='number'||typeof metric.value==='string'?String(metric.value):null;const label=typeof metric.label==='string'?metric.label:'Measured metric';
          return <li className="pv-row" key={typeof metric.id==='string'?metric.id:index}><span className="pv-bubble" aria-hidden="true"><Gauge/></span><div className="pv-row-body"><strong>{label}</strong>{typeof metric.note==='string'&&<span className="pv-meta">{metric.note}</span>}</div><span className="bench-value">{value===null?'Value not provided':`${value}${typeof metric.unit==='string'?' '+metric.unit:''}`}</span></li>;})
        :PLANNED.map(item=><li className="pv-row" key={item.id}><span className="pv-bubble" aria-hidden="true"><item.icon/></span><div className="pv-row-body"><strong>{item.label}</strong><span className="pv-meta">{item.description}</span></div><Chip>Not measured yet</Chip></li>)}
      </ul>
      {note&&<p className="pv-footnote"><Info aria-hidden="true"/>{note}</p>}
    </section>
    {models&&models.length>0&&<section className="st-col st-narrow" aria-labelledby="bench-models">
      <header className="pv-section-head"><h2 id="bench-models">Models used on this home</h2><Chip>Call ledger</Chip></header>
      <p className="pv-hint">Every model call goes through one client that prices it first and records it after. This is usage on this home box, not a benchmark.</p>
      <div className="bench-table-wrap" tabIndex={0}><table className="bench-table">
        <thead><tr><th scope="col">Model</th><th scope="col">Live calls</th><th scope="col">From cache</th><th scope="col">Spend</th><th scope="col">Median wait</th></tr></thead>
        <tbody>{models.map(m=><tr key={m.model}><th scope="row"><span className="bench-model"><Cpu aria-hidden="true"/><span><strong>{m.model}</strong><small>{m.role}</small></span></span></th>
          <td>{m.live_calls}</td><td>{m.cached_calls}</td><td>{usd(m.cost_usd)}</td><td>{secs(m.median_latency_ms)}</td></tr>)}</tbody>
        <tfoot><tr><th scope="row">Total</th><td>{models.reduce((a,m)=>a+m.live_calls,0)}</td><td>{models.reduce((a,m)=>a+m.cached_calls,0)}</td><td>{usd(models.reduce((a,m)=>a+m.cost_usd,0))}</td><td/></tr></tfoot>
      </table></div>
    </section>}
    {economics&&<section className="st-col st-narrow" aria-labelledby="bench-econ">
      <header className="pv-section-head"><h2 id="bench-econ">What watching costs per month</h2><Chip tone="warning">Hypothesis, not measured</Chip></header>
      <p className="pv-hint">{economics.note}</p>
      <ul className="pv-list st-list" aria-label="Monthly cost estimates">
        {economics.rows.map(r=><li className="pv-row" key={r.approach}><span className="pv-bubble" aria-hidden="true"><Scale/></span><div className="pv-row-body"><strong>{r.approach}</strong><span className="pv-meta">{r.basis}</span></div><span className="bench-value">{r.monthly}</span></li>)}
      </ul>
    </section>}
    </div>
  </div>;
}
