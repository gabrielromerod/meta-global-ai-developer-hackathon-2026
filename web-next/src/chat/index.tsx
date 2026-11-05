import {forwardRef, useEffect, useId, useRef, useState, useSyncExternalStore, type ComponentPropsWithoutRef, type FormEvent, type KeyboardEvent} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as Tabs from '@radix-ui/react-tabs';
import * as Tooltip from '@radix-ui/react-tooltip';
import {ArrowUp, Camera, FileVideo, House, Link2, MessageCircle, Plus, Sparkles, Video, X} from 'lucide-react';
import {motion} from 'framer-motion';
import {useEntranceMotion} from '../motion';
import type {ChatMessage, ChatProps, Thread} from '../contracts';
import {Button} from '../components/ui';
import './styles.css';

/** Lead-controlled drafts keep popup/fullscreen layouts in sync. No people messaging backend. */
export type ChatSurfaceProps = ChatProps;

const narrowQuery='(max-width: 640px)';
const STARTERS=[{text:'What happened at the side gate tonight?',note:'Answers cite the recorded events, with a link to each one.'},{text:'Has anyone been on the property more than once?',note:'Searches recorded visits; profiles and names are never sent to a model.'}];
const REAL_NOTE='Answers come from your analysed clips.';
/** Real-only home box: questions its analysed clips can answer (the front cameras today). */
const REAL_STARTERS=[{text:'Who came into the front garden?',note:'Answers cite your analysed clips, with a link to each one.'},{text:'Has anyone been on the property more than once?',note:'Grouped by clothing on this home box; profiles and names are never sent to a model.'}];
const SUGGESTIONS=['Who came to the porch today?','Did anything need my attention?'];
function visualNumber(name:string) {
  return parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name))||0;
}
function useNarrowLayout() {
  return useSyncExternalStore(callback=>{
    const query=window.matchMedia?.(narrowQuery);
    query?.addEventListener('change',callback);
    return ()=>query?.removeEventListener('change',callback);
  },()=>window.matchMedia?.(narrowQuery).matches??false,()=>false);
}

function useDrafts(props: ChatSurfaceProps) {
  const [local,setLocal]=useState<Record<string,string>>({});
  return {
    values: props.drafts ?? local,
    change: (id:string,text:string)=> {
      if (props.onDraftChange) props.onDraftChange(id,text);
      else setLocal(current=>({...current,[id]:text}));
    },
  };
}

function ThreadIcon({thread}: {thread:Thread}) {
  return thread.kind==='assistant' ? <House aria-hidden="true"/> : <MessageCircle aria-hidden="true"/>;
}

/** A real-only answer cites a recorded clip of this home (`capture_id`), not a demo visit. */
export interface ClipCitation {capture_id:string;event_id:string|null;label?:string}
export function clipCitation(citation:unknown):ClipCitation|null {
  const c=citation as Partial<ClipCitation>|null;
  return c&&typeof c.capture_id==='string'&&c.capture_id?{capture_id:c.capture_id,event_id:typeof c.event_id==='string'?c.event_id:null,...(typeof c.label==='string'&&c.label?{label:c.label}:{})}:null;
}
/** Short readable label for a capture id like `front_left_duo-<hash>-<hash>`. */
export function clipLabel(captureId:string){return captureId.split('-')[0].replace(/_/g,' ')+' clip';}
/** The Media library opens the clip named in `?capture=` (HashRouter). */
export function openCaptureClip(captureId:string){window.location.hash=`#/clips?capture=${encodeURIComponent(captureId)}`;}

