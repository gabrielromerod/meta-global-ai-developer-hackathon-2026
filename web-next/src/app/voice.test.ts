import {describe,it,expect} from 'vitest';
import {toWav} from './voice';
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
