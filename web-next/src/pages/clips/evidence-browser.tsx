import {useId, useMemo, useState, type FormEvent} from 'react';
import * as Select from '@radix-ui/react-select';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import {CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Search, X} from 'lucide-react';
import type {PageProps} from '../../contracts';
import {Button, ClipCard, EmptyState, Tabs} from '../../components/ui';
import {EMPTY_FILTERS, filterEvidence, toSearchParams, type EvidenceFilters} from './model';
import './evidence.css';

const PAGE_SIZE=12;
const kinds=[{id:'',label:'All clips'},{id:'person',label:'People'},{id:'vehicle',label:'Vehicles'},{id:'package',label:'Packages'}];
const verdicts=[{id:'',label:'All verdicts'},{id:'normal',label:'Normal'},{id:'noteworthy',label:'Noteworthy'},{id:'needs_attention',label:'Needs attention'},{id:'cant_confirm',label:"Can't confirm"}];

/** Filter chip backed by an accessible Radix select: shows its name until a value is chosen. */
function ChipSelect({label,value,options,onChange}: {label:string;value:string;options:{id:string;label:string}[];onChange:(value:string)=>void}) {
  const chosen=options.find(option=>option.id===value&&option.id);
  return <Select.Root value={value?`value:${value}`:'all'} onValueChange={next=>onChange(next==='all'?'':next.slice(6))}>
    <Select.Trigger className="media-chip" data-active={chosen?'':undefined} aria-label={label}>
      <span>{chosen?chosen.label:label}</span><Select.Icon><ChevronDown aria-hidden="true"/></Select.Icon>
    </Select.Trigger>
    <Select.Portal><Select.Content className="evidence-options" position="popper" sideOffset={6}>
      <Select.ScrollUpButton className="evidence-option-scroll"><ChevronUp aria-hidden="true"/></Select.ScrollUpButton>
      <Select.Viewport>{options.map(option=><Select.Item key={option.id} value={option.id?`value:${option.id}`:'all'} className="evidence-option">
        <Select.ItemText>{option.label}</Select.ItemText><Select.ItemIndicator><Check aria-hidden="true"/></Select.ItemIndicator>
      </Select.Item>)}</Select.Viewport>
      <Select.ScrollDownButton className="evidence-option-scroll"><ChevronDown aria-hidden="true"/></Select.ScrollDownButton>
    </Select.Content></Select.Portal>
  </Select.Root>;
}

function Pager({page,count,onChange}:{page:number;count:number;onChange:(page:number)=>void}){
  if(count<=1)return null;
  return <nav className="pv-pager" aria-label="Clip pages"><button type="button" className="pv-icon-btn" aria-label="Previous page" disabled={page===0} onClick={()=>onChange(page-1)}><ChevronLeft aria-hidden="true"/></button><span>{page+1} / {count}</span><button type="button" className="pv-icon-btn" aria-label="Next page" disabled={page>=count-1} onClick={()=>onChange(page+1)}><ChevronRight aria-hidden="true"/></button></nav>;
}

