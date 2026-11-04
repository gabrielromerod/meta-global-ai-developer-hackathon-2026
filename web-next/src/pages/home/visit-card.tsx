import {AlertTriangle, Camera, Check, ChevronRight, CircleAlert, CircleHelp, EyeOff} from 'lucide-react';
import type {Camera as CameraType, Verdict, VisitRow} from '../../contracts';
import type {TouchEvidence} from './model';
import {Chip, VerdictBadge} from '../../components/ui';

const verdictIcon:Record<Verdict,typeof Check>={needs_attention:AlertTriangle,noteworthy:CircleAlert,cant_confirm:CircleHelp,normal:Check};

/* One visit as a list row: verdict bubble, story, role and camera meta, time and chevron. */
export function VisitCard({visit,cameras,onOpen,compact=false}: {visit:VisitRow;cameras:CameraType[];onOpen:(id:string)=>void;compact?:boolean}) {
  const cameraNames = visit.cameras.map(id => cameras.find(camera=>camera.id===id)?.name ?? id);
  const Icon = verdictIcon[visit.verdict] ?? CircleHelp;
  return <button type="button" className={compact?'vc-row vc-compact':'vc-row'} data-verdict={visit.verdict}
    aria-label={`Open visit ${visit.title}`} onClick={()=>onOpen(visit.id)}>
    <span className="pv-bubble vc-bubble" aria-hidden="true"><Icon/></span>
    <span className="vc-body">
      <span className="vc-top"><VerdictBadge verdict={visit.verdict}/><time>{visit.clock}</time></span>
      <span className="vc-story">{visit.first_sentence || visit.story}</span>
      {!compact&&<span className="vc-meta"><Chip>{visit.role_label}</Chip><span className="vc-cameras"><Camera aria-hidden="true"/>{cameraNames.join(' · ') || 'Camera not recorded'}</span></span>}
      {!compact&&visit.gaps.map((gap,index)=><span className="vc-gap" key={`${gap}-${index}`}><EyeOff aria-hidden="true"/>{gap}</span>)}
    </span>
    <ChevronRight className="vc-chevron" aria-hidden="true"/>
  </button>;
}

/* One side of the same-action comparison: verdict, spatial basis and the supplied rule reason. */
export function TouchCard({evidence, label, context, onOpen}: {evidence:TouchEvidence;label:string;
  context:'household'|'external';onOpen:(id:string)=>void}) {
  const {visit, event} = evidence;
  return <button type="button" className="vc-row home-touch" data-verdict={visit.verdict}
    aria-label={`Open ${context} ${label} visit`} onClick={()=>onOpen(visit.id)}>
    <span className="vc-body">
      <span className="vc-top"><VerdictBadge verdict={visit.verdict}/><time>{event.clock}</time></span>
      <span className="vc-story home-touch-title">{label} touched</span>
      <span className="pv-meta"><span>{visit.role_label}</span> · <span>{visit.role_basis}</span></span>
      <span className="vc-reason">{visit.reason}</span>
    </span>
    <ChevronRight className="vc-chevron" aria-hidden="true"/>
  </button>;
}
