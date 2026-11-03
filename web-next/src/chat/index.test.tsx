// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {useState} from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {ChatPopup, MessagesPage} from './index';
import type {ChatProps, Thread} from '../contracts';

const threads: Thread[] = [
  {id:'ask-home',title:'Ask your home',kind:'assistant',note:'Answers use the cached visit ledger.',messages:[]},
  {id:'household',title:'Household',kind:'local_mock',note:'Messages stay in this browser.',messages:[]},
];
const capabilities = {ask_home:true,household_messaging:'local_mock',snapshot:false,recording:false,owner:false};
const base: ChatProps = {threads,selectedThreadId:'ask-home',onSelectThread:()=>{},onSend:()=>{},capabilities};
afterEach(cleanup);

function Harness({pending=false}: {pending?:boolean}) {
  const [items,setItems]=useState(threads);
  const [selected,setSelected]=useState('ask-home');
  return <MessagesPage {...base} threads={items} selectedThreadId={selected} pending={pending} onSelectThread={setSelected} onSend={(id,text)=>setItems(current=>current.map(thread=>thread.id===id?{...thread,messages:[...thread.messages,{id:'sent',author:'you',text,citations:[],clip_id:null}]}:thread))}/>;
}

describe('Messages',()=>{
  it('sends trimmed text to the selected thread and clears the composer', async()=>{
    const user=userEvent.setup();render(<Harness/>);
    await user.type(screen.getByRole('textbox',{name:'Message'}),'  What happened by the gate?  ');
    await user.click(screen.getByRole('button',{name:'Send message'}));
    expect(screen.getByText('What happened by the gate?')).toBeVisible();
    expect(screen.getByRole('textbox',{name:'Message'})).toHaveValue('');
  });
  it('never sends empty text and blocks duplicate submits while awaiting an answer',async()=>{
    const user=userEvent.setup();render(<Harness pending/>);
    expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
    await user.type(screen.getByRole('textbox',{name:'Message'}),'Question');
    expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Searching the visit ledger');
  });
  it('keeps household text local and allows keyboard thread selection',async()=>{
    const user=userEvent.setup();render(<Harness/>);
    screen.getByRole('tab',{name:'Ask your home'}).focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('tab',{name:'Household'})).toHaveAttribute('aria-selected','true');
    expect(screen.getByRole('region',{name:'Household'})).toHaveTextContent('Local to this browser');
    await user.type(screen.getByRole('textbox',{name:'Message'}),'Keep the gate closed{Enter}');
    expect(screen.getByText('Keep the gate closed')).toBeVisible();
  });
  it('allows line breaks with Shift+Enter and submits with Enter',async()=>{
    const user=userEvent.setup();render(<Harness/>);
    await user.type(screen.getByRole('textbox',{name:'Message'}),'First line');
    await user.keyboard('{Shift>}{Enter}{/Shift}');
    await user.type(screen.getByRole('textbox',{name:'Message'}),'Second line');
    expect(screen.getByRole('textbox',{name:'Message'})).toHaveValue('First line\nSecond line');
    await user.keyboard('{Enter}');
    expect(screen.getByRole('textbox',{name:'Message'})).toHaveValue('');
  });
  it('disables unavailable recording and snapshot controls with visible explanations',()=>{
    render(<MessagesPage {...base}/>);
    expect(screen.getByRole('button',{name:'Take snapshot'})).toBeDisabled();
    expect(screen.getByRole('button',{name:'Record clip'})).toBeDisabled();
    expect(screen.getByText('Snapshots and recording are unavailable for this session.')).toBeVisible();
  });
  it('shows backend errors without fabricating an answer or clearing a failed draft',()=>{
    render(<MessagesPage {...base} error="The visit ledger could not be searched."/>);
    expect(screen.getByRole('alert')).toHaveTextContent('The visit ledger could not be searched.');
    expect(screen.queryByText('Vigil replied')).not.toBeInTheDocument();
  });
  it('opens citations from supplied messages and never invents thread history',async()=>{
    let selected='';const user=userEvent.setup();
    render(<MessagesPage {...base} onOpenVisit={id=>{selected=id;}} threads={[{...threads[0],messages:[{id:'answer',author:'vigil',text:'A person touched the side gate.',citations:[{visit_id:'visit-c',event_id:'event-7'}],clip_id:null}]}]}/>);
    await user.click(screen.getByRole('button',{name:'Open evidence event-7'}));
    expect(selected).toBe('visit-c');
    expect(screen.getByText('A person touched the side gate.')).toBeVisible();
  });
  it('closes the floating popup with Escape and restores the triggering focus',async()=>{
    const user=userEvent.setup();
    function PopupHarness(){const [open,setOpen]=useState(false);return <><button onClick={()=>setOpen(true)}>Open messages</button><ChatPopup {...base} open={open} onClose={()=>setOpen(false)}/></>;}
    render(<PopupHarness/>);
    await user.click(screen.getByRole('button',{name:'Open messages'}));
    await waitFor(()=>expect(screen.getByRole('dialog',{name:'Messages'})).toBeVisible());
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Open messages'})).toHaveFocus();
  });
  it('retains a controlled draft when switching between full screen and the popup',async()=>{
    const user=userEvent.setup();
    function LayoutHarness(){
      const [popup,setPopup]=useState(false);
      const [drafts,setDrafts]=useState<Record<string,string>>({});
      const props={...base,drafts,onDraftChange:(id:string,text:string)=>setDrafts(current=>({...current,[id]:text}))};
      return <><button onClick={()=>setPopup(current=>!current)}>Switch layout</button>{popup?<ChatPopup {...props} open onClose={()=>setPopup(false)}/>:<MessagesPage {...props}/>}</>;
    }
    render(<LayoutHarness/>);
    await user.type(screen.getByRole('textbox',{name:'Message'}),'Keep this draft');
    await user.click(screen.getByRole('button',{name:'Switch layout'}));
    expect(screen.getByRole('textbox',{name:'Message'})).toHaveValue('Keep this draft');
    await user.keyboard('{Escape}');
    expect(screen.getByRole('textbox',{name:'Message'})).toHaveValue('Keep this draft');
  });
  it('keeps a draft after a rejected asynchronous send',async()=>{
    const user=userEvent.setup();
    render(<MessagesPage {...base} onSend={()=>Promise.reject(new Error('offline'))}/>);
    await user.type(screen.getByRole('textbox',{name:'Message'}),'Gate question');
    await user.click(screen.getByRole('button',{name:'Send message'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('The message could not be sent. Your draft has been kept.');
    expect(screen.getByRole('textbox',{name:'Message'})).toHaveValue('Gate question');
  });
  it('never enables media controls from capability flags without working callbacks',()=>{
    render(<MessagesPage {...base} capabilities={{...capabilities,snapshot:true,recording:true}}/>);
    expect(screen.getByRole('button',{name:'Take snapshot'})).toBeDisabled();
    expect(screen.getByRole('button',{name:'Record clip'})).toBeDisabled();
  });
  it('renders a shared clip once and opens the lead-owned clip player',async()=>{
    let selected='';const user=userEvent.setup();
    render(<MessagesPage {...base} onOpenClip={id=>{selected=id;}} threads={[{...threads[1],messages:[{id:'clip-message',author:'you',text:'Gate clip',citations:[],clip_id:'clip-c'}]}]} selectedThreadId="household"/>);
    await user.click(screen.getByRole('button',{name:'Shared clip clip-c'}));
    expect(selected).toBe('clip-c');
    expect(screen.getAllByText('Gate clip')).toHaveLength(1);
  });
  it('uses an honest empty state when no threads were supplied',()=>{
    render(<MessagesPage {...base} threads={[]}/>);
    expect(screen.getByRole('heading',{name:'No threads available'})).toBeVisible();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
  it('distinguishes initial loading from an empty thread list',()=>{
    render(<MessagesPage {...base} threads={[]} pending/>);
    expect(screen.getByRole('heading',{name:'Loading messages'})).toBeVisible();
    expect(screen.queryByText('No threads available')).not.toBeInTheDocument();
  });
  it('shows an initial service failure and offers the actual retry callback',async()=>{
    const retry=vi.fn();
    render(<MessagesPage {...base} threads={[]} error="Chat service unavailable." onRetry={retry}/>);
    expect(screen.getByRole('alert')).toHaveTextContent('Chat service unavailable.');
    await userEvent.click(screen.getByRole('button',{name:'Try again'}));
    expect(retry).toHaveBeenCalledOnce();
  });
  it('blocks clip sharing when the selected thread cannot send messages',async()=>{
    const user=userEvent.setup();
    render(<MessagesPage {...base} selectedThreadId="household" capabilities={{...capabilities,household_messaging:'unavailable'}} onShareClip={()=>{throw new Error('Unavailable sharing must never run');}}/>);
    await user.click(screen.getByRole('button',{name:'Share options'}));
    expect(screen.getByRole('menuitem',{name:/Share a clip/})).toHaveAttribute('aria-disabled','true');
  });
  it('renders keyboard help and pending punctuation as valid Unicode',()=>{
    render(<MessagesPage {...base} pending/>);
    expect(screen.getByRole('status').textContent).toBe('Searching the visit ledger\u2026');
    expect(screen.getByText('Enter to send \u00b7 Shift+Enter for a new line')).toBeVisible();
  });
});