function Message({message,onOpenVisit,onOpenClip,onOpenCitation}: {message:ChatMessage;onOpenVisit?:ChatProps['onOpenVisit'];onOpenClip?:ChatSurfaceProps['onOpenClip'];onOpenCitation?:ChatProps['onOpenCitation']}) {
  const author=message.author==='you'?'You':message.author==='vigil'?'Vigil':'Household';
  return <li className={`v-chat-message v-chat-message--${message.author}`}>
    {message.author!=='you'&&<span className="v-chat-message-avatar" aria-hidden="true">{message.author==='vigil'?<House/>:<MessageCircle/>}</span>}
    <div className="v-chat-message-body">
      <span className={message.author==='you'?'v-chat-visually-hidden':'v-chat-message-author'}>{author}</span>
      <div className="v-chat-bubble"><p>{message.text}</p></div>
      {message.citations.length>0 && <div className="v-chat-citations" aria-label="Evidence citations">
        {message.citations.map((citation,i)=>{const clip=clipCitation(citation);
          return clip?<button type="button" className="v-chat-citation" key={`${clip.capture_id}:${clip.event_id}:${i}`} aria-label={`Open clip ${clip.label??clipLabel(clip.capture_id)}`} onClick={()=>openCaptureClip(clip.capture_id)}><Link2 aria-hidden="true"/>{clip.label??clip.event_id??clipLabel(clip.capture_id)}</button>
          :<button type="button" className="v-chat-citation" key={`${citation.visit_id}:${citation.event_id}`} aria-label={`Open evidence ${citation.event_id}`} disabled={!onOpenVisit&&!onOpenCitation} onClick={()=>onOpenCitation?onOpenCitation(citation):onOpenVisit?.(citation.visit_id)}><Link2 aria-hidden="true"/>{citation.event_id}</button>;})}
      </div>}
      {message.clip_id && <button type="button" className="v-chat-shared-clip" aria-label={`Shared clip ${message.clip_id}`} disabled={!onOpenClip} onClick={()=>onOpenClip?.(message.clip_id!)}><span className="v-chat-shared-clip-icon" aria-hidden="true"><FileVideo/></span><span>Shared clip<span className="v-chat-clip-id">{message.clip_id}</span></span>{!onOpenClip&&<span className="v-chat-clip-id">Playback unavailable</span>}</button>}
    </div>
  </li>;
}

function HintButton({label,explanation,disabled,onClick,children}: {label:string;explanation:string;disabled:boolean;onClick?:()=>void;children:React.ReactNode}) {
  return <Tooltip.Root><Tooltip.Trigger asChild><span className="v-chat-control-wrap" tabIndex={disabled?0:undefined} aria-label={disabled?`${label}: ${explanation}`:undefined}>
    <button type="button" className="v-chat-icon-button" aria-label={label} title={explanation} disabled={disabled} onClick={onClick}>{children}</button>
  </span></Tooltip.Trigger><Tooltip.Portal><Tooltip.Content className="v-chat-tooltip" sideOffset={visualNumber('--v-space-1')}>{explanation}<Tooltip.Arrow className="v-chat-tooltip-arrow"/></Tooltip.Content></Tooltip.Portal></Tooltip.Root>;
}