/** Domain composition of shared UI. No fetching or domain state outside supplied props. */
export function EvidenceBrowser({mode,state,onOpenClip,onSearch,capturesSlot}:PageProps & {mode:'clips'|'media'}) {
  const [filters,setFilters]=useState<EvidenceFilters>({...EMPTY_FILTERS});
  const [timeOpen,setTimeOpen]=useState(false);
  const [page,setPage]=useState(0);
  const result=useMemo(()=>filterEvidence(state,filters),[state,filters]);
  const searchId=useId(),startId=useId(),endId=useId();
  const active=Object.values(filters).some(Boolean);
  const timeSet=Boolean(filters.start||filters.end);
  const pageCount=Math.max(1,Math.ceil(result.clips.length/PAGE_SIZE));
  const safePage=Math.min(page,pageCount-1);
  const visible=result.clips.slice(safePage*PAGE_SIZE,(safePage+1)*PAGE_SIZE);
  function change<K extends keyof EvidenceFilters>(key:K,value:EvidenceFilters[K]) {
    setFilters(previous=>({...previous,[key]:value}));setPage(0);
  }
  function submit(event:FormEvent) {
    event.preventDefault();
    const query=toSearchParams(filters);
    if(!query.error && !result.error) onSearch?.(query.params);
  }
  function clear() {
    setFilters({...EMPTY_FILTERS});setPage(0);
    onSearch?.({...EMPTY_FILTERS});
  }
  const cameras=[{id:'',label:'All cameras'},...state.cameras.map(camera=>({id:camera.id,label:camera.name}))];
  const cameraName=(id:string)=>state.cameras.find(camera=>camera.id===id)?.name ?? id;
  return <div className={`evidence-page evidence-page--${mode}`}>
    {mode==='media'&&capturesSlot}
    <form className="media-toolbar" aria-label={mode==='media'?'Media search':'Clip filters'} onSubmit={submit} noValidate>
      <div className="media-search-row">
        <label className="media-search" htmlFor={searchId}><Search aria-hidden="true"/><span className="v-sr-only">Search evidence</span>
          <input id={searchId} type="search" placeholder="Search clips, e.g. “package at the porch”" value={filters.q} onChange={event=>change('q',event.target.value)}/>
        </label>
        <Button type="submit" disabled={!onSearch || Boolean(result.error)} aria-label="Apply filters" title={!onSearch?'Filters update as you type.':undefined}>Apply</Button>
      </div>
      {!onSearch && <p className="evidence-time-note">Filters update as you type.</p>}
      {result.error && !timeOpen && <p className="evidence-filter-error" role="alert">{result.error}</p>}
    </form>
    <Tabs className="evidence-kind-tabs" items={kinds} value={filters.kind} onChange={value=>change('kind',value)} label="Clip category">
        <div className="media-chip-row" role="group" aria-label="Filters">
        <ChipSelect label="Camera" value={filters.camera} options={cameras} onChange={value=>change('camera',value)}/>
        <ChipSelect label="Verdict" value={filters.verdict} options={verdicts} onChange={value=>change('verdict',value)}/>
        <DropdownMenu.Root open={timeOpen} onOpenChange={setTimeOpen} modal={false}>
          <DropdownMenu.Trigger asChild><button type="button" className="media-chip" data-active={timeSet?'':undefined}><CalendarDays aria-hidden="true"/>Time range</button></DropdownMenu.Trigger>
          <DropdownMenu.Portal><DropdownMenu.Content className="evidence-date-popover" align="start" sideOffset={8} onCloseAutoFocus={event=>event.preventDefault()}>
            <div className="evidence-date-fields"><strong>Time range</strong><p className="evidence-time-note">Dates use this device's local time.</p>
              <div className="evidence-field"><label htmlFor={startId}>From (local time)</label><input id={startId} className="evidence-control" type="datetime-local" value={filters.start} onChange={event=>change('start',event.target.value)}/></div>
              <div className="evidence-field"><label htmlFor={endId}>Until (local time)</label><input id={endId} className="evidence-control" type="datetime-local" value={filters.end} onChange={event=>change('end',event.target.value)}/></div>
              {result.error && <p className="evidence-filter-error" role="alert">{result.error}</p>}
              <div className="evidence-date-actions"><Button variant="outline" disabled={!timeSet} onClick={()=>{setFilters(previous=>({...previous,start:'',end:''}));setPage(0);}}>Clear</Button><Button onClick={()=>setTimeOpen(false)}>Done</Button></div>
            </div>
          </DropdownMenu.Content></DropdownMenu.Portal>
        </DropdownMenu.Root>
        {active&&<button type="button" className="media-clear" onClick={clear} aria-label="Clear filters"><X aria-hidden="true"/>Clear</button>}
        </div>
      <div className="media-results" role="region" aria-label="Clip results">
        <p className="media-count" aria-live="polite">{result.error?'Search needs attention':`${result.clips.length} ${result.clips.length===1?'clip':'clips'} · newest first`}</p>
        {result.clips.length ? <ul className="evidence-grid pv-scroll" tabIndex={0} aria-label="Recorded clips">{visible.map(clip=><li key={clip.id}><ClipCard clip={clip} onOpen={onOpenClip} cameraName={cameraName(clip.camera_id)} illustration={state.evidence.kind==='fixture'&&!clip.thumbnail_url?`${import.meta.env.BASE_URL}illustrations/scene-${(state.clips.findIndex(item=>item.id===clip.id)%6)+1}.jpg`:undefined}/></li>)}</ul>
          : <EmptyState title={result.error?'Check the date filters':active?'No matching clips':'No clips yet'} description={result.error?'Correct the date range to search this recording.':active?'Try another search or clear the filters.':'Recorded camera clips will appear here.'}/>}
        <Pager page={safePage} count={pageCount} onChange={setPage}/>
      </div>
    </Tabs>
  </div>;
}
