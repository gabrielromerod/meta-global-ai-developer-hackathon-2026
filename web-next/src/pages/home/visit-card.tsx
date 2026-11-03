import {Camera, ChevronRight, EyeOff} from 'lucide-react';
import type {Camera as CameraType, VisitRow} from '../../contracts';
import {Chip, VerdictBadge} from '../../components/ui';

export function VisitCard({visit,cameras,onOpen}: {visit:VisitRow;cameras:CameraType[];onOpen:(id:string)=>void}) {
  const cameraNames = visit.cameras.map(id => cameras.find(camera=>camera.id===id)?.name ?? id);
  return <button type="button" className="home-visit-card" data-verdict={visit.verdict}
    aria-label={`Open visit ${visit.title}`} onClick={()=>onOpen(visit.id)}>
    <span className="home-visit-meta"><VerdictBadge verdict={visit.verdict}/><time>{visit.clock}</time></span>
    <span className="home-visit-story">{visit.first_sentence || visit.story}</span>
    <span className="home-visit-footer"><Chip>{visit.role_label}</Chip><ChevronRight aria-hidden="true"/></span>
    {visit.gaps.map((gap,index)=><span className="home-visit-gap" key={`${gap}-${index}`}><EyeOff aria-hidden="true"/>{gap}</span>)}
    <span className="home-visit-cameras"><Camera aria-hidden="true"/>{cameraNames.join(' · ') || 'Camera not recorded'}</span>
  </button>;
}