function ThreadView({thread,props,draft,onDraftChange}: {thread:Thread;props:ChatSurfaceProps;draft:string;onDraftChange:(text:string)=>void}) {
  const fieldId=useId();
  const historyRef=useRef<HTMLDivElement>(null);
  const lastSent=useRef('');
  const [submitting,setSubmitting]=useState(false);
  const [localError,setLocalError]=useState<string|null>(null);
  const sending=Boolean(props.pending||submitting);
  const supported=thread.kind==='assistant'?props.capabilities.ask_home:props.capabilities.household_messaging==='local_mock';
  const canSend=supported&&typeof props.onSend==='function';
  const snapshot=props.capabilities.snapshot&&Boolean(props.onSnapshot);
  const record=props.capabilities.recording&&Boolean(props.onRecord);
  useEffect(()=>{
    const history=historyRef.current;
    if(!history||(!thread.messages.length&&!sending))return;
    const scrollToLatest=()=>{history.scrollTop=history.scrollHeight;};
    scrollToLatest();
    // Font loading and popup layout can change the measured content after mount.
    // Observe both the scroll panel and its contents so pending feedback stays visible.
    if(typeof ResizeObserver==='undefined')return;
    const observer=new ResizeObserver(scrollToLatest);
    observer.observe(history);
    for(const child of history.children)observer.observe(child);
    return ()=>observer.disconnect();
  },[thread.id,thread.messages.length,sending]);
  useEffect(()=>{
    if(props.error&&lastSent.current&&!draft)onDraftChange(lastSent.current);
  },[props.error]); // Restore a failed submission; lead may keep this draft controlled.

  async function submit(event?:FormEvent,override?:string) {
    event?.preventDefault();
    const text=(override??draft).trim();
    if(!text||sending||!canSend)return;
    setLocalError(null);setSubmitting(true);lastSent.current=override??draft;
    try {
      const result=props.onSend(thread.id,text) as void|Promise<void>;
      if(result&&typeof result.then==='function')await result;
      onDraftChange('');
    } catch {
      setLocalError('The message could not be sent. Your draft has been kept.');
    } finally {setSubmitting(false);}
  }
  function onKeyDown(event:KeyboardEvent<HTMLTextAreaElement>) {
    if(event.key==='Enter'&&!event.shiftKey&&!event.nativeEvent.isComposing){event.preventDefault();void submit();}
  }
  const assistant=thread.kind==='assistant';
  const hints=[!canSend?(assistant?'Ask your home is unavailable for this session.':'Local household messaging is unavailable for this session.'):null,!snapshot&&!record?'Snapshots and recording are unavailable for this session.':null].filter(Boolean) as string[];
  return <section className="v-chat-thread" aria-label={thread.title}>
    <header className="v-chat-thread-header"><span className="v-chat-avatar"><ThreadIcon thread={thread}/></span><div><h2>{thread.title}</h2><p>{thread.kind==='local_mock'?'Local to this browser':thread.note===REAL_NOTE?thread.note:'Answers cite cached visit evidence'}</p></div></header>
    <div ref={historyRef} className="v-chat-history" role="log" aria-label={`${thread.title} messages`} aria-live="polite" tabIndex={0}>
      <div className="v-chat-column">
      {thread.messages.length===0&&!sending?<div className="v-chat-empty">
        <span className="v-chat-empty-icon"><ThreadIcon thread={thread}/></span>
        <h3>{assistant?'Ask about your home':'No messages yet'}</h3>
        <p>{assistant?'Search what the cameras recorded. Every answer links to the visit evidence.':'Share a note or a clip with this local household thread.'}</p>
        {assistant&&<div className="v-chat-starters" aria-label="Start with a question">{(thread.note===REAL_NOTE?REAL_STARTERS:STARTERS).map(starter=><button type="button" key={starter.text} className="v-chat-starter" disabled={!canSend||sending} onClick={()=>void submit(undefined,starter.text)}><MessageCircle aria-hidden="true"/><span><strong>{starter.text}</strong><small>{starter.note}</small></span><ArrowUp aria-hidden="true" className="v-chat-starter-go"/></button>)}</div>}
        {assistant&&<div className="v-chat-suggestions" aria-label="Suggested questions">{SUGGESTIONS.map(text=><button type="button" key={text} className="v-chat-suggestion" disabled={!canSend||sending} onClick={()=>onDraftChange(text)}><Sparkles aria-hidden="true"/>{text}</button>)}</div>}
        {thread.kind==='local_mock'&&<p className="v-chat-fine">Messages stay in this browser. They are not delivered to anyone.</p>}
      </div>:thread.messages.length>0&&<ol className="v-chat-message-list">{thread.messages.map(message=><Message key={message.id} message={message} onOpenCitation={props.onOpenCitation} onOpenVisit={props.onOpenVisit} onOpenClip={props.onOpenClip}/>)}</ol>}
      {sending&&<p className="v-chat-pending" role="status"><span className="v-chat-dots" aria-hidden="true"><i/><i/><i/></span>{assistant?'Searching the visit ledger\u2026':'Saving your local message\u2026'}</p>}
      </div>
    </div>
    <form className="v-chat-composer" onSubmit={event=>void submit(event)}>
      <div className="v-chat-column">
      {(props.error||localError)&&<p className="v-chat-error" role="alert">{props.error||localError}</p>}
      <label className="v-chat-visually-hidden" htmlFor={fieldId}>Message</label>
      <div className="v-chat-pill">
        <DropdownMenu.Root><DropdownMenu.Trigger asChild><button type="button" className="v-chat-icon-button" aria-label="Share options"><Plus aria-hidden="true"/></button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="v-chat-menu" side="top" align="start" sideOffset={visualNumber('--v-space-1')}><DropdownMenu.Label className="v-chat-menu-label">Share evidence</DropdownMenu.Label><DropdownMenu.Item className="v-chat-menu-item" disabled={!canSend||!props.onShareClip} onSelect={()=>{if(canSend)props.onShareClip?.(thread.id);}}><FileVideo aria-hidden="true"/><span>Share a clip{!canSend?<small>Messaging unavailable for this session</small>:!props.onShareClip&&<small>Clip sharing unavailable</small>}</span></DropdownMenu.Item><DropdownMenu.Item className="v-chat-menu-item" disabled={!snapshot} onSelect={()=>props.onSnapshot?.()}><Camera aria-hidden="true"/><span>Take snapshot{!snapshot&&<small>Unavailable for this session</small>}</span></DropdownMenu.Item><DropdownMenu.Item className="v-chat-menu-item" disabled={!record} onSelect={()=>props.onRecord?.()}><Video aria-hidden="true"/><span>Record clip{!record&&<small>Unavailable for this session</small>}</span></DropdownMenu.Item></DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>
        <textarea id={fieldId} value={draft} onChange={event=>onDraftChange(event.target.value)} onKeyDown={onKeyDown} rows={1} disabled={!canSend||sending} maxLength={4000} placeholder={assistant?'Ask about your home':'Write a local message'} aria-describedby={`${fieldId}-help`}/>
        <HintButton label="Take snapshot" explanation={snapshot?'Capture the selected camera frame':'Snapshots are unavailable for this session'} disabled={!snapshot} onClick={props.onSnapshot}><Camera aria-hidden="true"/></HintButton>
        <HintButton label="Record clip" explanation={record?'Record the selected camera clip':'Recording is unavailable for this session'} disabled={!record} onClick={props.onRecord}><Video aria-hidden="true"/></HintButton>
        <button type="submit" className="v-chat-send" aria-label="Send message" disabled={!canSend||sending||!draft.trim()}><ArrowUp aria-hidden="true"/></button>
      </div>
      <div className="v-chat-hints"><p id={`${fieldId}-help`}>{'Enter to send \u00b7 Shift+Enter for a new line'}</p>{hints.map(hint=><p key={hint} className="v-chat-capability">{hint}</p>)}</div>
      </div>
    </form>
  </section>;
}

