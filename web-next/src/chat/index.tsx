import {useEffect, useId, useRef, useState, useSyncExternalStore, type FormEvent, type KeyboardEvent} from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as Tabs from '@radix-ui/react-tabs';
import * as Tooltip from '@radix-ui/react-tooltip';
import {Camera, ChevronDown, FileVideo, House, Link2, MessageCircle, Plus, Send, Video, X} from 'lucide-react';
import {motion} from 'framer-motion';
import {useEntranceMotion} from '../motion';
import type {ChatMessage, ChatProps, Thread} from '../contracts';
import {Button} from '../components/ui';
import './styles.css';

/** Lead-controlled drafts keep popup/fullscreen layouts in sync. No people messaging backend. */
export type ChatSurfaceProps = ChatProps;

const narrowQuery='(max-width: 640px)';
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

function Message({message,onOpenVisit,onOpenClip,onOpenCitation}: {message:ChatMessage;onOpenVisit?:ChatProps['onOpenVisit'];onOpenClip?:ChatSurfaceProps['onOpenClip'];onOpenCitation?:ChatProps['onOpenCitation']}) {
  return <li className={`v-chat-message v-chat-message--${message.author}`}>
    <span className="v-chat-message-author">{message.author==='you'?'You':message.author==='vigil'?'Vigil':'Household'}</span>
    <div className="v-chat-bubble">
      <p>{message.text}</p>
      {message.citations.length>0 && <div className="v-chat-citations" aria-label="Evidence citations">
        {message.citations.map(citation=><button type="button" className="v-chat-citation" key={`${citation.visit_id}:${citation.event_id}`} aria-label={`Open evidence ${citation.event_id}`} disabled={!onOpenVisit&&!onOpenCitation} onClick={()=>onOpenCitation?onOpenCitation(citation):onOpenVisit?.(citation.visit_id)}><Link2 aria-hidden="true"/>{citation.event_id}</button>)}
      </div>}
      {message.clip_id && <button type="button" className="v-chat-shared-clip" aria-label={`Shared clip ${message.clip_id}`} disabled={!onOpenClip} onClick={()=>onOpenClip?.(message.clip_id!)}><FileVideo aria-hidden="true"/><span>Shared clip<span className="v-chat-clip-id">{message.clip_id}</span></span>{!onOpenClip&&<span>Playback unavailable</span>}</button>}
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

  async function submit(event?:FormEvent) {
    event?.preventDefault();
    const text=draft.trim();
    if(!text||sending||!canSend)return;
    setLocalError(null);setSubmitting(true);lastSent.current=draft;
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
  return <section className="v-chat-thread" aria-label={thread.title}>
    <header className="v-chat-thread-header"><span className="v-chat-avatar"><ThreadIcon thread={thread}/></span><div><h2>{thread.title}</h2><p>{thread.kind==='local_mock'?'Local to this browser':'Cached visit evidence'}</p></div></header>
    <div ref={historyRef} className="v-chat-history" role="log" aria-label={`${thread.title} messages`} aria-live="polite" tabIndex={0}>
      {thread.messages.length===0&&!sending?<div className="v-chat-empty"><span className="v-chat-empty-icon"><ThreadIcon thread={thread}/></span><h3>{thread.kind==='assistant'?'Ask about a visit':'No messages yet'}</h3><p>{thread.kind==='assistant'?'Search what the cameras recorded. Answers link to the visit evidence.':'Share a note or a clip with this local household thread.'}</p>{thread.kind==='local_mock'&&<p>Messages stay in this browser. They are not delivered to anyone.</p>}</div>:thread.messages.length>0&&<ol className="v-chat-message-list">{thread.messages.map(message=><Message key={message.id} message={message} onOpenCitation={props.onOpenCitation} onOpenVisit={props.onOpenVisit} onOpenClip={props.onOpenClip}/>)}</ol>}
      {sending&&<p className="v-chat-pending" role="status">{thread.kind==='assistant'?'Searching the visit ledger\u2026':'Saving your local message\u2026'}</p>}
    </div>
    <form className="v-chat-composer" onSubmit={event=>void submit(event)}>
      {(props.error||localError)&&<p className="v-chat-error" role="alert">{props.error||localError}</p>}
      {!canSend&&<p className="v-chat-capability">{thread.kind==='assistant'?'Ask your home is unavailable for this session.':'Local household messaging is unavailable for this session.'}</p>}
      <label className="v-chat-visually-hidden" htmlFor={fieldId}>Message</label>
      <div className="v-chat-input-row"><textarea id={fieldId} value={draft} onChange={event=>onDraftChange(event.target.value)} onKeyDown={onKeyDown} rows={2} disabled={!canSend||sending} maxLength={4000} placeholder={thread.kind==='assistant'?'Ask about your home':'Write a local message'} aria-describedby={`${fieldId}-help`}/><button type="submit" className="v-chat-send" aria-label="Send message" disabled={!canSend||sending||!draft.trim()}><Send aria-hidden="true"/></button></div>
      <div className="v-chat-composer-tools"><div className="v-chat-attachments"><DropdownMenu.Root><DropdownMenu.Trigger asChild><button type="button" className="v-chat-icon-button" aria-label="Share options"><Plus aria-hidden="true"/><ChevronDown aria-hidden="true"/></button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="v-chat-menu" side="top" align="start" sideOffset={visualNumber('--v-space-1')}><DropdownMenu.Label className="v-chat-menu-label">Share evidence</DropdownMenu.Label><DropdownMenu.Item className="v-chat-menu-item" disabled={!canSend||!props.onShareClip} onSelect={()=>{if(canSend)props.onShareClip?.(thread.id);}}><FileVideo aria-hidden="true"/><span>Share a clip{!canSend?<small>Messaging unavailable for this session</small>:!props.onShareClip&&<small>Clip sharing unavailable</small>}</span></DropdownMenu.Item><DropdownMenu.Item className="v-chat-menu-item" disabled={!snapshot} onSelect={()=>props.onSnapshot?.()}><Camera aria-hidden="true"/><span>Take snapshot{!snapshot&&<small>Unavailable for this session</small>}</span></DropdownMenu.Item><DropdownMenu.Item className="v-chat-menu-item" disabled={!record} onSelect={()=>props.onRecord?.()}><Video aria-hidden="true"/><span>Record clip{!record&&<small>Unavailable for this session</small>}</span></DropdownMenu.Item></DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>
      <HintButton label="Take snapshot" explanation={snapshot?'Capture the selected camera frame':'Snapshots are unavailable for this session'} disabled={!snapshot} onClick={props.onSnapshot}><Camera aria-hidden="true"/></HintButton><HintButton label="Record clip" explanation={record?'Record the selected camera clip':'Recording is unavailable for this session'} disabled={!record} onClick={props.onRecord}><Video aria-hidden="true"/></HintButton></div><p id={`${fieldId}-help`}>{'Enter to send \u00b7 Shift+Enter for a new line'}</p></div>
      {!snapshot&&!record&&<p className="v-chat-capability">Snapshots and recording are unavailable for this session.</p>}
    </form>
  </section>;
}

function ThreadWorkspace({props,popup=false}: {props:ChatSurfaceProps;popup?:boolean}) {
  const drafts=useDrafts(props);
  const narrow=useNarrowLayout();
  const selected=props.threads.find(thread=>thread.id===props.selectedThreadId)??props.threads[0];
  if(!selected)return <div className="v-chat-empty"><MessageCircle aria-hidden="true"/><h2>{props.pending?'Loading messages':props.error?'Messages unavailable':'No threads available'}</h2><p role={props.error?'alert':props.pending?'status':undefined}>{props.error||(props.pending?'Loading threads from the home box…':'Messages will appear here when a session is loaded.')}</p>{props.error&&props.onRetry&&<Button onClick={props.onRetry}>Try again</Button>}</div>;
  return <Tooltip.Provider delayDuration={visualNumber('--v-motion')}><Tabs.Root className={`v-chat-workspace${popup?' v-chat-workspace--popup':''}`} value={selected.id} onValueChange={props.onSelectThread} orientation={popup||narrow?'horizontal':'vertical'} activationMode="automatic">
    <aside className="v-chat-thread-list"><Tabs.List className="v-chat-tabs" aria-label="Message threads">{props.threads.map(thread=><Tabs.Trigger key={thread.id} value={thread.id} className="v-chat-thread-tab" aria-label={thread.title}><span className="v-chat-avatar"><ThreadIcon thread={thread}/></span><span><strong>{thread.title}</strong><small>{thread.kind==='assistant'?'Visit evidence':'Local to this browser'}</small></span></Tabs.Trigger>)}</Tabs.List>{!popup&&<p className="v-chat-thread-note">{selected.note}</p>}</aside>
    <Tabs.Content className="v-chat-tab-panel" value={selected.id} key={selected.id}><ThreadView thread={selected} props={props} draft={drafts.values[selected.id]??''} onDraftChange={text=>drafts.change(selected.id,text)}/></Tabs.Content>
  </Tabs.Root></Tooltip.Provider>;
}

export function MessagesPage(props:ChatSurfaceProps) {
  return <div className="v-chat-page"><ThreadWorkspace props={props}/></div>;
}

export function ChatPopup(props:ChatSurfaceProps) {
  const focusBeforeOpen=useRef<HTMLElement|null>(null);
  const wasOpen=useRef(false);
  const entrance=useEntranceMotion('panel',props.open?'open':'closed');
  if(props.open&&!wasOpen.current)focusBeforeOpen.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
  wasOpen.current=Boolean(props.open);
  return <Dialog.Root open={Boolean(props.open)} modal={false} onOpenChange={open=>{if(!open)props.onClose?.();}}><Dialog.Portal><Dialog.Content asChild onCloseAutoFocus={event=>{event.preventDefault();focusBeforeOpen.current?.focus();}} onInteractOutside={event=>event.preventDefault()}>
    <motion.section className="v-chat-popup" {...entrance}>
      <header className="v-chat-popup-header"><div><Dialog.Title>Messages</Dialog.Title><Dialog.Description>Ask your home or leave a local household message.</Dialog.Description></div><Dialog.Close asChild><button type="button" className="v-chat-icon-button" aria-label="Close messages"><X aria-hidden="true"/></button></Dialog.Close></header>
      <ThreadWorkspace props={props} popup/>
    </motion.section>
  </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
