import {createContext, useContext, useLayoutEffect, useRef, useSyncExternalStore, type ReactNode} from 'react';
import {AnimatePresence, MotionConfig, motion, useAnimationControls, useIsPresent, type Transition} from 'framer-motion';
import './motion.css';

const preferenceQuery='(prefers-reduced-motion: reduce)';
const preferenceSubscribers=new Set<()=>void>();
let removePreferenceListener:(()=>void)|undefined;
function subscribePreference(callback:()=>void) {
  preferenceSubscribers.add(callback);
  if(!removePreferenceListener&&typeof window!=='undefined'&&typeof window.matchMedia==='function') {
    const media=window.matchMedia(preferenceQuery);
    const update=()=>{for(const notify of preferenceSubscribers)notify();};
    if(typeof media.addEventListener==='function') {
      media.addEventListener('change',update);
      removePreferenceListener=()=>media.removeEventListener('change',update);
    } else {
      media.addListener(update);
      removePreferenceListener=()=>media.removeListener(update);
    }
  }
  return ()=>{
    preferenceSubscribers.delete(callback);
    if(preferenceSubscribers.size===0){removePreferenceListener?.();removePreferenceListener=undefined;}
  };
}
function preferenceSnapshot() {
  return typeof window==='undefined'||typeof window.matchMedia!=='function'
    ? true : window.matchMedia(preferenceQuery).matches;
}

/** The installed Motion 14.9 hook is initial-only; native subscription supplies changes. */
export function useMotionPreference():boolean {
  return useSyncExternalStore(subscribePreference,preferenceSnapshot,()=>true);
}

export interface MotionPolicy {
  reduced:boolean;duration:number;fastDuration:number;viewDuration:number;
  offset:number;panelOffset:number;ease:[number,number,number,number]|'linear';
  zero:number;one:number;
}
const PolicyContext=createContext<MotionPolicy|null>(null);
function policyFromTokens(reduced:boolean):MotionPolicy {
  const style=typeof document==='undefined'?null:getComputedStyle(document.documentElement);
  const value=(name:string)=>style?.getPropertyValue(name).trim()||'';
  const number=(name:string)=>{const parsed=parseFloat(value(name));return Number.isFinite(parsed)?parsed:0;};
  const seconds=(name:string)=>{const raw=value(name);return Math.max(0,number(name)/(raw.endsWith('ms')?1000:1));};
  const bezier=value('--v-ease').match(/^cubic-bezier\(([^)]+)\)$/)?.[1].split(',').map(part=>Number(part.trim()));
  const ease=bezier?.length===4&&bezier.every(Number.isFinite)?bezier as [number,number,number,number]:'linear';
  return {
    reduced,duration:reduced?0:seconds('--v-motion'),fastDuration:reduced?0:seconds('--v-motion-fast'),
    viewDuration:reduced?0:seconds('--v-motion-view'),offset:reduced?0:number('--v-space-1'),
    panelOffset:reduced?0:number('--v-space-2'),ease,zero:number('--v-zero'),one:number('--v-one')||1,
  };
}

/** Mount once above the shell. Preference changes preserve child identity and local state. */
export function MotionProvider({children}:{children:ReactNode}) {
  const reduced=useMotionPreference();
  const policy=policyFromTokens(reduced);
  return <PolicyContext.Provider value={policy}><MotionConfig reducedMotion={reduced?'always':'never'} transition={{duration:policy.duration,ease:policy.ease}}>{children}</MotionConfig></PolicyContext.Provider>;
}

export function useMotionPolicy():MotionPolicy {
  const provided=useContext(PolicyContext);
  const reduced=useMotionPreference();
  return provided??policyFromTokens(reduced);
}

/** Spread onto an existing motion element; no data selection or repeated decoration. */
export function useEntranceMotion(kind:'view'|'panel'='panel',identity?:string) {
  const policy=useMotionPolicy();
  const controls=useAnimationControls();
  // New route controls stay visible and focusable from the first committed frame.
  const initial=policy.reduced?false:{opacity:kind==='view'?policy.one:policy.zero,y:kind==='view'?policy.offset:policy.panelOffset};
  const transition:Transition={duration:kind==='view'?policy.viewDuration:policy.duration,ease:policy.ease};
  const duration=transition.duration;
  const ease=JSON.stringify(policy.ease);
  useLayoutEffect(()=>{
    const target={opacity:policy.one,y:policy.zero};
    if(policy.reduced){controls.stop();controls.set(target);}
    else void controls.start({...target,transition:{duration,ease:policy.ease}});
    return ()=>controls.stop();
  },[controls,identity,policy.reduced,policy.one,policy.zero,duration,ease]);
  return {initial,animate:controls,transition};
}

export interface PageTransitionProps {viewKey:string;label?:string;className?:string;children:ReactNode}
export function PageTransition({viewKey,label,className='',children}:PageTransitionProps) {
  const container=useRef<HTMLDivElement>(null);
  const previousKey=useRef(viewKey);
  const restoreFocus=previousKey.current!==viewKey&&Boolean(container.current?.contains(document.activeElement));
  const entrance=useEntranceMotion('view',viewKey);
  useLayoutEffect(()=>{
    previousKey.current=viewKey;
    // Keep a stable navigation trigger focused; recover only a removed route control.
    if(restoreFocus&&(document.activeElement===document.body||!document.activeElement?.isConnected))
      container.current?.focus({preventScroll:true});
  },[viewKey,restoreFocus]);
  return <div ref={container} tabIndex={-1} role={label?'region':undefined} aria-label={label} className={`v-motion-frame ${className}`}>
    <motion.div key={viewKey} className="v-motion-view" {...entrance}>{children}</motion.div>
  </div>;
}

export function PanelEntrance({children,className=''}:{children:ReactNode;className?:string}) {
  const entrance=useEntranceMotion();
  return <motion.div className={`v-motion-panel ${className}`} {...entrance}>{children}</motion.div>;
}

function PresenceContent({label,children,className}:{label:string;children:ReactNode;className:string}) {
  const present=useIsPresent();
  const policy=useMotionPolicy();
  const entrance=useEntranceMotion();
  return <motion.div className={`v-motion-panel ${className}`} role="region" aria-label={label}
    inert={!present} aria-hidden={!present} {...entrance}
    exit={{opacity:policy.zero,y:policy.zero,transition:{duration:policy.fastDuration,ease:policy.ease}}}>
    {children}
  </motion.div>;
}

/** For inline panels only. Radix continues to own popup/dialog presence and focus. */
export function PanelTransition({open,label,children,className=''}:{open:boolean;label:string;children:ReactNode;className?:string}) {
  return <AnimatePresence initial={false} mode="wait">{open&&<PresenceContent key="panel" label={label} className={className}>{children}</PresenceContent>}</AnimatePresence>;
}