function ThreadWorkspace({props,popup=false}: {props:ChatSurfaceProps;popup?:boolean}) {
  const drafts=useDrafts(props);
  const narrow=useNarrowLayout();
  const selected=props.threads.find(thread=>thread.id===props.selectedThreadId)??props.threads[0];
  if(!selected)return <div className="v-chat-empty"><MessageCircle aria-hidden="true"/><h2>{props.pending?'Loading messages':props.error?'Messages unavailable':'No threads available'}</h2><p role={props.error?'alert':props.pending?'status':undefined}>{props.error||(props.pending?'Loading threads from the home box…':'Messages will appear here when a session is loaded.')}</p>{props.error&&props.onRetry&&<Button onClick={props.onRetry}>Try again</Button>}</div>;
  return <Tooltip.Provider delayDuration={visualNumber('--v-motion')}><Tabs.Root className={`v-chat-workspace${popup?' v-chat-workspace--popup':''}`} value={selected.id} onValueChange={props.onSelectThread} orientation={popup||narrow?'horizontal':'vertical'} activationMode="automatic">
    <aside className="v-chat-thread-list"><Tabs.List className="v-chat-tabs" aria-label="Message threads">{props.threads.map(thread=><Tabs.Trigger key={thread.id} value={thread.id} className="v-chat-thread-tab" aria-label={thread.title}><span className="v-chat-avatar"><ThreadIcon thread={thread}/></span><span><strong>{thread.title}</strong><small>{thread.kind==='assistant'?(thread.note===REAL_NOTE?'Your clips':'Visit evidence'):'Local to this browser'}</small></span></Tabs.Trigger>)}</Tabs.List>{!popup&&<p className="v-chat-thread-note">{selected.note}</p>}</aside>
    <Tabs.Content className="v-chat-tab-panel" value={selected.id} key={selected.id}><ThreadView thread={selected} props={props} draft={drafts.values[selected.id]??''} onDraftChange={text=>drafts.change(selected.id,text)}/></Tabs.Content>
  </Tabs.Root></Tooltip.Provider>;
}

export function MessagesPage(props:ChatSurfaceProps) {
  return <div className="v-chat-page"><ThreadWorkspace props={props}/></div>;
}

const PopupPanel=forwardRef<HTMLElement,ComponentPropsWithoutRef<typeof motion.section>&{chat:ChatSurfaceProps}>(({chat,...contentProps},ref)=>{
  const entrance=useEntranceMotion();
  return <motion.section {...contentProps} ref={ref} className="v-chat-popup" {...entrance}>
    <header className="v-chat-popup-header"><div><Dialog.Title>Messages</Dialog.Title><Dialog.Description>Ask your home or leave a local household message.</Dialog.Description></div><Dialog.Close asChild><button type="button" className="v-chat-icon-button" aria-label="Close messages"><X aria-hidden="true"/></button></Dialog.Close></header>
    <ThreadWorkspace props={chat} popup/>
  </motion.section>;
});
PopupPanel.displayName='PopupPanel';

export function ChatPopup(props:ChatSurfaceProps) {
  const focusBeforeOpen=useRef<HTMLElement|null>(null);
  const wasOpen=useRef(false);
  if(props.open&&!wasOpen.current)focusBeforeOpen.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
  wasOpen.current=Boolean(props.open);
  return <Dialog.Root open={Boolean(props.open)} modal={false} onOpenChange={open=>{if(!open)props.onClose?.();}}><Dialog.Portal><Dialog.Content asChild onCloseAutoFocus={event=>{event.preventDefault();focusBeforeOpen.current?.focus();}} onInteractOutside={event=>event.preventDefault()}><PopupPanel chat={props}/></Dialog.Content></Dialog.Portal></Dialog.Root>;
}
