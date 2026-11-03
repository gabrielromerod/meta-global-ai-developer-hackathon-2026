import type {PageProps} from '../../contracts';
import {Card,Chip,EmptyState} from '../../components/ui';
import {PageHeading} from '../settings/controls';
import '../settings/controls.css';

export function BenchmarkPage({state}:PageProps){
  const measured=state.benchmark.measured;
  return <div className="controls-page benchmark-page"><PageHeading title="Field benchmark" description="Measurements appear only after a labelled field evaluation." action={<Chip>{measured?'Measured results':'Not measured'}</Chip>}/><div className="controls-scroll" tabIndex={0} aria-label="Benchmark results">{measured&&state.benchmark.metrics.length?<div className="controls-grid">{state.benchmark.metrics.map((metric,index)=>{const value=typeof metric.value==='number'||typeof metric.value==='string'?String(metric.value):null;return <Card key={typeof metric.id==='string'?metric.id:index} title={typeof metric.label==='string'?metric.label:'Measured metric'}><p className="benchmark-value">{value===null?'Value not provided':`${value}${typeof metric.unit==='string'?' '+metric.unit:''}`}</p>{typeof metric.note==='string'&&<p className="controls-note">{metric.note}</p>}</Card>;})}</div>:<Card><EmptyState title="No field benchmark yet" description="Recorded model examples are not measurements of real-camera accuracy, latency or cost."/></Card>}<p className="controls-note benchmark-note">{state.benchmark.note}</p></div></div>;
}
