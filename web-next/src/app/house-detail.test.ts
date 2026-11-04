import {describe,expect,it} from 'vitest';
import {parseDetail,roofHeightAt,roofTriangles,type Roof} from './house-detail';

const roof=(type:Roof['type'],rise=1):Roof=>({id:'r',type,min:[0,0],max:[10,6],eave:2.8,rise,overhang:0});
const ys=(points:number[])=>points.filter((_,i)=>i%3===1);

describe('private house massing rendering', () => {
  it('builds closed roofs whose ridge sits at eave plus rise and whose eaves stay level', () => {
    for (const type of ['hip','gable_x','gable_z'] as const) {
      const points=roofTriangles(roof(type));
      expect(points.length%9).toBe(0);
      expect(Math.max(...ys(points))).toBeCloseTo(3.8);
      expect(Math.min(...ys(points))).toBeCloseTo(2.8);
    }
    const hip=roofTriangles(roof('hip'));
    expect(hip.length/9).toBe(6); // two trapezoids (4 triangles) and two hip ends
  });
  it('falls back to a flat slab and ignores the public diagram without detail', () => {
    expect(new Set(ys(roofTriangles(roof('flat',0))))).toEqual(new Set([2.8+.15]));
    expect(parseDetail({site_plan:{boxes:[]}})).toBeNull();
    const detail=parseDetail({detail:{roofs:[{id:'a',type:'dome',min:[0,0],max:[1,1]}],surfaces:[{id:'s',min:[0,0],max:[1,1]}],fences:[{id:'f',from:[0,0],to:[1,0],observed:false}]}});
    expect(detail?.roofs[0].type).toBe('flat');
    expect(detail?.surfaces[0].kind).toBe('paving');
    expect(detail?.fences[0].observed).toBe(false);
  });
  it('places solar panels on the roof slope, highest at the ridge', () => {
    const r=roof('gable_z');
    expect(roofHeightAt(r,5,3)).toBeCloseTo(3.8);
    expect(roofHeightAt(r,0,3)).toBeCloseTo(2.8);
    expect(roofHeightAt(r,2.5,3)).toBeCloseTo(3.3);
    expect(roofHeightAt(r,20,3)).toBe(2.8);
    expect(parseDetail({detail:{solar:[{id:'a',min:[0,0],max:[1,2]}]}})?.solar[0].max).toEqual([1,2]);
  });
});
