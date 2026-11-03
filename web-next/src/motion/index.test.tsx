// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {useState} from 'react';
import {act, cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {MotionProvider, PageTransition, PanelTransition, useMotionPolicy, useMotionPreference,timeSeconds} from './index';

let reduced=false;
const listeners=new Set<()=>void>();
function preference(value:boolean) {act(()=>{reduced=value;for(const listener of listeners)listener();});}
beforeEach(()=>{
  reduced=false;
  vi.stubGlobal('matchMedia',vi.fn(()=>({get matches(){return reduced;},media:'(prefers-reduced-motion: reduce)',addEventListener:(_name:string,listener:()=>void)=>listeners.add(listener),removeEventListener:(_name:string,listener:()=>void)=>listeners.delete(listener),addListener:()=>{},removeListener:()=>{},dispatchEvent:()=>true})));
  for(const [name,value] of Object.entries({'--v-motion':'220ms','--v-motion-fast':'120ms','--v-motion-view':'480ms','--v-space-1':'8px','--v-space-2':'16px','--v-ease':'cubic-bezier(.2,.7,.2,1)','--v-zero':'0','--v-one':'1'}))document.documentElement.style.setProperty(name,value);
});
afterEach(()=>{cleanup();listeners.clear();vi.unstubAllGlobals();document.documentElement.removeAttribute('style');});

function Policy() {const policy=useMotionPolicy();return <output aria-label="Motion policy">{JSON.stringify(policy)}</output>;}
function readPolicy() {return JSON.parse(screen.getByLabelText('Motion policy').textContent||'{}');}

describe('Vigil motion policy',()=>{
  it('reads minified seconds and original milliseconds as the same duration',()=>{
    expect(timeSeconds('480ms')).toBe(.48);expect(timeSeconds('.48s')).toBe(.48);
    expect(timeSeconds('1600ms')).toBe(1.6);expect(timeSeconds('1.6s')).toBe(1.6);
    expect(timeSeconds('0ms')).toBe(0);expect(timeSeconds('invalid')).toBe(0);
  });
  it('honors an initial reduced preference synchronously',()=>{
    reduced=true;render(<MotionProvider><Policy/><PageTransition viewKey="home" label="Home"><button>Home control</button></PageTransition></MotionProvider>);
    expect(readPolicy().reduced).toBe(true);
    expect(readPolicy().duration).toBe(0);
    expect(readPolicy().offset).toBe(0);
    expect(screen.getByRole('region',{name:'Home'})).toContainElement(screen.getByRole('button',{name:'Home control'}));
  });
  it('updates when preference changes in both directions without remounting child state',async()=>{
    function Counter(){const [value,setValue]=useState(0);return <button onClick={()=>setValue(v=>v+1)}>Count {value}</button>;}
    const user=userEvent.setup();render(<MotionProvider><Policy/><Counter/></MotionProvider>);
    await user.click(screen.getByRole('button',{name:'Count 0'}));
    preference(true);expect(readPolicy().reduced).toBe(true);expect(readPolicy().duration).toBe(0);
    preference(false);expect(readPolicy().reduced).toBe(false);expect(readPolicy().duration).toBe(.22);
    expect(screen.getByRole('button',{name:'Count 1'})).toBeInTheDocument();
  });
  it('uses the token durations, offset and easing rather than component constants',()=>{
    render(<MotionProvider><Policy/></MotionProvider>);
    expect(readPolicy()).toMatchObject({duration:.22,fastDuration:.12,viewDuration:.48,offset:8,panelOffset:16,ease:[.2,.7,.2,1]});
  });
  it('cleans up native preference subscriptions when unmounted',()=>{
    function Probe(){useMotionPreference();return null;}
    const {unmount}=render(<Probe/>);expect(listeners.size).toBe(1);unmount();expect(listeners.size).toBe(0);
  });
  it('stops an in-flight transform when reduced motion becomes enabled',async()=>{
    render(<MotionProvider><PageTransition viewKey="home" label="Home"><p>Visible evidence</p></PageTransition></MotionProvider>);
    const animated=screen.getByRole('region',{name:'Home'}).firstElementChild!;
    expect(getComputedStyle(animated).transform).toContain('translateY');
    preference(true);
    await act(async()=>{await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
    expect(getComputedStyle(animated).transform).toBe('none');
  });
});

describe('View and panel transitions',()=>{
  it('leaves navigation focus on its stable trigger across route changes',async()=>{
    function Routes(){const [route,setRoute]=useState('home');return <MotionProvider><button onClick={()=>setRoute('attention')}>Attention navigation</button><PageTransition viewKey={route} label={route}><button>{route} control</button></PageTransition></MotionProvider>;}
    const user=userEvent.setup();render(<Routes/>);
    await user.click(screen.getByRole('button',{name:'Attention navigation'}));
    expect(screen.getByRole('button',{name:'Attention navigation'})).toHaveFocus();
    expect(screen.getByRole('button',{name:'attention control'})).toBeVisible();
    expect(screen.queryByRole('button',{name:'home control'})).not.toBeInTheDocument();
  });
  it('moves focus to the new region only when a focused outgoing control is removed',()=>{
    const {rerender}=render(<MotionProvider><PageTransition viewKey="home" label="Home"><button>Outgoing action</button></PageTransition></MotionProvider>);
    screen.getByRole('button',{name:'Outgoing action'}).focus();
    rerender(<MotionProvider><PageTransition viewKey="attention" label="Attention"><p>Attention evidence</p></PageTransition></MotionProvider>);
    expect(screen.getByRole('region',{name:'Attention'})).toHaveFocus();
  });
  it('keeps only one route tree during rapid changes and cancels old mount work',()=>{
    reduced=true;let mounts=0,unmounts=0;
    function Content({name}:{name:string}){useState(()=>{mounts++;return 0;});return <span ref={node=>{if(node===null)unmounts++;}}>{name}</span>;}
    const {rerender,unmount}=render(<MotionProvider><PageTransition viewKey="one"><Content name="one"/></PageTransition></MotionProvider>);
    for(const name of ['two','three','four'])rerender(<MotionProvider><PageTransition viewKey={name}><Content name={name}/></PageTransition></MotionProvider>);
    expect(screen.getByText('four')).toBeInTheDocument();expect(screen.queryByText('one')).not.toBeInTheDocument();expect(screen.queryByText('two')).not.toBeInTheDocument();
    expect(mounts).toBe(4);unmount();expect(unmounts).toBe(4);
  });
  it('removes closing panel controls from accessibility and never duplicates reopened content',()=>{
    reduced=true;
    const {rerender}=render(<MotionProvider><PanelTransition open label="Visit panel"><button>Panel action</button></PanelTransition></MotionProvider>);
    rerender(<MotionProvider><PanelTransition open={false} label="Visit panel"><button>Panel action</button></PanelTransition></MotionProvider>);
    expect(screen.queryByRole('button',{name:'Panel action'})).not.toBeInTheDocument();
    rerender(<MotionProvider><PanelTransition open label="Visit panel"><button>Panel action</button></PanelTransition></MotionProvider>);
    expect(screen.getAllByRole('button',{name:'Panel action'})).toHaveLength(1);
  });
  it('unmounts an ordinary-motion closing panel after its library-managed exit',async()=>{
    const {rerender}=render(<MotionProvider><PanelTransition open label="Evidence panel"><span>Closing evidence</span></PanelTransition></MotionProvider>);
    rerender(<MotionProvider><PanelTransition open={false} label="Evidence panel"><span>Closing evidence</span></PanelTransition></MotionProvider>);
    await waitFor(()=>expect(screen.queryByText('Closing evidence')).not.toBeInTheDocument());
  });
  it('shows one visible panel when reopened before an ordinary-motion exit finishes',async()=>{
    const tree=(open:boolean)=><MotionProvider><PanelTransition open={open} label="Evidence panel"><button>Evidence action</button></PanelTransition></MotionProvider>;
    const {rerender}=render(tree(true));
    rerender(tree(false));
    await act(async()=>{await new Promise(resolve=>requestAnimationFrame(resolve));});
    rerender(tree(true));
    await waitFor(()=>expect(screen.getByRole('button',{name:'Evidence action'})).toBeVisible());
    expect(screen.getAllByRole('button',{name:'Evidence action'})).toHaveLength(1);
  });
});
