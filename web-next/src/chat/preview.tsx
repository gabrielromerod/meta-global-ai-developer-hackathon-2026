import {createRoot} from 'react-dom/client';
import {useState} from 'react';
import {MessageCircle, Moon, Sun} from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '../styles/tokens.css';
import './preview.css';
import {ChatPopup, MessagesPage} from './index';
import chatFixture from '../fixtures/chat.json';
import stateFixture from '../fixtures/state.json';
import type {ChatProps, Thread} from '../contracts';

function Preview(){
  const [threads,setThreads]=useState(chatFixture.threads as Thread[]);
  const [selected,setSelected]=useState('ask-home');
  const [mode,setMode]=useState<'page'|'popup'>('page');
  const [open,setOpen]=useState(false);
  const [theme,setTheme]=useState('dark');
  const [drafts,setDrafts]=useState<Record<string,string>>({});
  const [shareThread,setShareThread]=useState<string|null>(null);
  const [notice,setNotice]=useState('');
  const props:ChatProps={threads,selectedThreadId:selected,onSelectThread:setSelected,drafts,onDraftChange:(id,text)=>setDrafts(current=>({...current,[id]:text})),onSend:(threadId,text)=>{
    setThreads(current=>current.map(thread=>thread.id===threadId?{...thread,messages:[...thread.messages,{id:crypto.randomUUID(),author:'you',text,citations:[],clip_id:null}]}:thread));
  },onShareClip:setShareThread,onOpenVisit:id=>setNotice(`Selected visit: ${id}`),onOpenClip:id=>setNotice(`Selected clip: ${id}. Playback is handled by the integrated app.`),capabilities:{ask_home:false,household_messaging:'local_mock',snapshot:false,recording:false,owner:false}};
  return <div className="v-chat-preview"><header className="v-chat-preview-header"><div><h1>Messages</h1><p>Component preview · Demo data · Ask-home backend is not connected here</p></div><div className="v-chat-preview-actions"><button type="button" onClick={()=>{setMode(mode==='page'?'popup':'page');setOpen(mode==='page');}}>{mode==='page'?'Show popup':'Show full screen'}</button><button type="button" aria-label="Change theme" onClick={()=>{const next=theme==='dark'?'light':'dark';setTheme(next);document.documentElement.dataset.theme=next;}}>{theme==='dark'?<Sun aria-hidden="true"/>:<Moon aria-hidden="true"/>}</button></div></header>
    <div className="v-chat-preview-content">{mode==='page'?<MessagesPage {...props}/>:<div className="v-chat-preview-backdrop"><h2>Messages over any page</h2><p>Switch to Household to send a local message. No messages are delivered to another person.</p></div>}</div>
    {mode==='popup'&&<><button type="button" className="v-chat-preview-pill" onClick={()=>setOpen(current=>!current)} aria-expanded={open}><MessageCircle aria-hidden="true"/>Messages</button><ChatPopup {...props} open={open} onClose={()=>setOpen(false)}/></>}
    {notice&&<p className="v-chat-preview-notice" role="status">{notice}<button type="button" onClick={()=>setNotice('')}>Dismiss</button></p>}
    <Dialog.Root open={shareThread!==null} onOpenChange={value=>{if(!value)setShareThread(null);}}><Dialog.Portal><Dialog.Overlay className="v-chat-preview-scrim"/><Dialog.Content className="v-chat-preview-picker"><Dialog.Title>Share a clip</Dialog.Title><Dialog.Description>Select from the authored demo evidence. This is local to the preview.</Dialog.Description><div className="v-chat-preview-clip-list">{stateFixture.clips.map(clip=><button type="button" key={clip.id} onClick={()=>{
      setThreads(current=>current.map(thread=>thread.id===shareThread?{...thread,messages:[...thread.messages,{id:crypto.randomUUID(),author:'you',text:clip.title,citations:[],clip_id:clip.id}]}:thread));setShareThread(null);
    }}>{clip.title}<small>{clip.clock} · {clip.source_label}</small></button>)}</div><Dialog.Close asChild><button type="button">Cancel</button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
createRoot(document.getElementById('preview-root')!).render(<Preview/>);
