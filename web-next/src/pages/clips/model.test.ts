import {describe, expect, it} from 'vitest';
import fixture from '../../fixtures/state.json';
import type {UIState} from '../../contracts';
import {EMPTY_FILTERS, filterEvidence, toSearchParams} from './model';

const state = fixture as unknown as UIState;
describe('Clip and media filters over supplied evidence (FR-017)', () => {
  it('intersects text, camera, verdict and kind without changing the evidence', () => {
    const result = filterEvidence(state, {...EMPTY_FILTERS,q:'gate',camera:'doorbell',verdict:'needs_attention',kind:'person'});
    expect(result.error).toBeNull();
    expect(result.clips.map(clip=>clip.visit_id)).toEqual(['v_c']);
    expect(result.clips[0]).toBe(state.clips.find(clip=>clip.visit_id==='v_c'));
  });
  it('finds visit story text as well as the clip title', () => {
    const source = {...state,visits:state.visits.map(visit=>visit.id==='v_c'?{...visit,story:'A supplied observation with a distinct search phrase.'}:visit)};
    expect(filterEvidence(source,{...EMPTY_FILTERS,q:'distinct search phrase'}).clips.map(clip=>clip.visit_id)).toEqual(['v_c']);
  });
  it('keeps measured timestamps and includes exact filter boundaries', () => {
    const clip=state.clips[0];
    const start=new Date(Date.parse(state.session.start)+clip.t0*1000).toISOString();
    const result=filterEvidence(state,{...EMPTY_FILTERS,start,end:start});
    expect(result.clips.map(item=>item.id)).toEqual([clip.id]);
    expect(result.clips[0].t0).toBe(clip.t0);
  });
  it('sorts by the supplied recording time, newest first', () => {
    const result=filterEvidence(state,EMPTY_FILTERS);
    expect(result.clips.map(clip=>clip.t0)).toEqual([...state.clips].sort((a,b)=>b.t0-a.t0).map(clip=>clip.t0));
  });
  it('returns an honest empty result for an unavailable camera or category', () => {
    expect(filterEvidence(state,{...EMPTY_FILTERS,camera:'side_left'}).clips).toEqual([]);
    expect(filterEvidence(state,{...EMPTY_FILTERS,kind:'vehicle'}).clips).toEqual([]);
  });
  it('rejects reversed or invalid dates instead of silently widening a search', () => {
    expect(filterEvidence(state,{...EMPTY_FILTERS,start:'2026-11-03T19:00:00Z',end:'2026-11-03T18:00:00Z'}).error).toMatch(/end.*after/i);
    expect(filterEvidence(state,{...EMPTY_FILTERS,start:'not-a-date'}).error).toMatch(/valid/i);
  });
  it('cannot apply dates when the recording date is unavailable', () => {
    const unknown={...state,session:{...state.session,start:''}};
    expect(filterEvidence(unknown,{...EMPTY_FILTERS,start:'2026-11-03T18:00:00Z'}).error).toMatch(/recording date.*unavailable/i);
  });
  it('preserves absent video and thumbnails as unavailable', () => {
    expect(filterEvidence(state,EMPTY_FILTERS).clips.every(clip=>clip.clip_url===null && clip.thumbnail_url===null)).toBe(true);
  });
  it('submits timezone-aware ISO values while preserving all filter intersections', () => {
    const result=toSearchParams({...EMPTY_FILTERS,q:'gate',camera:'side_left',verdict:'needs_attention',kind:'person',start:'2026-11-03T18:00:00-08:00',end:'2026-11-03T19:00:00-08:00'});
    expect(result.error).toBeNull();
    expect(result.params).toEqual({q:'gate',camera:'side_left',verdict:'needs_attention',kind:'person',start:'2026-11-04T02:00:00.000Z',end:'2026-11-04T03:00:00.000Z'});
  });
});
