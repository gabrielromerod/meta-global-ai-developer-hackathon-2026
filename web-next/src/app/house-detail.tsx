// Simplified, untextured house from a private massing (vigil/spatial/massing.py): walls,
// inferred roofs, porch, pergola, doors, fences, ground surfaces and trees. Colours derive
// from the scene tokens; nothing here is a photo or a mesh from the scan.
import {useMemo} from 'react';
import {Edges} from '@react-three/drei';
import {BufferGeometry,Color,DoubleSide,Float32BufferAttribute} from 'three';
import type {Box,Vec2} from '../twin/geometry';

type Rec=Record<string,unknown>;
export interface Roof {id:string;type:'hip'|'gable_x'|'gable_z'|'flat';min:Vec2;max:Vec2;eave:number;rise:number;overhang:number}
export interface Detail {
  roofs:Roof[];
  fences:{id:string;from:Vec2;to:Vec2;h:number;observed:boolean}[];
  surfaces:{id:string;kind:string;min:Vec2;max:Vec2}[];
  porches:{id:string;min:Vec2;max:Vec2;h:number;posts:Vec2[]}[];
  pergolas:{id:string;min:Vec2;max:Vec2;h:number;style:string}[];
  solar:{id:string;min:Vec2;max:Vec2}[];
  doors:{id:string;kind:string;from:Vec2;to:Vec2;h:number}[];
  trees:{id:string;kind:string;at:Vec2;r:number;h:number}[];
}
export interface DetailPalette {background:string;accent:string;house:string;roof:string;tree:string}

const n=(v:unknown,d=0)=>typeof v==='number'&&Number.isFinite(v)?v:d;
const s=(v:unknown,d='')=>typeof v==='string'?v:d;
const list=(v:unknown)=>Array.isArray(v)?v.map(x=>(x??{}) as Rec):[];
const v2=(v:unknown):Vec2=>Array.isArray(v)?[n(v[0]),n(v[1])]:[0,0];

/** Reads the optional ``detail`` block; null for the generic public diagram. */
export function parseDetail(twin:Rec):Detail|null{
  const d=twin.detail as Rec|undefined;
  if(!d||typeof d!=='object')return null;
  return {
    roofs:list(d.roofs).map(r=>({id:s(r.id),type:(['hip','gable_x','gable_z','flat'].includes(s(r.type))?s(r.type):'flat') as Roof['type'],min:v2(r.min),max:v2(r.max),eave:n(r.eave,2.8),rise:Math.max(0,n(r.rise)),overhang:Math.max(0,n(r.overhang,.4))})),
    fences:list(d.fences).map(f=>({id:s(f.id),from:v2(f.from),to:v2(f.to),h:n(f.h,1.8),observed:f.observed!==false})),
    surfaces:list(d.surfaces).map(x=>({id:s(x.id),kind:s(x.kind,'paving'),min:v2(x.min),max:v2(x.max)})),
    porches:list(d.porches).map(p=>({id:s(p.id),min:v2(p.min),max:v2(p.max),h:n(p.h,2.8),posts:Array.isArray(p.posts)?p.posts.map(v2):[]})),
    pergolas:list(d.pergolas).map(p=>({id:s(p.id),min:v2(p.min),max:v2(p.max),h:n(p.h,2.6),style:s(p.style,'slats')})),
    solar:list(d.solar).map(x=>({id:s(x.id),min:v2(x.min),max:v2(x.max)})),
    doors:list(d.doors).map(x=>({id:s(x.id),kind:s(x.kind,'door'),from:v2(x.from),to:v2(x.to),h:n(x.h,2.1)})),
    trees:list(d.trees).map(t=>({id:s(t.id),kind:s(t.kind,'tree'),at:v2(t.at),r:n(t.r,1),h:n(t.h,3)})),
  };
}

