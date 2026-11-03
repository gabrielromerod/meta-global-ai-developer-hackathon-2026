// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {useMotionPreference} from './index';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});

it('registers only one reduced-motion listener across both query forms and removes it on unmount',()=>{
  const listeners=new Map<string,Set<unknown>>();
  vi.stubGlobal('matchMedia',(query:string)=>{
    const active=()=>{if(!listeners.has(query))listeners.set(query,new Set());return listeners.get(query)!;};
    return {matches:false,media:query,
      addEventListener:(type:string,listener:unknown)=>{if(type==='change')active().add(listener);},
      removeEventListener:(type:string,listener:unknown)=>{if(type==='change')active().delete(listener);},
      addListener:(listener:unknown)=>active().add(listener),removeListener:(listener:unknown)=>active().delete(listener)};
  });
  const count=()=>[...listeners].filter(([query])=>query.includes('prefers-reduced-motion')).reduce((total,[,active])=>total+active.size,0);
  function Probe(){return <output>{String(useMotionPreference())}</output>;}
  const baseline=count(),{unmount}=render(<><Probe/><Probe/></>),mounted=count();
  unmount();
  expect({baseline,mounted,unmounted:count()}).toEqual({baseline:0,mounted:1,unmounted:0});
});

it('conservatively reduces motion when native preference support is unavailable',()=>{
  vi.stubGlobal('matchMedia',undefined);
  function Probe(){return <output aria-label="Reduced preference">{String(useMotionPreference())}</output>;}
  render(<Probe/>);
  expect(screen.getByLabelText('Reduced preference')).toHaveTextContent('true');
});
