import {describe, expect, it} from 'vitest';
import fixture from '../../fixtures/state.json';
import type {UIState} from '../../contracts';
import {attentionVisits, touchComparison, summaryText, viewCameras} from './model';

const state = fixture as unknown as UIState;

describe('Home evidence selection (FR-017, FR-044)', () => {
  it('preserves the code-ranked attention order without adding unknown visits', () => {
    expect(attentionVisits({...state, attention_ids:['missing', 'v_c', 'v_ap']} ).map(v=>v.id)).toEqual(['v_c','v_ap']);
  });
  it('caps the attention preview at five visits and removes duplicate IDs', () => {
    expect(attentionVisits({...state,attention_ids:['v_c','v_c','v_ap','v_b','v_bp','v_a']}).map(v=>v.id)).toEqual(['v_c','v_ap','v_b','v_bp','v_a']);
  });
  it('shows the same protected-object touch with its supplied household and outsider verdicts', () => {
    const pair = touchComparison(state);
    expect(pair?.label).toBe('side gate');
    expect(pair?.household.visit.id).toBe('v_ap');
    expect(pair?.household.visit.verdict).toBe('normal');
    expect(pair?.household.event.clock).toBe('6:02:28 PM');
    expect(pair?.external.visit.id).toBe('v_c');
    expect(pair?.external.visit.verdict).toBe('needs_attention');
    expect(pair?.external.event.clock).toBe('6:14:05 PM');
  });
  it('never manufactures a comparison if only one side has recorded evidence', () => {
    expect(touchComparison({...state,events:state.events.filter(e=>e.visit_id !== 'v_c')})).toBeNull();
    expect(touchComparison({...state,visits:[]})).toBeNull();
  });
  it('does not turn unknown camera or street counts into measured zero', () => {
    const result = summaryText(state.summary);
    expect(result).toContain('5 visits');
    expect(result).toContain('1 needs attention');
    expect(result).not.toContain('0');
    expect(result).not.toContain('camera events');
    expect(result).not.toContain('street');
  });
  it('renders measured prefilter totals in order, including a genuinely measured zero', () => {
    expect(summaryText({...state.summary,camera_events:142,on_property:9,visits:3,needs_attention:0})).toBe('142 camera events → 9 on the property → 3 visits → 0 needs attention');
  });
  it('selects cameras from the configured view rather than guessing a route', () => {
    expect(viewCameras(state,'left_passage').map(c=>c.id)).toEqual(['side_left']);
    expect(viewCameras(state,'missing')).toEqual([]);
  });
});
