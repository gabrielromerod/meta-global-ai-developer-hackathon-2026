/** QA-only component harness. All incoming text is existing authored fixture evidence. */
import {createRoot} from 'react-dom/client';
import {useState} from 'react';
import '@fontsource/inter/400.css';
import '../styles/tokens.css';
import './preview.css';
import {ChatPopup,MessagesPage} from './index';
import chatFixture from '../fixtures/chat.json';
import stateFixture from '../fixtures/state.json';
import type {ChatProps,Thread} from '../contracts';

const query=new URLSearchParams(location.search);
function ReviewPreview(){
  const [selected,setSelected]=useState(query.get('thread')||'household');
  const [open,setOpen]=useState(query.get('popup')==='1');
  const [pending,setPending]=useState(query.get('pending')==='1');
  const [drafts,setDrafts]=useState<Record<string,string>>({});
  const populated=query.get('messages')==='1';
  const event=stateFixture.events[0];
  const visit=stateFixture.visits.find(item=>item.id===event.visit_id)!;
  const threads:Thread[]=(chatFixture.threads as Thread[]).map(thread=>({...thread,messages:populated&&thread.id===selected?[{id:'qa-existing-evidence',author:'vigil',text:visit.story,citations:[{visit_id:visit.id,event_id:event.event_id}],clip_id:null}]:[]}));
  const props:ChatProps={threads,selectedThreadId:selected,onSelectThread:setSelected,onSend:()=>{},drafts,onDraftChange:(id,text)=>setDrafts(current=>({...current,[id]:text})),pending,onOpenVisit:()=>{},capabilities:{ask_home:true,household_messaging:'local_mock',snapshot:false,recording:false,owner:false}};
  return <div className="v-chat-preview"><header className="v-chat-preview-header"><div><h1>Chat regression harness</h1><p>Generated test state from authored fixture evidence. No backend or messages are sent.</p></div><div className="v-chat-preview-actions"><button type="button" onClick={()=>setOpen(current=>!current)}>Toggle popup</button><button type="button" onClick={()=>setPending(current=>!current)}>Toggle pending</button></div></header><div className="v-chat-preview-content"><MessagesPage {...props}/></div><ChatPopup {...props} open={open} onClose={()=>setOpen(false)}/></div>;
}
createRoot(document.getElementById('chat-review-root')!).render(<ReviewPreview/>);
