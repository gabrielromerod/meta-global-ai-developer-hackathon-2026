import type {UIState, VisitRow, VisitEvent} from '../../contracts';

export function attentionVisits(state: UIState, limit = 5): VisitRow[] {
  const visits = new Map(state.visits.map(visit => [visit.id, visit]));
  return [...new Set(state.attention_ids)]
    .map(id => visits.get(id))
    .filter((visit): visit is VisitRow => visit !== undefined)
    .slice(0, limit);
}

export function summaryText(summary: UIState['summary']): string {
  const stages: string[] = [];
  if (summary.camera_events !== null) stages.push(`${summary.camera_events} camera events`);
  if (summary.on_property !== null) stages.push(`${summary.on_property} on the property`);
  stages.push(`${summary.visits} ${summary.visits === 1 ? 'visit' : 'visits'}`);
  stages.push(`${summary.needs_attention} needs attention`);
  return stages.join(' → ');
}

export function viewCameras(state: UIState, viewId: string): UIState['cameras'] {
  const view = state.views.find(item => item.id === viewId);
  return view ? state.cameras.filter(camera => view.camera_ids.includes(camera.id)) : [];
}

export interface TouchEvidence { visit: VisitRow; event: VisitEvent }
export interface TouchComparison { label: string; household: TouchEvidence; external: TouchEvidence }

// Select existing evidence for explanation. This never infers a role or computes a verdict.
export function touchComparison(state: UIState): TouchComparison | null {
  const visits = new Map(state.visits.map(visit => [visit.id, visit]));
  const touches = state.events.filter(event => event.type === 'touch' && event.target);
  for (const event of touches) {
    const visit = visits.get(event.visit_id);
    if (!visit || event.actor_role !== 'household_insider' || visit.verdict !== 'normal') continue;
    const externalEvent = touches.find(other => {
      const otherVisit = visits.get(other.visit_id);
      return other.target === event.target && other.actor_role === 'external_visitor'
        && otherVisit?.verdict === 'needs_attention';
    });
    const externalVisit = externalEvent && visits.get(externalEvent.visit_id);
    if (!externalEvent || !externalVisit) continue;
    const object = state.protected_objects.find(item => item.id === event.target);
    const label = typeof object?.label === 'string' ? object.label : 'Protected object';
    return {label, household: {visit, event}, external: {visit: externalVisit, event: externalEvent}};
  }
  return null;
}
