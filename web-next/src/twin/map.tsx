import {useId,useMemo,type CSSProperties} from 'react';
import type {HouseViewProps} from '../contracts';
import {Button,Chip} from '../components/ui';
import {coneFootprint,evidenceAtTime,parseTwin} from './geometry';
import './map.css';

/** Native SVG fallback over the same generic geometry and observed evidence rules. */
export function MapView({twin,positions,time=0,activeCameraId,onCameraSelect,lighting}:HouseViewProps){
  const pattern=useId().replaceAll(':','');
  const model=useMemo(()=>parseTwin(twin),[twin]);
  const evidence=useMemo(()=>evidenceAtTime(positions,time),[positions,time]);
  const [x,z]=model.ground.min,[right,back]=model.ground.max;
  const sceneStyle=lighting?{'--v-twin-ground':`var(--v-scene-${lighting}-ground)`,'--v-twin-house':`var(--v-scene-${lighting}-house)`,'--v-twin-tree':`var(--v-scene-${lighting}-tree)`} as CSSProperties:undefined;
  return <section className="twin-map" style={sceneStyle} aria-label="Property camera map" data-testid="property-map">
    <header><Chip>2D map</Chip><span>Stylized property · approximate locations</span></header>
    <svg role="img" aria-label="Property evidence map" viewBox={`${x} ${z} ${right-x} ${back-z}`}>
      <defs><pattern id={pattern} width="1" height="1" patternUnits="userSpaceOnUse"><path d="M0,1 L1,0" className="map-hatch"/></pattern></defs>
      <rect x={x} y={z} width={right-x} height={back-z} className="map-ground"/>
      <g transform={`translate(${x+right} ${z+back}) scale(-1 -1)`}>
      {model.boxes.map(box=><rect key={box.id} x={box.min[0]} y={box.min[1]} width={box.max[0]-box.min[0]} height={box.max[1]-box.min[1]} className={box.kind==='tree_barrier'?'map-trees':'map-house'}><title>{box.kind==='tree_barrier'?'Tree barrier':'House'}</title></rect>)}
      {model.cameras.map(camera=><g key={camera.id}><polygon points={coneFootprint(camera,model.boxes,model.ground).map(point=>point.join(',')).join(' ')} className="map-cone"/><circle cx={camera.position[0]} cy={camera.position[2]} className={camera.id===activeCameraId?'map-camera is-active':'map-camera'} onClick={()=>onCameraSelect?.(camera.id)}><title>{camera.name}</title></circle></g>)}
      {model.blindRegions.map(region=><polygon key={region.id} points={region.polygon_m.map(point=>point.join(',')).join(' ')} fill={`url(#${pattern})`} className="map-blind"><title>{region.name}</title></polygon>)}
      {evidence.paths.map((path,index)=><polyline key={index} points={path.map(point=>point.join(',')).join(' ')} className="map-observed"/>)}
      {evidence.gaps.map(gap=><line key={gap.id} x1={gap.from[0]} y1={gap.from[1]} x2={gap.to[0]} y2={gap.to[1]} className="map-gap"><title>{gap.label}</title></line>)}
      {evidence.current&&<circle aria-label="Current estimated position" cx={evidence.current.x} cy={evidence.current.z} r={evidence.current.r95} className="map-estimate"/>}
      </g>
    </svg>
    <div className="map-camera-actions" aria-label="Select a map camera">{model.cameras.map(camera=><Button size="sm" variant="ghost" key={camera.id} disabled={!onCameraSelect} aria-label={`Select ${camera.name}`} aria-pressed={camera.id===activeCameraId} onClick={()=>onCameraSelect?.(camera.id)}>{camera.name}</Button>)}</div>
    <div className="map-legend"><span>Camera coverage · nominal</span><span>Observed path</span><span>Not observed</span>{model.boxes.some(box=>box.kind==='tree_barrier')&&<span>Tree barrier</span>}</div>
    {evidence.gapLabels.map(label=><p className="map-gap-note" key={label}>{label}. No position is inferred inside the gap.</p>)}
  </section>;
}
