import {useEffect,useRef,useState} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {ArrowLeft,Link2,Pause,Play,Share2,VideoOff} from 'lucide-react';
import type {UIState,VisitEvent} from '../contracts';
import {Button,Card,Chip,EmptyState,VerdictBadge} from '../components/ui';
import {HouseView} from '../twin';
import {api,type PlaybackCamera,type VisitDetail} from './api';
import {cameraTime,frameAt,readableError,recordedClock} from './model';

export function VisitReview({id,state,twin,initialClipId,onBack,onShare,onSnapshotReady,initialEventId,selectionKey}:{initialEventId?:string|null;selectionKey?:string;id:string;state:UIState;twin:Record<string,unknown>|null;initialClipId:string|null;onBack:()=>void;onShare:(clip:string)=>void;onSnapshotReady:(capture:(()=>Promise<Blob>)|null)=>void}){
  const queries=useQueryClient();
  const query=useQuery({queryKey:['visit',id],queryFn:()=>api<VisitDetail>('/api/ui/visits/'+encodeURIComponent(id))});
  const positions=useQuery({queryKey:['positions',id],queryFn:()=>api<Record<string,unknown>>('/api/ui/visits/'+encodeURIComponent(id)+'/positions')});
  const [time,setTime]=useState(0),[playing,setPlaying]=useState(false),[active,setActive]=useState<string|null>(null),[notice,setNotice]=useState<string|null>(null);
  const videos=useRef(new Map<string,HTMLVideoElement>());
  const [decoded,setDecoded]=useState(0);
  const detail=query.data;
  const clock=recordedClock(state.session.start,time);
  useEffect(()=>{
    const video=active?videos.current.get(active):null;
    if(!video||video.readyState<2){onSnapshotReady(null);return;}
    onSnapshotReady(()=>new Promise<Blob>((resolve,reject)=>{const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;const context=canvas.getContext('2d');if(!context){reject(new Error('Snapshots are unavailable in this browser.'));return;}context.drawImage(video,0,0);canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('Snapshot could not be encoded.')),'image/png');}));
    return()=>onSnapshotReady(null);
  },[active,decoded,id,onSnapshotReady]);
  useEffect(()=>{setPlaying(false);setNotice(null);if(detail){const event=detail.events.find(e=>e.event_id===initialEventId);setTime(event?.t??detail.t0);const clip=state.clips.find(c=>c.id===initialClipId&&c.visit_id===id);setActive(event?.camera_id??clip?.camera_id??detail.events[0]?.camera_id??detail.playback_cameras[0]?.id??null);}},[id,detail?.id,initialClipId,initialEventId,selectionKey]);
  useEffect(()=>{
    if(!detail)return;
    for(const camera of detail.playback_cameras){const video=videos.current.get(camera.id);if(!video)continue;const target=cameraTime(time,camera.clip_t0,video.duration);if(Number.isFinite(target)&&Math.abs(video.currentTime-target)>.15)video.currentTime=target;}
  },[time,detail]);
  useEffect(()=>{
    if(!detail)return;
    for(const video of videos.current.values()){
      if(playing&&video.paused)void video.play().catch((error:unknown)=>{if(error instanceof DOMException&&error.name==='AbortError')return;setPlaying(false);setNotice('Playback could not start. Use the video controls to try again.');});
      if(!playing&&!video.paused)video.pause();
    }
  },[playing,detail]);
  useEffect(()=>{
    if(!playing||!detail)return;let frame:number,last=performance.now();
    function tick(now:number){const delta=Math.min((now-last)/1000,.25);last=now;
      const media=detail!.playback_cameras.filter(c=>c.clip_url);
      const source=media.find(c=>c.id===active)??media[0],video=source?videos.current.get(source.id):null;
      setTime(previous=>{const next=Math.min(detail!.playback_t1,video&&video.readyState>=2?video.currentTime+source!.clip_t0:media.length?previous:previous+delta);if(next>=detail!.playback_t1)setPlaying(false);return next;});frame=requestAnimationFrame(tick);}
    frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame);
  },[playing,detail,active]);
  const feedback=useMutation({mutationFn:(kind:string)=>api<{note:string}>('/api/visits/'+encodeURIComponent(id)+'/feedback',{kind}),onSuccess:result=>setNotice(result.note)});
  const rebuild=useMutation({mutationFn:async()=>{
    const job=await api<{job_id:string}>('/api/visits/'+encodeURIComponent(id)+'/rerun',{stage:'story',live:false});
    for(let attempt=0;attempt<60;attempt++){
      const result=await api<{state:string;status?:string;result?:{notice?:string};error?:string}>('/api/jobs/'+encodeURIComponent(job.job_id));
      if(result.state==='done'||result.status==='done')return result.result?.notice??'Recorded story shown. No model request was made.';
      if(result.state==='failed'||result.status==='failed')throw new Error(result.error||'Story rebuild failed. The current story remains available.');
      await new Promise(resolve=>setTimeout(resolve,250));
    }throw new Error('The rebuild is still pending. The current story remains available.');
  },onSuccess:message=>{setNotice(message);void queries.invalidateQueries({queryKey:['visit',id]});}});
  function seek(event:VisitEvent){setTime(event.t);setActive(event.camera_id);}
  if(query.isPending)return <EmptyState title="Loading visit evidence"/>;
  if(query.isError)return <div className="app-start"><p role="alert">{readableError(query.error)}</p><Button onClick={()=>void query.refetch()}>Try again</Button><Button variant="ghost" onClick={onBack}>Back to Attention</Button></div>;
  if(!detail)return null;
  const clip=state.clips.find(c=>c.visit_id===id&&c.camera_id===active);
  return <div className="visit-workspace" data-testid="visit-card" data-visit={id}>
    <header className="visit-heading"><Button size="icon" variant="ghost" aria-label="Back to Attention" onClick={onBack}><ArrowLeft/></Button><div><VerdictBadge verdict={detail.verdict} label={detail.verdict_label}/><h2>{detail.scenario_title||'Recorded visit'}</h2><p className="visit-first">{detail.first_sentence}</p></div><Button variant="outline" disabled={!clip} onClick={()=>clip&&onShare(clip.id)}><Share2/>Share clip</Button></header>
    <div className="visit-columns"><div className="visit-visuals">
      <Card title="Observed route" className="visit-house">{twin?<HouseView forceMap={new URLSearchParams(window.location.search).get('twin')==='2d'} twin={twin} positions={positions.data} time={time} activeCameraId={active} onCameraSelect={setActive}/>:<EmptyState title="House view unavailable"/>}</Card>
      <Card title="Camera evidence" className="visit-player-card">
        <div className="visit-clock"><Button size="icon" aria-label={playing?'Pause evidence timeline':'Play evidence timeline'} onClick={()=>{if(time>=detail.playback_t1)setTime(detail.playback_t0);setPlaying(p=>!p);}}>{playing?<Pause/>:<Play/>}</Button><label className="v-sr-only" htmlFor="evidence-clock">Evidence time</label><input id="evidence-clock" type="range" aria-valuetext={`${clock.text} ${clock.zone}`} min={detail.playback_t0} max={detail.playback_t1} step="0.01" value={time} onChange={event=>setTime(Number(event.target.value))}/><output className="visit-recorded-clock" aria-label="Recorded time" aria-live="off"><span>{clock.text}</span><small>{clock.date} · {clock.zone}</small></output></div>
        <div className="visit-camera-grid">{detail.playback_cameras.map(camera=><CameraPlayer key={camera.id} camera={camera} detail={detail} time={time} active={active===camera.id} setVideo={video=>{if(video)videos.current.set(camera.id,video);else videos.current.delete(camera.id);}} onSeek={setTime} onPlaybackChange={(playing,absolute)=>{setTime(absolute);setPlaying(playing);}} onDecoded={()=>setDecoded(n=>n+1)} onSelect={()=>setActive(camera.id)} onError={()=>setNotice(`${camera.name}: the exported video could not be decoded.`)}/>)}</div>
      </Card>
    </div><div className="visit-story-scroll" tabIndex={0} aria-label="Visit story and evidence">
      <Card title="What happened"><div className="visit-story" data-testid="story">{detail.sentences.map(sentence=><article className="visit-sentence" key={sentence.index} data-source={sentence.source}><p>{sentence.text}</p><div className="visit-citations">{sentence.citations.map(citation=><Button variant="outline" key={citation.event_id} className="visit-citation" onClick={()=>seek(citation)} aria-label={`Show evidence ${citation.event_id}`}><Link2/>{citation.clock} · {citation.camera_name}</Button>)}</div><small className="visit-source">{detail.evidence.kind==='fixture'?'Demo data · ':''}{sentence.badge.label}</small></article>)}</div></Card>
      <Card title="Context from code"><div className="visit-context">{detail.subjects.map(subject=><p key={subject.id}><strong>{subject.role_label}</strong>: {subject.basis_label} <small>({subject.role_basis})</small></p>)}{detail.rule_hits.map(hit=><p key={hit.event_id}>Rule {hit.rule_id} fired: {hit.rule_name}.</p>)}{detail.trace.rules_excluded.map((rule,index)=><p key={index}>{rule.reason}</p>)}{detail.expected_windows.map(window=><p key={window.id}>Recorded expected window {window.id} “{window.label}”.</p>)}{detail.watches.filter(w=>w.notice).map(w=><p key={w.id}>{w.notice}</p>)}{detail.gaps.map(gap=><p key={gap.id}>{gap.label}. No position is inferred inside the gap.</p>)}</div></Card>
      <Card title="Evidence timeline"><ol className="visit-event-list">{detail.events.map(event=><li key={event.event_id}><Button variant="ghost" onClick={()=>seek(event)}>{event.clock} · {event.camera_name}: {event.type.replaceAll('_',' ')}{event.target?' · '+event.target.replaceAll('_',' '):''}</Button></li>)}</ol></Card>
      <Card><details className="visit-trace"><summary>How this was decided</summary><p>{detail.trace.triage?.forced?'Escalation forced by code. ':''}{detail.trace.triage?.reason}</p>{detail.trace.drafts.map(draft=><article key={draft.attempt}><h3>Draft {draft.attempt}: {draft.passed?'accepted':'rejected by the validator'}</h3>{draft.failures?.map((failure,index)=><p key={index}>{failure.detail}</p>)}</article>)}<p>Code verdict floor: {String(detail.trace.verdict_inputs.floor??'unavailable')}. Model proposal: {String(detail.trace.verdict_inputs.proposal??'unavailable')}.</p><p>{detail.telemetry.totals.count} {detail.evidence.kind==='fixture'?'authored demo':'recorded'} model calls · ${detail.telemetry.totals.cost_usd.toFixed(4)} ledger total.</p><p>{detail.evidence.kind==='fixture'?'These values are fixture telemetry, not a measured benchmark.':'Values come from the recorded call ledger.'}</p><Button variant="outline" disabled={rebuild.isPending} onClick={()=>rebuild.mutate()}>Rebuild story from cache</Button></details></Card>
      <Card title="Feedback"><p>Feedback never changes a recorded verdict.</p><div className="visit-feedback"><Button variant="outline" disabled={feedback.isPending} onClick={()=>feedback.mutate('expected')}>This was expected</Button></div></Card>
      {(notice||feedback.isError||rebuild.isError||positions.isError)&&<p className="app-notice" role={feedback.isError||rebuild.isError||positions.isError?'alert':'status'}>{feedback.isError?readableError(feedback.error):rebuild.isError?readableError(rebuild.error):positions.isError?readableError(positions.error):notice}</p>}
    </div></div>
  </div>;
}
function CameraPlayer({camera,detail,time,active,setVideo,onSeek,onSelect,onError,onDecoded,onPlaybackChange}:{camera:PlaybackCamera;detail:VisitDetail;time:number;active:boolean;setVideo:(video:HTMLVideoElement|null)=>void;onSeek:(time:number)=>void;onSelect:()=>void;onError:()=>void;onDecoded:()=>void;onPlaybackChange:(playing:boolean,absolute:number)=>void}){
  const canvas=useRef<HTMLCanvasElement>(null);
  useEffect(()=>{const element=canvas.current,context=element?.getContext('2d');if(!element||!context)return;context.clearRect(0,0,element.width,element.height);const css=getComputedStyle(document.documentElement);context.strokeStyle=css.getPropertyValue('--v-accent').trim();context.lineWidth=parseFloat(css.getPropertyValue('--v-focus-width'));for(const track of Object.values(detail.overlays[camera.id]??{})){const frame=frameAt(track.frames,time);if(!frame)continue;const [x1,y1,x2,y2]=frame.box;context.strokeRect(x1,y1,x2-x1,y2-y1);if(frame.outline.length){context.beginPath();frame.outline.forEach(([x,y],index)=>index?context.lineTo(x,y):context.moveTo(x,y));context.closePath();context.stroke();}}},[detail,time,camera.id]);
  return <article className={`visit-camera${active?' is-active':''}`} aria-label={`${camera.name} evidence`}><Button className="visit-camera-select" variant="ghost" onClick={onSelect} aria-pressed={active}>{camera.name}</Button>{camera.clip_url?<div className="visit-video"><video className="player-media" ref={setVideo} src={camera.clip_url} controls muted playsInline preload="metadata" onFocus={onSelect} onClick={onSelect} onPlay={event=>onPlaybackChange(true,event.currentTarget.currentTime+camera.clip_t0)} onPause={event=>onPlaybackChange(false,event.currentTarget.currentTime+camera.clip_t0)} onLoadedData={onDecoded} onCanPlay={onDecoded} onLoadedMetadata={event=>{event.currentTarget.currentTime=cameraTime(time,camera.clip_t0,event.currentTarget.duration);}} onSeeked={event=>{onDecoded();const abs=event.currentTarget.currentTime+camera.clip_t0;if(Math.abs(abs-time)>.2)onSeek(abs);}} onError={onError}/><canvas ref={canvas} className="overlay" width={camera.width} height={camera.height} aria-label="Observed SAM track overlays"/></div>:<div className="visit-media-empty"><VideoOff aria-hidden="true"/><p>Media unavailable</p><small>{camera.source_label} · no exported clip</small></div>}</article>;
}
