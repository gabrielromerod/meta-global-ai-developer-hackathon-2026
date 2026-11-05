// Route replay: a cinematic, follow-cam 3D view of one visit's estimated positions.
// Evidence rules: positions are approximate estimates (r95 ring), nothing is drawn inside a
// coverage gap (no interpolation across one), and the gap label is written by code.
import {Component,useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {Canvas,useFrame,useThree} from '@react-three/fiber';
import {Edges,Grid,Line,OrbitControls} from '@react-three/drei';
import {AdditiveBlending,CanvasTexture,Color,DoubleSide,RepeatWrapping,Shape,Vector3,type Mesh,type MeshBasicMaterial} from 'three';
import type {OrbitControls as OrbitControlsImpl} from 'three-stdlib';
import {EyeOff,Radar} from 'lucide-react';
import {parseTwin,type TwinModel,type Vec2} from '../twin/geometry';
import {HouseDetail,parseDetail,type Detail} from './house-detail';
import {useMotionPreference} from '../motion';

type Rec=Record<string,unknown>;
interface Sample {t:number;x:number;z:number;r95:number;track:string;cameras:string[]}
interface Gap {id:string;t0:number;t1:number;from:Vec2|null;to:Vec2|null;label:string;region:string;regionName:string}
interface Segment {points:Sample[]}
interface Head {x:number;z:number;r95:number;cameras:string[]}
interface Palette {background:string;accent:string;unknown:string;danger:string;house:string;roof:string;tree:string;text:string}

const num=(v:unknown,d=0)=>typeof v==='number'&&Number.isFinite(v)?v:d;
const str=(v:unknown,d='')=>typeof v==='string'?v:d;
const arr=(v:unknown)=>Array.isArray(v)?v:[];
const point=(v:unknown):Vec2|null=>Array.isArray(v)&&typeof v[0]==='number'&&typeof v[1]==='number'?[v[0],v[1]]:null;

/** Parses the positions payload into gap-aware segments. Never joins samples across a gap. */
export function buildRoute(data:Rec|undefined){
  const gaps:Gap[]=arr(data?.gaps).map(g=>g as Rec).map(g=>({id:str(g.id),t0:num(g.t0),t1:num(g.t1),from:point(g.from),to:point(g.to),label:str(g.label,'Not observed'),region:str(g.region_id),regionName:str(g.region_name)}));
  const inGap=(t:number)=>gaps.some(g=>t>g.t0&&t<g.t1);
  const samples:Sample[]=arr(data?.positions).map(p=>p as Rec).filter(p=>typeof p.x==='number'&&typeof p.z==='number'&&typeof p.t==='number'&&!inGap(num(p.t)))
    .map(p=>({t:num(p.t),x:num(p.x),z:num(p.z),r95:Math.max(0,num(p.r95)),track:str(p.track_id),cameras:arr(p.cameras??p.camera_ids).map(c=>str(c))})).sort((a,b)=>a.t-b.t);
  const segments:Segment[]=[];let current:Sample[]=[];
  samples.forEach((s,i)=>{const prev=samples[i-1];
    if(prev&&(prev.track!==s.track||s.t-prev.t>2||gaps.some(g=>prev.t<=g.t0&&s.t>=g.t1))){if(current.length)segments.push({points:current});current=[];}
    current.push(s);});
  if(current.length)segments.push({points:current});
  // Display smoothing only (centred moving average inside a segment); recorded samples stay untouched.
  for(const segment of segments){const p=segment.points;segment.points=p.map((s,i)=>{const w=p.slice(Math.max(0,i-2),i+3);return {...s,x:w.reduce((a,b)=>a+b.x,0)/w.length,z:w.reduce((a,b)=>a+b.z,0)/w.length};});}
  return {gaps,segments};
}

/** Position at a recorded time: interpolated only between neighbours of one segment. */
export function headAt(segments:Segment[],time:number):Head|null{
  for(const {points} of segments){
    if(!points.length||time<points[0].t-.5||time>points[points.length-1].t+.5)continue;
    const i=points.findIndex(p=>p.t>time);
    if(i<=0){const p=i===0?points[0]:points[points.length-1];return {x:p.x,z:p.z,r95:p.r95,cameras:p.cameras};}
    const a=points[i-1],b=points[i],k=(time-a.t)/Math.max(b.t-a.t,1e-6);
    return {x:a.x+(b.x-a.x)*k,z:a.z+(b.z-a.z)*k,r95:a.r95+(b.r95-a.r95)*k,cameras:a.cameras};
  }
  return null;
}

function readPalette(element:HTMLElement|null):Palette{
  const css=getComputedStyle(element??document.documentElement),v=(n:string)=>css.getPropertyValue(n).trim();
  return {background:v('--v-scene-night-background')||'#131a23',accent:v('--v-twin-cone')||'#75aeff',unknown:v('--v-unknown')||'#d1b8ff',danger:v('--v-danger')||'#ff858c',house:v('--v-scene-night-house')||'#788492',roof:v('--v-scene-night-roof')||'#465462',tree:v('--v-scene-night-tree')||'#385e4b',text:v('--v-text')||'#fff'};
}

function webglAvailable(){
  try{const canvas=document.createElement('canvas');return !!(canvas.getContext('webgl2')||canvas.getContext('webgl'));}catch{return false;}
}

class Boundary extends Component<{children:ReactNode;fallback:ReactNode},{failed:boolean}>{
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  render(){return this.state.failed?this.props.fallback:this.props.children;}
}

export function RouteReplay({twin,positions,time,activeCameraId,playing,fallback}:{twin:Rec;positions?:Rec;time:number;activeCameraId:string|null;playing:boolean;fallback:ReactNode}){
  const host=useRef<HTMLDivElement>(null);
  const [palette,setPalette]=useState<Palette|null>(null);
  const [gl]=useState(webglAvailable);
  const reduced=useMotionPreference();
  const model=useMemo(()=>parseTwin(twin),[twin]);
  const route=useMemo(()=>buildRoute(positions),[positions]);
  const detail=useMemo(()=>parseDetail(twin),[twin]);
  useEffect(()=>{setPalette(readPalette(host.current));},[]);
  if(!gl)return <>{fallback}</>;
  const gap=route.gaps.find(g=>time>=g.t0&&time<=g.t1)??null;
  const head=gap?null:headAt(route.segments,time);
  const cameraName=model.cameras.find(c=>c.id===activeCameraId)?.name;
  const seen=route.segments.some(s=>s.points[0].t<=time);
  return <div ref={host} className="house-view replay" data-theme="dark" data-state={gap?'gap':head?'tracking':'idle'}>
    <Boundary fallback={fallback}>
      {palette&&<Canvas className="replay-canvas" dpr={[1,2]} camera={{fov:40,near:.1,far:200,position:[14,13,-10]}} gl={{antialias:true,preserveDrawingBuffer:true}} aria-label="Route replay">
        <color attach="background" args={[palette.background]}/>
        <fog attach="fog" args={[palette.background,18,46]}/>
        <Scene model={model} detail={detail} route={route} time={time} head={head} gap={gap} activeCameraId={activeCameraId} palette={palette} playing={playing} reduced={reduced}/>
      </Canvas>}
    </Boundary>
    <div className="replay-hud" aria-hidden="true"><span className="replay-corner tl"/><span className="replay-corner tr"/><span className="replay-corner bl"/><span className="replay-corner br"/></div>
    <div className="replay-top">
      <span className={`replay-live${playing?' is-on':''}`}><Radar aria-hidden="true"/>{playing?'Replaying route':'Route replay'}</span>
      {cameraName&&<span className="replay-cam">{cameraName}</span>}
    </div>
    <div className="replay-bottom">
      <p className="replay-status" aria-live="polite">{gap?<><EyeOff aria-hidden="true"/>No camera saw this stretch{gap.regionName?` · ${gap.regionName}`:''}</>:head?<>Estimated position ±{head.r95.toFixed(1)} m</>:seen?<>Out of view</>:<>Waiting for first sighting</>}</p>
      {route.gaps.length>0&&<p className="twin-gap-summary">{route.gaps.map(g=><span key={g.id} data-active={g===gap||undefined}>{g.label}</span>)}</p>}
    </div>
  </div>;
}

interface Guarded {id:string;label:string;footprint:Vec2[]}
/** Protected objects with a ground footprint (bundle `footprint_json` or a live `footprint`). */
export function guardedObjects(objects:unknown):Guarded[]{
  return arr(objects).map(o=>o as Rec).map(o=>({id:str(o.id),label:str(o.label,'Protected object'),footprint:arr(o.footprint??o.footprint_json).map(point).filter((v):v is Vec2=>v!==null)})).filter(o=>o.id&&o.footprint.length>=3);
}

function Scene({model,detail,route,time,head,gap,activeCameraId,palette,playing,reduced,focusOverride,onCameraSelect,rigOffset,guarded=[]}:{model:TwinModel;detail:Detail|null;route:ReturnType<typeof buildRoute>;time:number;head:Head|null;gap:Gap|null;activeCameraId:string|null;palette:Palette;playing:boolean;reduced:boolean;focusOverride?:Vec2|null;onCameraSelect?:(id:string)=>void;rigOffset?:[number,number,number];guarded?:Guarded[]}){
  const accent=useMemo(()=>new Color(palette.accent),[palette.accent]);
  const dim=useMemo(()=>new Color(palette.background).lerp(accent,.25),[palette.background,accent]);
  // Last known position (or first sighting) keeps the camera framed when nobody is visible.
  const focus=useMemo<Vec2>(()=>{
    if(focusOverride)return focusOverride;
    if(head){const c=routeCentre(route);return c?[c[0]+(head.x-c[0])*.35,c[1]+(head.z-c[1])*.35]:[head.x,head.z];}
    if(gap){const region=model.blindRegions.find(r=>r.id===gap.region);if(region){const p=region.polygon_m;return [p.reduce((a,b)=>a+b[0],0)/p.length,p.reduce((a,b)=>a+b[1],0)/p.length];}if(gap.from&&gap.to)return [(gap.from[0]+gap.to[0])/2,(gap.from[1]+gap.to[1])/2];}
    const past=route.segments.flatMap(s=>s.points).filter(p=>p.t<=time).pop()??route.segments[0]?.points[0];
    return past?[past.x,past.z]:[0,3.5];
  },[head,gap,route,time,model,focusOverride]);
  return <>
    <hemisphereLight args={[palette.house,palette.background,detail?1.5:.9]}/>
    <directionalLight position={[10,16,-8]} intensity={detail?1.8:.8}/>
    <Grid position={[0,.002,0]} args={[60,60]} cellSize={.5} sectionSize={2} cellThickness={.4} sectionThickness={.8} cellColor={dim} sectionColor={dim.clone().lerp(accent,.35)} fadeDistance={30} fadeStrength={1.6} infiniteGrid/>
    {detail?<HouseDetail detail={detail} buildings={model.boxes.filter(b=>b.kind==='building')} palette={palette}/>:model.boxes.map(box=><Massing key={box.id} box={box} palette={palette}/>)}
    {detail&&model.boxes.filter(b=>b.kind!=='building').map(box=><Massing key={box.id} box={box} palette={palette}/>)}
    {model.blindRegions.map(region=><BlindRegion key={region.id} polygon={region.polygon_m} active={gap?.region===region.id} palette={palette} reduced={reduced}/>)}
    {model.cameras.map(camera=><CameraDevice key={camera.id} camera={camera} active={camera.id===activeCameraId} accent={palette.accent} onSelect={onCameraSelect}/>)}
    {route.segments.map((segment,i)=><Trail key={i} points={segment.points} time={time} head={head} accent={accent} background={palette.background}/>)}
    {route.gaps.map(g=><GapEnds key={g.id} gap={g} time={time} color={palette.unknown}/>)}
    {guarded.map(o=><GuardedFootprint key={o.id} object={o} palette={palette}/>)}
    {head&&<Marker head={head} color={palette.accent} reduced={reduced}/>}
    <Rig focus={focus} playing={playing} reduced={reduced} offset={rigOffset}/>
  </>;
}

function Rig({focus,playing,reduced,offset=[9,12,-11]}:{focus:Vec2;playing:boolean;reduced:boolean;offset?:[number,number,number]}){
  const controls=useRef<OrbitControlsImpl>(null);const {camera}=useThree();
  const target=useMemo(()=>new Vector3(),[]);const placed=useRef(false);
  useFrame((_,delta)=>{
    const c=controls.current;if(!c)return;
    target.set(focus[0],0,focus[1]);
    if(!placed.current){camera.position.set(target.x+offset[0],offset[1],target.z+offset[2]);c.target.copy(target);placed.current=true;}
    const before=c.target.clone();
    c.target.lerp(target,reduced?1:1-Math.exp(-delta*2.2));
    camera.position.add(c.target.clone().sub(before));
    c.update();
  });
  return <OrbitControls ref={controls} makeDefault enablePan={false} enableDamping minDistance={5} maxDistance={offset[1]>14?70:32} maxPolarAngle={1.3} autoRotate={playing&&!reduced} autoRotateSpeed={.35}/>;
}

function Massing({box,palette}:{box:TwinModel['boxes'][number];palette:Palette}){
  const w=box.max[0]-box.min[0],d=box.max[1]-box.min[1],tree=box.kind.includes('tree');
  return <mesh position={[(box.min[0]+box.max[0])/2,box.h/2,(box.min[1]+box.max[1])/2]}>
    <boxGeometry args={[w,box.h,d]}/>
    <meshStandardMaterial color={tree?palette.tree:palette.house} transparent opacity={tree?.35:.55} depthWrite={false}/>
    <Edges color={tree?palette.tree:palette.accent} transparent opacity={tree?.6:.75}/>
  </mesh>;
}

function flatShape(points:Vec2[]){const shape=new Shape();points.forEach(([x,z],i)=>i?shape.lineTo(x,-z):shape.moveTo(x,-z));shape.closePath();return shape;}

function routeCentre(route:ReturnType<typeof buildRoute>):Vec2|null{
  const pts=route.segments.flatMap(s=>s.points);if(!pts.length)return null;
  const xs=pts.map(p=>p.x),zs=pts.map(p=>p.z);
  return [(Math.min(...xs)+Math.max(...xs))/2,(Math.min(...zs)+Math.max(...zs))/2];
}

// Diagonal hatch for blind regions. Shape UVs are metres, so repeat 2 gives two stripes per metre.
let hatchTexture:CanvasTexture|null=null;
function hatch(){
  if(hatchTexture)return hatchTexture;
  const c=document.createElement('canvas');c.width=c.height=64;const g=c.getContext('2d');
  if(g){g.strokeStyle='#fff';g.lineWidth=10;for(let i=-64;i<=128;i+=32){g.beginPath();g.moveTo(i,64);g.lineTo(i+64,0);g.stroke();}}
  hatchTexture=new CanvasTexture(c);hatchTexture.wrapS=hatchTexture.wrapT=RepeatWrapping;hatchTexture.repeat.set(2,2);
  return hatchTexture;
}

function BlindRegion({polygon,active,palette,reduced}:{polygon:Vec2[];active:boolean;palette:Palette;reduced:boolean}){
  const material=useRef<MeshBasicMaterial>(null);const shape=useMemo(()=>flatShape(polygon),[polygon]);
  const stripes=useMemo(()=>hatch(),[]);
  const outline=useMemo(()=>[...polygon,polygon[0]].map(([x,z])=>[x,.03,z] as [number,number,number]),[polygon]);
  useFrame(({clock})=>{if(material.current)material.current.opacity=active?(reduced?.4:.28+.18*Math.sin(clock.elapsedTime*4)):.1;});
  const color=active?palette.danger:palette.unknown;
  return <group>
    <mesh rotation={[-Math.PI/2,0,0]} position={[0,.02,0]}><shapeGeometry args={[shape]}/><meshBasicMaterial ref={material} color={color} transparent opacity={.1} side={DoubleSide} depthWrite={false}/></mesh>
    <mesh rotation={[-Math.PI/2,0,0]} position={[0,.025,0]}><shapeGeometry args={[shape]}/><meshBasicMaterial color={color} alphaMap={stripes} transparent opacity={active?.55:.3} side={DoubleSide} depthWrite={false}/></mesh>
    <Line points={outline} color={color} lineWidth={active?2:1} dashed dashSize={.3} gapSize={.2} transparent opacity={active?1:.6}/>
  </group>;
}

function CameraDevice({camera,active,accent,onSelect}:{camera:TwinModel['cameras'][number];active:boolean;accent:string;onSelect?:(id:string)=>void}){
  const [x,y,z]=camera.position,[lx,,lz]=camera.look_at;
  const fan=useMemo(()=>{
    const heading=Math.atan2(lz-z,lx-x),half=camera.hfov_deg*Math.PI/360,range=Math.min(camera.range_m,9);
    const pts:Vec2[]=[[x,z]];for(let i=0;i<=16;i++){const a=heading-half+(2*half*i)/16;pts.push([x+Math.cos(a)*range,z+Math.sin(a)*range]);}
    return flatShape(pts);
  },[x,z,lx,lz,camera.hfov_deg,camera.range_m]);
  return <group>
    <mesh position={[x,y,z]} onClick={onSelect?event=>{event.stopPropagation();onSelect(camera.id);}:undefined} onPointerOver={onSelect?()=>{document.body.style.cursor='pointer';}:undefined} onPointerOut={onSelect?()=>{document.body.style.cursor='';}:undefined}><octahedronGeometry args={[active?.6:.5]}/><meshBasicMaterial color={accent} transparent opacity={active?1:.85}/></mesh>
    {onSelect&&<mesh position={[x,y,z]} onClick={event=>{event.stopPropagation();onSelect(camera.id);}} onPointerOver={()=>{document.body.style.cursor='pointer';}} onPointerOut={()=>{document.body.style.cursor='';}}><sphereGeometry args={[.9,12,8]}/><meshBasicMaterial transparent opacity={0} depthWrite={false}/></mesh>}
    {!active&&onSelect&&<Line points={[[x,y,z],[x,.02,z]]} color={accent} lineWidth={1} transparent opacity={.35}/>}
    {!active&&onSelect&&<mesh rotation={[-Math.PI/2,0,0]} position={[0,.012,0]}><shapeGeometry args={[fan]}/><meshBasicMaterial color={accent} transparent opacity={.035} blending={AdditiveBlending} side={DoubleSide} depthWrite={false}/></mesh>}
    {active&&<><mesh rotation={[-Math.PI/2,0,0]} position={[0,.015,0]}><shapeGeometry args={[fan]}/><meshBasicMaterial color={accent} transparent opacity={.1} blending={AdditiveBlending} side={DoubleSide} depthWrite={false}/></mesh>
      <Line points={[[x,y,z],[x,.02,z]]} color={accent} lineWidth={1} transparent opacity={.5}/></>}
  </group>;
}

function Trail({points,time,head,accent,background}:{points:Sample[];time:number;head:Head|null;accent:Color;background:string}){
  const all=useMemo(()=>points.map(p=>[p.x,.06,p.z] as [number,number,number]),[points]);
  const done=points.filter(p=>p.t<=time).map(p=>[p.x,.08,p.z] as [number,number,number]);
  const live=head&&points[0].t<=time&&points[points.length-1].t>=time;
  if(live&&head)done.push([head.x,.08,head.z]);
  // The walked part brightens toward the person; the rest of the recorded route stays a faint ghost.
  const colors=done.map((_,i)=>new Color(background).lerp(accent,.25+.75*((i+1)/done.length)));
  return <>
    {all.length>1&&<Line points={all} color={accent} lineWidth={1} transparent opacity={.18} dashed dashSize={.15} gapSize={.15}/>}
    {done.length>1&&<Line points={done} vertexColors={colors} lineWidth={3.5}/>}
  </>;
}

/** Gap endpoints plus a grey dotted connector. It claims nothing about the path: it only links the
 *  last and next sightings; the HUD below says how long nobody saw the person. */
function GuardedFootprint({object,palette}:{object:Guarded;palette:Palette}){
  const shape=useMemo(()=>flatShape(object.footprint),[object.footprint]);
  const outline=useMemo(()=>[...object.footprint,object.footprint[0]].map(([x,z])=>[x,.04,z] as [number,number,number]),[object.footprint]);
  const c=object.footprint.reduce<[number,number]>((a,[x,z])=>[a[0]+x/object.footprint.length,a[1]+z/object.footprint.length],[0,0]);
  return <group>
    <mesh rotation={[-Math.PI/2,0,0]} position={[0,.035,0]}><shapeGeometry args={[shape]}/><meshBasicMaterial color={palette.accent} transparent opacity={.22} side={DoubleSide} depthWrite={false}/></mesh>
    <Line points={outline} color={palette.accent} lineWidth={2}/>
    <mesh position={[c[0],.45,c[1]]}><coneGeometry args={[.12,.3,4]}/><meshBasicMaterial color={palette.accent}/></mesh>
  </group>;
}

function GapEnds({gap,time,color}:{gap:Gap;time:number;color:string}){
  const open=time>=gap.t0,from=gap.from,to=gap.to;
  return <>
    {from&&open&&<Ring at={from} color={color}/>}
    {to&&time>=gap.t1&&<Ring at={to} color={color}/>}
    {from&&to&&open&&<Line points={[[from[0],.07,from[1]],[to[0],.07,to[1]]]} color="#8a94a3" lineWidth={1.5} dashed dashSize={.08} gapSize={.18} transparent opacity={.85}/>}
  </>;
}
function Ring({at,color}:{at:Vec2;color:string}){
  return <mesh rotation={[-Math.PI/2,0,0]} position={[at[0],.05,at[1]]}><ringGeometry args={[.22,.3,32]}/><meshBasicMaterial color={color} transparent opacity={.9} side={DoubleSide}/></mesh>;
}

function Marker({head,color,reduced}:{head:Head;color:string;reduced:boolean}){
  const halo=useRef<Mesh>(null),pulse=useRef<Mesh>(null);
  useFrame(({clock})=>{
    if(reduced)return;const t=clock.elapsedTime;
    if(halo.current)halo.current.scale.setScalar(1+.15*Math.sin(t*5));
    if(pulse.current){const p=(t*.8)%1;pulse.current.scale.setScalar(.4+p*1.6);(pulse.current.material as MeshBasicMaterial).opacity=.6*(1-p);}
  });
  const r=Math.max(head.r95,.2);
  return <group position={[head.x,0,head.z]}>
    <mesh position={[0,.9,0]}><capsuleGeometry args={[.16,1.1,6,12]}/><meshBasicMaterial color={color} transparent opacity={.9}/></mesh>
    <mesh ref={halo} position={[0,.9,0]}><sphereGeometry args={[.55,24,24]}/><meshBasicMaterial color={color} transparent opacity={.14} blending={AdditiveBlending} depthWrite={false}/></mesh>
    <mesh position={[0,3,0]}><cylinderGeometry args={[.03,.03,6,8,1,true]}/><meshBasicMaterial color={color} transparent opacity={.25} blending={AdditiveBlending} depthWrite={false}/></mesh>
    <mesh rotation={[-Math.PI/2,0,0]} position={[0,.04,0]}><circleGeometry args={[r,40]}/><meshBasicMaterial color={color} transparent opacity={.12} depthWrite={false}/></mesh>
    <mesh rotation={[-Math.PI/2,0,0]} position={[0,.045,0]}><ringGeometry args={[r-.03,r,48]}/><meshBasicMaterial color={color} transparent opacity={.8} side={DoubleSide}/></mesh>
    <mesh ref={pulse} rotation={[-Math.PI/2,0,0]} position={[0,.05,0]}><ringGeometry args={[.9,1,48]}/><meshBasicMaterial color={color} transparent opacity={0} side={DoubleSide} depthWrite={false}/></mesh>
  </group>;
}

const EMPTY_ROUTE:ReturnType<typeof buildRoute>={gaps:[],segments:[]};

/** Explorable private house (no route): cameras are selectable, views frame front/side/back. */
export function HouseScene({twin,activeCameraId,onCameraSelect,preset,fallback,protectedObjects,positions,note}:{twin:Rec;activeCameraId:string|null;onCameraSelect?:(id:string)=>void;preset?:string;fallback:ReactNode;protectedObjects?:unknown;positions?:Rec;note?:string}){
  // With positions, the whole recorded route is drawn at once (end of the visit): trail, gap rings
  // and the dotted "not observed" link, with the gap's blind region highlighted.
  const route=useMemo(()=>positions?buildRoute(positions):EMPTY_ROUTE,[positions]);
  const end=useMemo(()=>route.segments.reduce((m,s)=>Math.max(m,s.points[s.points.length-1]?.t??0),0),[route]);
  const head=useMemo(()=>route.segments.length?headAt(route.segments,end):null,[route,end]);
  const guarded=useMemo(()=>guardedObjects(protectedObjects),[protectedObjects]);
  const host=useRef<HTMLDivElement>(null);
  const [palette,setPalette]=useState<Palette|null>(null);
  const [gl]=useState(webglAvailable);
  const reduced=useMotionPreference();
  const model=useMemo(()=>parseTwin(twin),[twin]);
  const detail=useMemo(()=>parseDetail(twin),[twin]);
  useEffect(()=>{setPalette(readPalette(host.current));},[]);
  const focus=useMemo<Vec2>(()=>{
    const houses=model.boxes.filter(b=>b.kind==='building');
    const x0=Math.min(...houses.map(b=>b.min[0]),0),x1=Math.max(...houses.map(b=>b.max[0]),0),z0=Math.min(...houses.map(b=>b.min[1]),0),z1=Math.max(...houses.map(b=>b.max[1]),0);
    const camera=model.cameras.find(c=>c.id===activeCameraId);
    if(camera){const [x,,z]=camera.position,[lx,,lz]=camera.look_at;return [x+(lx-x)*.45,z+(lz-z)*.45];}
    if(preset==='front')return [(x0+x1)/2,z0-4];
    if(preset==='backyard')return [(x0+x1)/2,z1+4];
    if(preset==='left'){const side=model.cameras.find(c=>c.id==='side_left');return side?[side.position[0],(z0+z1)/2]:[x0-1,(z0+z1)/2];}
    return [(x0+x1)/2,(z0+z1)/2];
  },[model,activeCameraId,preset]);
  if(!gl)return <>{fallback}</>;
  const cameraName=model.cameras.find(c=>c.id===activeCameraId)?.name;
  return <div ref={host} className="house-view replay house-scene" data-theme="dark">
    <Boundary fallback={fallback}>
      {palette&&<Canvas className="replay-canvas" dpr={[1,2]} camera={{fov:40,near:.1,far:200,position:[14,16,-18]}} gl={{antialias:true}} aria-label="House model">
        <color attach="background" args={[palette.background]}/>
        <fog attach="fog" args={[palette.background,30,70]}/>
        <Scene model={model} detail={detail} route={route} time={end} head={head} gap={null} activeCameraId={activeCameraId} palette={palette} playing={false} reduced={reduced} focusOverride={activeCameraId||preset||!route.segments.length?focus:routeCentre(route)??focus} onCameraSelect={onCameraSelect} rigOffset={[16,15,-24]} guarded={guarded}/>
      </Canvas>}
    </Boundary>
    <div className="replay-hud" aria-hidden="true"><span className="replay-corner tl"/><span className="replay-corner tr"/><span className="replay-corner bl"/><span className="replay-corner br"/></div>
    <div className="replay-top">
      <span className="replay-live"><Radar aria-hidden="true"/>My house · private</span>
      {cameraName&&<span className="replay-cam">{cameraName}</span>}
    </div>
    <div className="replay-bottom">{route.gaps.length>0&&<p className="twin-gap-summary">{route.gaps.map(g=><span key={g.id} data-active>{g.label}{g.regionName?` · ${g.regionName}`:''}</span>)}</p>}<p className="replay-status">{note??(detail?'Simplified from your LiDAR scan. Roof and camera spots are approximate.':'Generic diagram')}</p></div>
  </div>;
}
