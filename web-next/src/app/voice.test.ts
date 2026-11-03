import {afterEach,describe,it,expect,vi} from 'vitest';
import {Recorder,toWav} from './voice';
afterEach(()=>vi.unstubAllGlobals());
describe('FR-022 phone-only PCM encoding',()=>{
  it('encodes 48 kHz float chunks as 16 kHz mono PCM16 and bounds memory output',async()=>{
    const result=toWav([new Float32Array(48000)],48000);
    const view=new DataView(await result.blob.arrayBuffer());
    expect(view.getUint16(20,true)).toBe(1);expect(view.getUint16(22,true)).toBe(1);
    expect(view.getUint32(24,true)).toBe(16000);expect(view.getUint16(34,true)).toBe(16);
    expect(result.seconds).toBe(1);expect(result.blob.size).toBe(32044);
    expect(toWav([new Float32Array(48000*31)],48000).seconds).toBe(30);
  });
});
it('releases an acquired microphone if AudioContext setup fails',async()=>{
  const stop=vi.fn();vi.stubGlobal('navigator',{mediaDevices:{getUserMedia:vi.fn(async()=>({getTracks:()=>[{stop}]}))}});
  vi.stubGlobal('AudioContext',class{constructor(){throw new Error('Fixture audio setup failure');}});
  const recorder=new Recorder();
  await expect(recorder.start()).rejects.toThrow('Fixture audio setup failure');
  expect(stop).toHaveBeenCalledOnce();
  recorder.dispose();expect(stop).toHaveBeenCalledOnce();
});
it('releases a microphone that arrives after a cancelled permission request',async()=>{
  const stop=vi.fn();let grant!:(stream:unknown)=>void;
  vi.stubGlobal('navigator',{mediaDevices:{getUserMedia:vi.fn(()=>new Promise(resolve=>{grant=resolve;}))}});
  const recorder=new Recorder();const pending=recorder.start();recorder.dispose();grant({getTracks:()=>[{stop}]});
  await expect(pending).rejects.toThrow('cancelled');expect(stop).toHaveBeenCalledOnce();
});
