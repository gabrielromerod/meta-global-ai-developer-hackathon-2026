import {useEffect,useRef,useState} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {ArrowLeft,BellOff,CalendarClock,ChevronDown,EyeOff,Eye,Footprints,Link2,Pause,Play,Share2,ShieldAlert,ShieldCheck,VideoOff} from 'lucide-react';
import type {UIState,VisitEvent} from '../contracts';
import {Button,EmptyState,VerdictBadge} from '../components/ui';
import {HouseView} from '../twin';
import {RouteReplay} from './route-replay';
import {api,type PlaybackCamera,type VisitDetail} from './api';
import {cameraTime,frameAt,readableError,recordedClock} from './model';
import './visit.css';

export function VisitReview({id,state,twin,initialClipId,onBack,onShare,onSnapshotReady,initialEventId,selectionKey}:{initialEventId?:string|null;selectionKey?:string;id:string;state:UIState;twin:Record<string,unknown>|null;initialClipId:string|null;onBack:()=>void;onShare:(clip:string)=>void;onSnapshotReady:(capture:(()=>Promise<Blob>)|null)=>void}){
  const queries=useQueryClient();
  const query=useQuery({queryKey:['visit',id],queryFn:()=>api<VisitDetail>('/api/ui/visits/'+encodeURIComponent(id))});
  const positions=useQuery({queryKey:['positions',id],queryFn:()=>api<Record<string,unknown>>('/api/ui/visits/'+encodeURIComponent(id)+'/positions')});
  const [time,setTime]=useState(0),[playing,setPlaying]=useState(false),[active,setActive]=useState<string|null>(null),[notice,setNotice]=useState<string|null>(null);
  const videos=useRef(new Map<string,HTMLVideoElement>());
  const visuals=useRef<HTMLDivElement>(null);
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
  // A visit always opens on its proof: the camera tile and timeline at the top of the evidence column.
  useEffect(()=>{if(!detail)return;let frame=requestAnimationFrame(()=>{frame=requestAnimationFrame(()=>{if(visuals.current)visuals.current.scrollTop=0;});});return()=>cancelAnimationFrame(frame);},[id,detail?.id]);
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
  const undo=useMutation({mutationFn:(watch:string)=>api<{watch:{status:string}}>('/api/watches/'+encodeURIComponent(watch)+'/undo',{}),onSuccess:()=>{setNotice('Stopped watching. The recorded visit is unchanged.');void queries.invalidateQueries({queryKey:['visit',id]});},onError:error=>setNotice(readableError(error))});
  function seek(event:VisitEvent){setTime(event.t);setActive(event.camera_id);}
  if(query.isPending)return <EmptyState title="Loading visit evidence"/>;
  if(query.isError)return <div className="app-start"><p role="alert">{readableError(query.error)}</p><Button onClick={()=>void query.refetch()}>Try again</Button><Button variant="ghost" onClick={onBack}>Back to Attention</Button></div>;
  if(!detail)return null;
  const clip=state.clips.find(c=>c.visit_id===id&&c.camera_id===active);
  const t0=detail.playback_t0,span=Math.max(detail.playback_t1-t0,1);
  const pct=(t:number)=>`${Math.min(100,Math.max(0,(t-t0)/span*100))}%`;
  const ordered=[...detail.events].sort((a,b)=>a.t-b.t);
  const current=[...ordered].reverse().find(event=>event.t<=time+.05)??null;
  const currentSentence=current?detail.sentences.find(sentence=>sentence.citations.some(c=>c.event_id===current.event_id))?.index??null:null;
  const activeGap=detail.gaps.find(gap=>time>=gap.t0&&time<=gap.t1)??null;
  const forceMap=new URLSearchParams(window.location.search).get('twin')==='2d';
  const houseView=twin?<HouseView forceMap={forceMap} twin={twin} positions={positions.data} time={time} activeCameraId={active} onCameraSelect={setActive}/>:null;
  const why=detail.rule_hits.length+detail.subjects.length+detail.trace.rules_excluded.length+detail.expected_windows.length+detail.watches.filter(w=>w.notice).length+detail.gaps.length;
  return <div className="visit-workspace" data-testid="visit-card" data-visit={id}>
    <header className="visit-heading">
      <Button size="icon" variant="ghost" aria-label="Back to Attention" onClick={onBack}><ArrowLeft/></Button>
      <div className="visit-title"><VerdictBadge verdict={detail.verdict} label={detail.verdict_label}/><h2>{detail.scenario_title||'Recorded visit'}</h2><p className="visit-first">{detail.first_sentence}</p></div>
      <Button variant="outline" disabled={!clip} onClick={()=>clip&&onShare(clip.id)}><Share2/>Share clip</Button>
    </header>
    <div className="visit-columns">
      <div className="visit-visuals" ref={visuals}>
        <section className="visit-player-card" aria-label="Camera evidence">
          <div className="visit-camera-grid">{detail.playback_cameras.map(camera=><CameraPlayer key={camera.id} camera={camera} detail={detail} time={time} active={active===camera.id} setVideo={video=>{if(video)videos.current.set(camera.id,video);else videos.current.delete(camera.id);}} onSeek={setTime} onPlaybackChange={(playing,absolute)=>{setTime(absolute);setPlaying(playing);}} onDecoded={()=>setDecoded(n=>n+1)} onSelect={()=>setActive(camera.id)} onError={()=>setNotice(`${camera.name}: the exported video could not be decoded.`)}/>)}
            <section className="visit-replay-cell" aria-label="Observed route">{twin?(forceMap?houseView:<RouteReplay twin={twin} positions={positions.data} time={time} activeCameraId={active} playing={playing} fallback={houseView}/>):<EmptyState title="House view unavailable"/>}</section>
          </div>
          <div className="visit-clock">
            <Button size="icon" aria-label={playing?'Pause evidence timeline':'Play evidence timeline'} onClick={()=>{if(time>=detail.playback_t1)setTime(detail.playback_t0);setPlaying(p=>!p);}}>{playing?<Pause/>:<Play/>}</Button>
            <div className="visit-scrub">
              <div className="visit-marks" aria-hidden="true">
                {detail.gaps.map(gap=><span key={gap.id} className="visit-mark-gap" style={{left:pct(gap.t0),width:`calc(${pct(gap.t1)} - ${pct(gap.t0)})`}}/>)}
                {ordered.map(event=><span key={event.event_id} className={`visit-mark${current?.event_id===event.event_id?' is-current':''}${detail.rule_hits.some(h=>h.event_id===event.event_id)?' is-rule':''}`} style={{left:pct(event.t)}}/>)}
              </div>
              <label className="v-sr-only" htmlFor="evidence-clock">Evidence time</label>
              <input id="evidence-clock" type="range" aria-valuetext={`${clock.text} ${clock.zone}`} min={detail.playback_t0} max={detail.playback_t1} step="0.01" value={time} onChange={event=>setTime(Number(event.target.value))}/>
            </div>
            <output className="visit-recorded-clock" aria-label="Recorded time" aria-live="off"><span>{clock.text}</span><small>{clock.date} · {clock.zone}</small></output>
          </div>
          <p className="visit-now" aria-live="polite">{activeGap?<><EyeOff aria-hidden="true"/>{activeGap.label} · no camera saw this stretch</>:current?<><Eye aria-hidden="true"/>{current.clock} · {current.camera_name}: {words(current.type)}{current.target?' · '+words(current.target):''}</>:<>Press play or pick a moment in the story.</>}</p>
        </section>
      </div>
      <div className="visit-story-scroll" tabIndex={0} aria-label="Visit story and evidence">
        {why>0&&<section className="visit-block" aria-labelledby="visit-why-title"><h3 id="visit-why-title" className="visit-block-title">Why this verdict</h3>
          <ul className="pv-list visit-context">
            {detail.rule_hits.map(hit=><li className="pv-row" data-tone="danger" key={hit.event_id}><span className="pv-bubble" aria-hidden="true"><ShieldAlert/></span><div className="pv-row-body"><strong>Rule {hit.rule_id} fired: {hit.rule_name}.</strong><span className="pv-meta">{hit.applies_to?`Applies to ${words(hit.applies_to)}. `:''}Only an owner rule can make a visit need attention.</span></div></li>)}
            {detail.subjects.map(subject=><li className="pv-row" key={subject.id}><span className="pv-bubble" aria-hidden="true"><Footprints/></span><div className="pv-row-body"><strong>{subject.role_label}</strong><span className="pv-meta">{subject.basis_label} <code>({subject.role_basis})</code></span></div></li>)}
            {detail.trace.rules_excluded.map((rule,index)=><li className="pv-row" data-tone="success" key={index}><span className="pv-bubble" aria-hidden="true"><ShieldCheck/></span><div className="pv-row-body"><span>{rule.reason}</span></div></li>)}
            {detail.expected_windows.map(window=><li className="pv-row" key={window.id}><span className="pv-bubble" aria-hidden="true"><CalendarClock/></span><div className="pv-row-body"><span>Recorded expected window {window.id} “{window.label}”.</span></div></li>)}
            {detail.watches.filter(w=>w.notice).map(w=><li className="pv-row visit-watch" data-status={w.status} key={w.id}><span className="pv-bubble" aria-hidden="true"><Eye/></span><div className="pv-row-body"><strong>{w.notice}</strong>{w.origin_label&&<span className="pv-meta">Started by {w.origin_label}{w.status==='undone'?' · stopped by you':''}</span>}</div>{w.can_undo&&<Button variant="outline" size="sm" disabled={!state.owner.enabled||undo.isPending} title={state.owner.enabled?undefined:'Owner access is needed to stop a watch.'} onClick={()=>undo.mutate(w.id)}>Undo</Button>}</li>)}
            {detail.gaps.map(gap=><li className="pv-row" data-tone="unknown" key={gap.id}><span className="pv-bubble" aria-hidden="true"><EyeOff/></span><div className="pv-row-body"><strong>{gap.label}. No position is inferred inside the gap.</strong>{gap.clock_t0&&<span className="pv-meta">{gap.clock_t0} – {gap.clock_t1}{gap.region_name?` · ${gap.region_name}`:''}</span>}</div></li>)}
          </ul></section>}
        <section className="visit-block" aria-labelledby="visit-story-title"><h3 id="visit-story-title" className="visit-block-title">What happened</h3>
          <div className="visit-story" data-testid="story">{detail.sentences.map(sentence=><article className="visit-sentence" key={sentence.index} data-source={sentence.source} data-current={currentSentence===sentence.index||undefined}><p>{sentence.text}</p><div className="visit-citations">{sentence.citations.map(citation=><Button variant="outline" key={citation.event_id} className={`visit-citation${current?.event_id===citation.event_id?' is-current':''}`} onClick={()=>seek(citation)} aria-label={`Show evidence ${citation.event_id}`}><Link2/>{citation.clock} · {citation.camera_name}</Button>)}</div><small className="visit-source">{detail.evidence.kind==='fixture'?'Demo data · ':''}{sentence.badge.label}</small></article>)}</div>
        </section>
        <section className="visit-block" aria-labelledby="visit-events-title"><h3 id="visit-events-title" className="visit-block-title">Evidence timeline</h3>
          <ol className="pv-list visit-event-list">{ordered.map(event=><li key={event.event_id} data-current={current?.event_id===event.event_id||undefined}><button type="button" onClick={()=>seek(event)}><time>{event.clock}</time><span><strong>{words(event.type)}{event.target?' · '+words(event.target):''}</strong><small>{event.camera_name}</small></span>{detail.rule_hits.some(h=>h.event_id===event.event_id)&&<ShieldAlert className="visit-event-rule" aria-label="Rule fired here"/>}</button></li>)}</ol>
        </section>
        <section className="visit-block"><details className="visit-trace"><summary>How this was decided<ChevronDown aria-hidden="true"/></summary><p>{detail.trace.triage?.forced?'Escalation forced by code. ':''}{detail.trace.triage?.reason}</p>{detail.trace.drafts.map(draft=><article key={draft.attempt}><h3>Draft {draft.attempt}: {draft.passed?'accepted':'rejected by the validator'}</h3>{draft.failures?.map((failure,index)=><p key={index}>{failure.detail}</p>)}</article>)}<p>Code verdict floor: {String(detail.trace.verdict_inputs.floor??'unavailable')}. Model proposal: {String(detail.trace.verdict_inputs.proposal??'unavailable')}.</p><p>{detail.telemetry.totals.count} {detail.evidence.kind==='fixture'?'authored demo':'recorded'} model calls · ${detail.telemetry.totals.cost_usd.toFixed(4)} ledger total.</p><p>{detail.evidence.kind==='fixture'?'These values are fixture telemetry, not a measured benchmark.':'Values come from the recorded call ledger.'}</p><Button variant="outline" disabled={rebuild.isPending} onClick={()=>rebuild.mutate()}>Rebuild story from cache</Button></details></section>
        <section className="visit-block visit-feedback-row" aria-label="Feedback"><span className="pv-bubble" aria-hidden="true"><BellOff/></span><div className="pv-row-body"><strong>Was this expected?</strong><span className="pv-meta">Feedback never changes a recorded verdict.</span></div><div className="visit-feedback"><Button variant="outline" disabled={feedback.isPending} onClick={()=>feedback.mutate('expected')}>This was expected</Button></div></section>
        {(notice||feedback.isError||rebuild.isError||positions.isError)&&<p className="app-notice" role={feedback.isError||rebuild.isError||positions.isError?'alert':'status'}>{feedback.isError?readableError(feedback.error):rebuild.isError?readableError(rebuild.error):positions.isError?readableError(positions.error):notice}</p>}
      </div>
    </div>
  </div>;
}
function words(value:string){return value.replaceAll('_',' ');}
function CameraPlayer({camera,detail,time,active,setVideo,onSeek,onSelect,onError,onDecoded,onPlaybackChange}:{camera:PlaybackCamera;detail:VisitDetail;time:number;active:boolean;setVideo:(video:HTMLVideoElement|null)=>void;onSeek:(time:number)=>void;onSelect:()=>void;onError:()=>void;onDecoded:()=>void;onPlaybackChange:(playing:boolean,absolute:number)=>void}){
  const canvas=useRef<HTMLCanvasElement>(null);
  useEffect(()=>{const element=canvas.current,context=element?.getContext('2d');if(!element||!context)return;context.clearRect(0,0,element.width,element.height);const css=getComputedStyle(document.documentElement);context.strokeStyle=css.getPropertyValue('--v-accent').trim();context.lineWidth=parseFloat(css.getPropertyValue('--v-focus-width'));for(const track of Object.values(detail.overlays[camera.id]??{})){const frame=frameAt(track.frames,time);if(!frame)continue;const [x1,y1,x2,y2]=frame.box;context.strokeRect(x1,y1,x2-x1,y2-y1);if(frame.outline.length){context.beginPath();frame.outline.forEach(([x,y],index)=>index?context.lineTo(x,y):context.moveTo(x,y));context.closePath();context.stroke();}}},[detail,time,camera.id]);
  return <article className={`visit-camera${active?' is-active':''}${camera.clip_url?'':' is-empty'}`} aria-label={`${camera.name} evidence`}><Button className="visit-camera-select" variant="ghost" onClick={onSelect} aria-pressed={active}>{camera.name}</Button>{camera.clip_url?<div className="visit-video"><video className="player-media" ref={setVideo} src={camera.clip_url} controls muted playsInline preload="metadata" onFocus={onSelect} onClick={onSelect} onPlay={event=>onPlaybackChange(true,event.currentTarget.currentTime+camera.clip_t0)} onPause={event=>onPlaybackChange(false,event.currentTarget.currentTime+camera.clip_t0)} onLoadedData={onDecoded} onCanPlay={onDecoded} onLoadedMetadata={event=>{event.currentTarget.currentTime=cameraTime(time,camera.clip_t0,event.currentTarget.duration);}} onSeeked={event=>{onDecoded();const abs=event.currentTarget.currentTime+camera.clip_t0;if(Math.abs(abs-time)>.2)onSeek(abs);}} onError={onError}/><canvas ref={canvas} className="overlay" width={camera.width} height={camera.height} aria-label="Observed SAM track overlays"/></div>:<div className="visit-media-empty"><VideoOff aria-hidden="true"/><p>Media unavailable</p><small>{camera.source_label} · no exported clip</small></div>}</article>;
}