/** Roof triangles (positions only) for a footprint expanded by the overhang. */
export function roofTriangles(roof:Roof):number[]{
  const o=roof.overhang,[x0,z0]=[roof.min[0]-o,roof.min[1]-o],[x1,z1]=[roof.max[0]+o,roof.max[1]+o];
  const y=roof.eave,top=roof.eave+roof.rise,w=x1-x0,d=z1-z0,mx=(x0+x1)/2,mz=(z0+z1)/2;
  const tri=(...p:number[][])=>p.flat();
  const quad=(a:number[],b:number[],c:number[],e:number[])=>[...tri(a,b,c),...tri(a,c,e)];
  const A=[x0,y,z0],B=[x1,y,z0],C=[x1,y,z1],D=[x0,y,z1];
  if(roof.type==='flat'||roof.rise<=0)return [...quad([x0,y+.15,z0],[x1,y+.15,z0],[x1,y+.15,z1],[x0,y+.15,z1])];
  if(roof.type==='gable_z'){const R0=[mx,top,z0],R1=[mx,top,z1];return [...quad(A,R0,R1,D),...quad(B,C,R1,R0),...tri(A,B,R0),...tri(D,R1,C)];}
  if(roof.type==='gable_x'){const R0=[x0,top,mz],R1=[x1,top,mz];return [...quad(A,B,R1,R0),...quad(D,R0,R1,C),...tri(A,R0,D),...tri(B,C,R1)];}
  if(w>=d){const R0=[x0+d/2,top,mz],R1=[x1-d/2,top,mz];return [...quad(A,B,R1,R0),...quad(D,R0,R1,C),...tri(A,R0,D),...tri(B,C,R1)];}
  const R0=[mx,top,z0+w/2],R1=[mx,top,z1-w/2];return [...quad(A,R0,R1,D),...quad(B,C,R1,R0),...tri(A,B,R0),...tri(D,R1,C)];
}

/** Height of a roof surface above a plan point (eave height outside its footprint). */
export function roofHeightAt(roof:Roof,x:number,z:number):number{
  const o=roof.overhang,x0=roof.min[0]-o,x1=roof.max[0]+o,z0=roof.min[1]-o,z1=roof.max[1]+o;
  if(x<x0||x>x1||z<z0||z>z1)return roof.eave;
  const w=x1-x0,d=z1-z0,toX=Math.min(x-x0,x1-x),toZ=Math.min(z-z0,z1-z);
  if(roof.type==='flat'||roof.rise<=0)return roof.eave+.15;
  if(roof.type==='gable_z')return roof.eave+roof.rise*toX/(w/2);
  if(roof.type==='gable_x')return roof.eave+roof.rise*toZ/(d/2);
  const half=Math.min(w,d)/2;return roof.eave+roof.rise*Math.min(toX,toZ,half)/half;
}

function SolarArray({panel,roofs,color}:{panel:Detail['solar'][number];roofs:Roof[];color:string}){
  const cx=(panel.min[0]+panel.max[0])/2,cz=(panel.min[1]+panel.max[1])/2;
  const roof=roofs.find(r=>cx>=r.min[0]&&cx<=r.max[0]&&cz>=r.min[1]&&cz<=r.max[1]);
  const points=useMemo(()=>{if(!roof)return [];const [a,b]=panel.min,[c,e]=panel.max;const y=(x:number,z:number)=>roofHeightAt(roof,x,z)+.08;
    const A=[a,y(a,b),b],B=[c,y(c,b),b],C=[c,y(c,e),e],D=[a,y(a,e),e];return [...A,...B,...C,...A,...C,...D];},[roof,panel]);
  const geometry=useGeometry(points);
  if(!roof)return null;
  return <mesh geometry={geometry}><meshStandardMaterial color={color} side={DoubleSide} metalness={.35} roughness={.35}/><Edges color="#ffffff" transparent opacity={.25}/></mesh>;
}

function useGeometry(points:number[]){
  return useMemo(()=>{const g=new BufferGeometry();g.setAttribute('position',new Float32BufferAttribute(points,3));g.computeVertexNormals();return g;},[points]);
}

