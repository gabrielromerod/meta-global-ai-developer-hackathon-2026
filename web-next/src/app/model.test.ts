import {describe,it,expect} from 'vitest';
import {cameraTime,frameAt,localThreads,readableError,recordedClock} from './model';

describe('shared evidence clock',()=>{
  it('preserves the recorded ISO offset instead of using the viewer timezone',()=>{
    expect(recordedClock('2026-11-02T14:00:00-08:00',15245)).toEqual({text:'6:14:05 PM',date:'Nov 2, 2026',zone:'UTC-08:00'});
    expect(recordedClock('2026-11-03T18:00:00+05:30',0).text).toBe('6:00:00 PM');
    expect(recordedClock('2026-11-03T18:00:00Z',0).zone).toBe('UTC');
    expect(recordedClock('not a recorded timestamp',5).zone).toBe('Timezone unavailable');
  });
  it('maps absolute evidence time to each real video without fabricating media',()=>{
    expect(cameraTime(105,100,20)).toBe(5);
    expect(cameraTime(95,100,20)).toBe(0);
    expect(cameraTime(140,100,20)).toBe(20);
  });
  it('never draws a stale SAM observation or interpolates over a recording hole',()=>{
    const frames=[{t:1,box:[1,2,3,4],outline:[]},{t:8,box:[9,8,7,6],outline:[]}];
    expect(frameAt(frames,4)).toBeNull();
    expect(frameAt(frames,8)?.box).toEqual([9,8,7,6]);
    expect(frameAt(frames,0)).toBeNull();
  });
});
describe('local-only household data',()=>{
  it('accepts only local messages for known threads and ignores malformed storage',()=>{
    expect(localThreads('not json')).toEqual({});
    expect(localThreads(JSON.stringify({household:[{id:'1',author:'you',text:'Gate',citations:[],clip_id:null}],unknown:[{text:'noise'}]}))).toEqual({household:[{id:'1',author:'you',text:'Gate',citations:[],clip_id:null}]});
    expect(localThreads(JSON.stringify({household:[{id:'1',author:'household',text:'Invented incoming person'}]}))).toEqual({});
  });
  it('gives an honest error when the service is unreachable',()=>expect(readableError(new TypeError('Failed to fetch'))).toContain('could not be reached'));
});
