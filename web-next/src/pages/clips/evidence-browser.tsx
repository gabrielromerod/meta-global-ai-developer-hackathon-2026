import {useId, useMemo, useState, type FormEvent} from 'react';
import * as Select from '@radix-ui/react-select';
import {CalendarDays, Check, ChevronDown, ChevronUp, Search} from 'lucide-react';
import type {PageProps} from '../../contracts';
import {Button, Card, Chip, ClipCard, EmptyState, Modal, Tabs} from '../../components/ui';
import {EMPTY_FILTERS, filterEvidence, toSearchParams, type EvidenceFilters} from './model';
import './evidence.css';

const kinds=[{id:'',label:'All clips'},{id:'person',label:'People'},{id:'vehicle',label:'Vehicles'},{id:'package',label:'Packages'}];
const verdicts=[{id:'',label:'All verdicts'},{id:'normal',label:'Normal'},{id:'noteworthy',label:'Noteworthy'},{id:'needs_attention',label:'Needs attention'},{id:'cant_confirm',label:"Can't confirm"}];

function SelectField({label,value,options,onChange}: {label:string;value:string;options:{id:string;label:string}[];onChange:(value:string)=>void}) {
  const id=useId();
  return <div className="evidence-field"><label htmlFor={id}>{label}</label>
    <Select.Root value={value?`value:${value}`:'all'} onValueChange={next=>onChange(next==='all'?'':next.slice(6))}>
      <Select.Trigger id={id} className="evidence-control evidence-select" aria-label={label}>
        <Select.Value/><Select.Icon><ChevronDown aria-hidden="true"/></Select.Icon>
      </Select.Trigger>
      <Select.Portal><Select.Content className="evidence-options" position="popper">
        <Select.ScrollUpButton className="evidence-option-scroll"><ChevronUp aria-hidden="true"/></Select.ScrollUpButton>
        <Select.Viewport>{options.map(option=><Select.Item key={option.id} value={option.id?`value:${option.id}`:'all'} className="evidence-option">
          <Select.ItemText>{option.label}</Select.ItemText><Select.ItemIndicator><Check aria-hidden="true"/></Select.ItemIndicator>
        </Select.Item>)}</Select.Viewport>
        <Select.ScrollDownButton className="evidence-option-scroll"><ChevronDown aria-hidden="true"/></Select.ScrollDownButton>
      </Select.Content></Select.Portal>
    </Select.Root>
  </div>;
}

/** Domain composition of shared UI. No fetching or domain state outside supplied props. */
export function EvidenceBrowser({mode,state,onOpenClip,onSearch}:PageProps & {mode:'clips'|'media'}) {
  const [filters,setFilters]=useState<EvidenceFilters>({...EMPTY_FILTERS});
  const [timeOpen,setTimeOpen]=useState(false);
  const result=useMemo(()=>filterEvidence(state,filters),[state,filters]);
  const searchId=useId();
  const startId=useId();
  const endId=useId();
  const extended=mode==='media';
  const active=Object.values(filters).some(Boolean);
  function change<K extends keyof EvidenceFilters>(key:K,value:EvidenceFilters[K]) {
    setFilters(previous=>({...previous,[key]:value}));
  }
  function submit(event:FormEvent) {
    event.preventDefault();
    const query=toSearchParams(filters);
    if(!query.error && !result.error) onSearch?.(query.params);
  }
  function clear() {
    setFilters({...EMPTY_FILTERS});
    onSearch?.({...EMPTY_FILTERS});
  }
  const cameras=[{id:'',label:'All cameras'},...state.cameras.map(camera=>({id:camera.id,label:camera.name}))];
  return <div className={`evidence-page evidence-page--${mode}`}>
    <header className="evidence-page-heading"><div>
      <h2>{extended?'Search recorded media':'Recorded clips'}</h2>
      <p>{extended?'Find camera evidence by text, time and verdict.':'Review recorded activity from your cameras.'}</p>
    </div><Chip>{result.clips.length} {result.clips.length===1?'clip':'clips'}</Chip></header>
    <Card className="evidence-filter-card">
      <form className={`evidence-filters ${extended?'evidence-filters--extended':''}`} aria-label={extended?'Media search':'Clip filters'} onSubmit={submit} noValidate>
        <div className="evidence-field evidence-search-field"><label htmlFor={searchId}>Search evidence</label>
          <div className="evidence-search-control"><Search aria-hidden="true"/><input id={searchId} type="search" className="evidence-control" value={filters.q} onChange={event=>change('q',event.target.value)}/></div>
        </div>
        <SelectField label="Camera" value={filters.camera} options={cameras} onChange={value=>change('camera',value)}/>
        <SelectField label="Verdict" value={filters.verdict} options={verdicts} onChange={value=>change('verdict',value)}/>
        <div className="evidence-filter-actions">
          {extended && <Button variant={filters.start||filters.end?'secondary':'outline'} className="evidence-range-button" onClick={()=>setTimeOpen(true)}><CalendarDays aria-hidden="true"/>Time range{(filters.start||filters.end) && <span className="evidence-range-set">Set</span>}</Button>}
          <Button variant="outline" onClick={clear} disabled={!active}>Clear filters</Button><Button type="submit" disabled={!onSearch || Boolean(result.error)} title={!onSearch?'Filters update as you type.':undefined}>Apply filters</Button></div>
        {!onSearch && <p className="evidence-time-note">Filters update as you type.</p>}
        {result.error && !timeOpen && <p className="evidence-filter-error" role="alert">{result.error}</p>}
      </form>
    </Card>
    <Tabs className="evidence-kind-tabs" items={kinds} value={filters.kind} onChange={value=>change('kind',value)} label="Clip category">
      <div className="evidence-results" tabIndex={0} role="region" aria-label="Clip results">
        <div className="evidence-results-heading" aria-live="polite"><p>{result.error?'Search needs attention':`${result.clips.length} matching ${result.clips.length===1?'clip':'clips'}`}</p><span>Newest first</span></div>
        {result.clips.length ? <ul className="evidence-grid" aria-label="Recorded clips">{result.clips.map(clip=><li key={clip.id}><ClipCard clip={clip} onOpen={onOpenClip}/><p className="evidence-camera-name">{state.cameras.find(camera=>camera.id===clip.camera_id)?.name ?? clip.camera_id}</p></li>)}</ul>
          : <EmptyState title={result.error?'Check the date filters':active?'No matching clips':'No clips yet'} description={result.error?'Correct the date range to search this recording.':active?'Try another search or clear the filters.':'Recorded camera clips will appear here.'}/>}
      </div>
    </Tabs>
    {extended && <Modal open={timeOpen} title="Time range" onClose={()=>setTimeOpen(false)}>
      <div className="evidence-date-fields"><p className="evidence-time-note">Date filters use this device's local time.</p>
        <div className="evidence-field"><label htmlFor={startId}>From (local time)</label><input id={startId} className="evidence-control" type="datetime-local" value={filters.start} onChange={event=>change('start',event.target.value)}/></div>
        <div className="evidence-field"><label htmlFor={endId}>Until (local time)</label><input id={endId} className="evidence-control" type="datetime-local" value={filters.end} onChange={event=>change('end',event.target.value)}/></div>
        {result.error && <p className="evidence-filter-error" role="alert">{result.error}</p>}
        <div className="evidence-date-actions"><Button variant="outline" disabled={!filters.start&&!filters.end} onClick={()=>setFilters(previous=>({...previous,start:'',end:''}))}>Clear time range</Button><Button onClick={()=>setTimeOpen(false)}>Done</Button></div>
      </div>
    </Modal>}
  </div>;
}