function RoofMesh({roof,palette,color}:{roof:Roof;palette:DetailPalette;color:string}){
  const points=useMemo(()=>roofTriangles(roof),[roof]);const geometry=useGeometry(points);
  return <mesh geometry={geometry}><meshStandardMaterial color={color} side={DoubleSide} roughness={.9} flatShading/><Edges color={palette.accent} transparent opacity={.55} threshold={20}/></mesh>;
}

function slab(min:Vec2,max:Vec2,y0:number,y1:number){return {position:[(min[0]+max[0])/2,(y0+y1)/2,(min[1]+max[1])/2] as [number,number,number],args:[Math.max(max[0]-min[0],.01),Math.max(y1-y0,.01),Math.max(max[1]-min[1],.01)] as [number,number,number]};}

function Panel({from,to,y0,y1,thick,color,opacity=1}:{from:Vec2;to:Vec2;y0:number;y1:number;thick:number;color:string;opacity?:number}){
  const dx=to[0]-from[0],dz=to[1]-from[1],len=Math.hypot(dx,dz);
  return <mesh position={[(from[0]+to[0])/2,(y0+y1)/2,(from[1]+to[1])/2]} rotation={[0,-Math.atan2(dz,dx),0]}><boxGeometry args={[len,y1-y0,thick]}/><meshStandardMaterial color={color} transparent={opacity<1} opacity={opacity} depthWrite={opacity>=1}/></mesh>;
}

