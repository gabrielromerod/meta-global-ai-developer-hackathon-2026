// @vitest-environment jsdom
import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import userEvent from '@testing-library/user-event';
import {VerdictBadge, Tabs, Modal, VideoTile, ClipCard} from './index';

afterEach(cleanup);
describe('shared security evidence components',()=>{
  it('shows a word beside every verdict icon',()=>{
    for(const verdict of ['normal','noteworthy','needs_attention','cant_confirm'] as const) render(<VerdictBadge verdict={verdict}/>);
    for(const label of ['Normal','Noteworthy','Needs attention',"Can't confirm"]) expect(screen.getByText(label)).toBeVisible();
  });
  it('selects configured view ids through accessible tabs',()=>{
    const onChange=vi.fn();
    render(<Tabs label="Camera views" value="overview" onChange={onChange} items={[{id:'overview',label:'Overview'},{id:'porch',label:'Porch'}]}/>);
    fireEvent.mouseDown(screen.getByRole('tab',{name:'Porch'}),{button:0,ctrlKey:false});
    expect(onChange).toHaveBeenCalledWith('porch');
  });
  it('associates selected camera view with its panel',()=>{
    render(<Tabs label="Views" value="porch" onChange={vi.fn()} items={[{id:'porch',label:'Porch'}]}>Porch evidence</Tabs>);
    expect(screen.getByRole('tabpanel',{name:'Porch'})).toHaveTextContent('Porch evidence');
  });
  it('uses a labelled dialog and restores the close callback',()=>{
    const onClose=vi.fn();
    render(<Modal title="Visit evidence" open onClose={onClose}><p>No media available</p></Modal>);
    expect(screen.getByRole('dialog',{name:'Visit evidence'})).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:'Close Visit evidence'}));
    expect(onClose).toHaveBeenCalledOnce();
  });
  it('returns keyboard focus to the external opener after Escape',async()=>{
    function Harness(){const [open,setOpen]=React.useState(false);return <><button onClick={()=>setOpen(true)}>Open evidence</button><Modal title="Evidence" open={open} onClose={()=>setOpen(false)}>Cited event</Modal></>;}
    const user=userEvent.setup();render(<Harness/>);
    const opener=screen.getByRole('button',{name:'Open evidence'});
    await user.click(opener);await user.keyboard('{Escape}');
    expect(opener).toHaveFocus();
  });
  it('does not imply unavailable camera clips are playable',()=>{
    render(<VideoTile camera={{id:'porch',name:'Porch',model:null,power_profile:'plugin_wifi',stream:'sub',status:'not_connected',source_label:'Not connected',hub_present:null,wifi_signal_dbm:null,clock_offset_s:null,clip_url:null,thumbnail_url:null}}/>);
    expect(screen.getByText('No clip available')).toBeVisible();
    expect(screen.queryByRole('button')).toBeNull();
  });
  it('keeps a clip card selectable as evidence when media is unavailable',()=>{
    const onOpen=vi.fn();
    render(<ClipCard clip={{id:'clip-1',visit_id:'visit-1',camera_id:'porch',verdict:'normal',clock:'6:14 PM',t0:0,t1:10,title:'Gate touch',kind:'person',clip_url:null,thumbnail_url:null,source_label:'Imported clips'}} onOpen={onOpen}/>);
    fireEvent.click(screen.getByRole('button',{name:/Gate touch/}));
    expect(onOpen).toHaveBeenCalledWith('clip-1');
    expect(screen.getByText('Media unavailable')).toBeVisible();
  });
});
