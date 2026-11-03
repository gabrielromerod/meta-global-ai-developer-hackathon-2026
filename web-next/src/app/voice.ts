/** Existing FR-022 encoding migrated to TypeScript. Phone speech stays in RAM. */
export const TARGET_RATE=16000,MAX_SECONDS=30;
export function downsample(samples:Float32Array,inRate:number,outRate=TARGET_RATE){
  if(inRate===outRate)return Float32Array.from(samples);
  if(inRate<outRate)throw new Error('Microphone sample rate is below 16 kHz.');
  const ratio=inRate/outRate,out=new Float32Array(Math.floor(samples.length/ratio));
  for(let i=0;i<out.length;i++){const start=Math.floor(i*ratio),end=Math.min(samples.length,Math.floor((i+1)*ratio));let sum=0;for(let j=start;j<end;j++)sum+=samples[j];out[i]=end>start?sum/(end-start):samples[start]||0;}return out;
}
export function encodeWav(samples:Float32Array,sampleRate=TARGET_RATE){
  const buffer=new ArrayBuffer(44+samples.length*2),view=new DataView(buffer);
  const tag=(offset:number,text:string)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
  tag(0,'RIFF');view.setUint32(4,36+samples.length*2,true);tag(8,'WAVE');tag(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,sampleRate,true);view.setUint32(28,sampleRate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);tag(36,'data');view.setUint32(40,samples.length*2,true);
  for(let i=0;i<samples.length;i++){const sample=Math.max(-1,Math.min(1,samples[i]));view.setInt16(44+i*2,sample<0?sample*0x8000:sample*0x7fff,true);}return buffer;
}
export function toWav(chunks:Float32Array[],inRate:number,maxSeconds=MAX_SECONDS){
  const total=Math.min(chunks.reduce((sum,c)=>sum+c.length,0),Math.ceil(inRate*maxSeconds));const all=new Float32Array(total);let offset=0;for(const chunk of chunks){const keep=chunk.subarray(0,total-offset);all.set(keep,offset);offset+=keep.length;if(offset===total)break;}
  const pcm=downsample(all,inRate);return {blob:new Blob([encodeWav(pcm)],{type:'audio/wav'}),seconds:pcm.length/TARGET_RATE};
}
export class Recorder{
  stream:MediaStream|null=null;context:AudioContext|null=null;source:MediaStreamAudioSourceNode|null=null;processor:ScriptProcessorNode|null=null;
  chunks:Float32Array[]=[];length=0;recording=false;disposed=false;
  constructor(readonly onTick:(seconds:number)=>void=()=>{},readonly onLimit:()=>void=()=>{}){}
  static supported(){return typeof navigator.mediaDevices?.getUserMedia==='function'&&typeof window.AudioContext==='function';}
  async start(){
    if(this.disposed)throw new Error('Recording was cancelled.');
    try {
    this.stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});
    if(this.disposed)throw new Error('Recording was cancelled.');
    this.context=new AudioContext();this.source=this.context.createMediaStreamSource(this.stream);this.processor=this.context.createScriptProcessor(4096,1,1);this.recording=true;
    this.processor.onaudioprocess=event=>{if(!this.recording)return;const data=event.inputBuffer.getChannelData(0);const left=Math.max(0,Math.ceil(this.context!.sampleRate*MAX_SECONDS)-this.length);const chunk=new Float32Array(data.subarray(0,left));this.chunks.push(chunk);this.length+=chunk.length;const seconds=this.length/this.context!.sampleRate;this.onTick(seconds);if(seconds>=MAX_SECONDS)this.onLimit();};
    this.source.connect(this.processor);this.processor.connect(this.context.destination);
    } catch(error) {await this.stop().catch(()=>{});throw error;}
  }
  async stop(){
    const active=this.recording,context=this.context,stream=this.stream,source=this.source,processor=this.processor,chunks=this.chunks;
    this.recording=false;this.context=null;this.stream=null;this.source=null;this.processor=null;this.chunks=[];this.length=0;
    if(processor)processor.onaudioprocess=null;
    try{source?.disconnect();}catch{/* An unconnected node is already released. */}
    try{processor?.disconnect();}catch{/* Still release the stream after a partial setup. */}
    stream?.getTracks().forEach(track=>track.stop());
    try{return active&&context?toWav(chunks,context.sampleRate):null;}
    finally{if(context&&context.state!=='closed')await context.close().catch(()=>{});}
  }
  dispose(){this.disposed=true;void this.stop().catch(()=>{});}
}