export function HouseDetail({detail,buildings,palette}:{detail:Detail;buildings:Box[];palette:DetailPalette}){
  const colors=useMemo(()=>{
    const bg=new Color(palette.background),house=new Color(palette.house),tree=new Color(palette.tree),roof=new Color(palette.roof);
    return {
      wall:house.clone().lerp(new Color('#ffffff'),.08).getStyle(),
      roofTone:roof.clone().lerp(house,.3).getStyle(),
      lawn:tree.clone().lerp(new Color(palette.house),.12).getStyle(),
      planting:tree.clone().lerp(roof,.55).lerp(bg,.2).getStyle(),
      paving:house.clone().lerp(bg,.4).getStyle(),
      gravel:house.clone().lerp(roof,.5).lerp(bg,.5).getStyle(),
      dark:bg.clone().lerp(roof,.35).getStyle(),
      fence:house.clone().lerp(bg,.35).getStyle(),
      tree:tree.clone().lerp(new Color(palette.accent),.08).getStyle(),
      wood:roof.clone().lerp(house,.3).getStyle(),
      solar:bg.clone().lerp(new Color(palette.accent),.3).getStyle(),
      cover:house.clone().lerp(new Color('#ffffff'),.15).getStyle(),
    };
  },[palette]);
  const surfaceColor=(kind:string)=>kind==='lawn'?colors.lawn:kind==='planting'?colors.planting:kind==='gravel'?colors.gravel:colors.paving;
  return <group name="private-house-massing">
    {detail.surfaces.map((x,i)=>{const sl=slab(x.min,x.max,0,.01+i*.0004);return <mesh key={x.id} position={[sl.position[0],.004+i*.0004,sl.position[2]]} rotation={[-Math.PI/2,0,0]}><planeGeometry args={[sl.args[0],sl.args[2]]}/><meshStandardMaterial color={surfaceColor(x.kind)} roughness={1}/></mesh>;})}
    {buildings.map(b=>{const sl=slab(b.min,b.max,0,b.h);return <mesh key={b.id} position={sl.position}><boxGeometry args={sl.args}/><meshStandardMaterial color={colors.wall} roughness={.95}/><Edges color={palette.accent} transparent opacity={.35}/></mesh>;})}
    {detail.roofs.map(r=><RoofMesh key={r.id} roof={r} palette={palette} color={colors.roofTone}/>)}
    {detail.solar.map(x=><SolarArray key={x.id} panel={x} roofs={detail.roofs} color={colors.solar}/>)}
    {detail.porches.map(p=><group key={p.id}>
      {(()=>{const sl=slab(p.min,p.max,p.h-.18,p.h);return <mesh position={sl.position}><boxGeometry args={sl.args}/><meshStandardMaterial color={palette.roof}/><Edges color={palette.accent} transparent opacity={.5}/></mesh>;})()}
      {p.posts.map((q,i)=><mesh key={i} position={[q[0],p.h/2,q[1]]}><cylinderGeometry args={[.09,.09,p.h,10]}/><meshStandardMaterial color={colors.wall}/></mesh>)}
    </group>)}
    {detail.pergolas.map(p=>{const w=p.max[0]-p.min[0],d=p.max[1]-p.min[1];const along=w>=d;const span=along?w:d;const count=Math.max(2,Math.round(span/.6));
      const posts:Vec2[]=[];const step=span/Math.max(1,Math.round(span/3));for(let t=0;t<=span+1e-6;t+=step)posts.push(along?[p.min[0]+t,p.max[1]]:[p.max[0],p.min[1]+t]);
      if(p.style==='solid')return <group key={p.id}>
        {(()=>{const sl=slab([p.min[0]-.15,p.min[1]],[p.max[0]+.15,p.max[1]+.2],p.h-.12,p.h);return <mesh position={sl.position}><boxGeometry args={sl.args}/><meshStandardMaterial color={colors.cover} roughness={.6}/><Edges color={palette.accent} transparent opacity={.4}/></mesh>;})()}
        {posts.map((q,i)=><mesh key={'p'+i} position={[q[0],(p.h-.12)/2,q[1]]}><boxGeometry args={[.12,p.h-.12,.12]}/><meshStandardMaterial color={colors.cover}/></mesh>)}
      </group>;
      return <group key={p.id}>
        {Array.from({length:count+1},(_,i)=>{const t=i*span/count;return along
          ?<mesh key={i} position={[p.min[0]+t,p.h,(p.min[1]+p.max[1])/2]}><boxGeometry args={[.07,.14,d+.2]}/><meshStandardMaterial color={colors.wood}/></mesh>
          :<mesh key={i} position={[(p.min[0]+p.max[0])/2,p.h,p.min[1]+t]}><boxGeometry args={[w+.2,.14,.07]}/><meshStandardMaterial color={colors.wood}/></mesh>;})}
        <Panel from={along?[p.min[0],p.max[1]]:[p.max[0],p.min[1]]} to={along?[p.max[0],p.max[1]]:[p.max[0],p.max[1]]} y0={p.h-.25} y1={p.h-.07} thick={.12} color={colors.wood}/>
        {posts.map((q,i)=><mesh key={'p'+i} position={[q[0],(p.h-.07)/2,q[1]]}><boxGeometry args={[.12,p.h-.07,.12]}/><meshStandardMaterial color={colors.wood}/></mesh>)}
      </group>;})}
    {detail.doors.map(x=><Panel key={x.id} from={x.from} to={x.to} y0={0} y1={x.h} thick={.04} color={x.kind==='garage'?colors.paving:colors.dark}/>)}
    {detail.fences.map(f=><Panel key={f.id} from={f.from} to={f.to} y0={0} y1={f.h} thick={.06} color={colors.fence} opacity={f.observed?.85:.4}/>)}
    {detail.trees.map(t=>t.kind==='umbrella'
      ?<group key={t.id} position={[t.at[0],0,t.at[1]]}><mesh position={[0,t.h/2,0]}><cylinderGeometry args={[.03,.03,t.h,6]}/><meshStandardMaterial color={colors.fence}/></mesh><mesh position={[0,t.h-.2,0]}><coneGeometry args={[t.r,.45,12,1,true]}/><meshStandardMaterial color={colors.paving} side={DoubleSide}/></mesh></group>
      :<group key={t.id} position={[t.at[0],0,t.at[1]]}><mesh position={[0,t.h*.2,0]}><cylinderGeometry args={[.08,.12,t.h*.4,6]}/><meshStandardMaterial color={colors.wood}/></mesh><mesh position={[0,t.h*.62,0]}><icosahedronGeometry args={[Math.max(t.r,t.h*.3),1]}/><meshStandardMaterial color={colors.tree} flatShading roughness={1}/></mesh></group>)}
  </group>;
}
