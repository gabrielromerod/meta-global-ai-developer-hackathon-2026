// @vitest-environment jsdom
import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import fixture from '../../fixtures/state.json';
import type {UIState} from '../../contracts';
import {ClipsPage} from './index';
import {MediaPage} from '../media';

const state=fixture as unknown as UIState;
const callbacks=()=>({onOpenClip:vi.fn(),onOpenVisit:vi.fn()});
afterEach(cleanup);
describe('Clips and Media library',()=>{
  it('filters supplied clips by category, with an honest unavailable category',async()=>{
    render(<ClipsPage state={state} {...callbacks()}/>);
    expect(screen.getAllByRole('listitem')).toHaveLength(state.clips.length);
    await userEvent.click(screen.getByRole('tab',{name:'Vehicles'}));
    expect(screen.getByText('No matching clips')).toBeVisible();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab',{name:'Packages'}));
    expect(screen.getAllByRole('listitem')).toHaveLength(state.clips.filter(clip=>clip.kind==='package').length);
  });
  it('opens the actual clip ID even when media is unavailable',async()=>{
    const props=callbacks();
    render(<ClipsPage state={state} {...props}/>);
    const card=screen.getAllByRole('listitem')[0].querySelector('button')!;
    await userEvent.click(card);
    expect(props.onOpenClip).toHaveBeenCalledWith([...state.clips].sort((a,b)=>b.t0-a.t0)[0].id);
    // Demo clips carry a labelled illustration, never a fake recording.
    expect(screen.getAllByText('Illustration · clip unavailable')).toHaveLength(state.clips.length);
    expect(document.querySelector('video')).toBeNull();
  });
  it('searches actual evidence and clears back to the complete collection',async()=>{
    render(<MediaPage state={state} {...callbacks()}/>);
    const input=screen.getByRole('searchbox',{name:'Search evidence'});
    await userEvent.type(input,'unseen meteor');
    expect(screen.getByText('No matching clips')).toBeVisible();
    await userEvent.click(screen.getByRole('button',{name:'Clear filters'}));
    expect(input).toHaveValue('');
    expect(screen.getAllByRole('listitem')).toHaveLength(state.clips.length);
  });
  it('submits full filter state to the lead callback with ISO timestamps',async()=>{
    const onSearch=vi.fn();
    render(<MediaPage state={state} {...callbacks()} onSearch={onSearch}/>);
    await userEvent.type(screen.getByRole('searchbox',{name:'Search evidence'}),'gate');
    await userEvent.click(screen.getByRole('button',{name:'Time range'}));
    fireEvent.change(screen.getByLabelText('From (local time)'),{target:{value:'2026-11-02T18:00'}});
    await userEvent.click(screen.getByRole('button',{name:'Done'}));
    await userEvent.click(screen.getByRole('button',{name:'Apply filters'}));
    expect(onSearch).toHaveBeenCalledTimes(1);
    expect(onSearch.mock.calls[0][0]).toMatchObject({q:'gate',start:new Date('2026-11-02T18:00').toISOString()});
  });
  it('explains invalid time ranges and does not send an invalid query',async()=>{
    const onSearch=vi.fn();
    render(<MediaPage state={state} {...callbacks()} onSearch={onSearch}/>);
    await userEvent.click(screen.getByRole('button',{name:'Time range'}));
    fireEvent.change(screen.getByLabelText('From (local time)'),{target:{value:'2026-11-03T19:00'}});
    fireEvent.change(screen.getByLabelText('Until (local time)'),{target:{value:'2026-11-03T18:00'}});
    expect(screen.getByRole('alert')).toHaveTextContent(/end time on or after/i);
    await userEvent.click(screen.getByRole('button',{name:'Done'}));
    await userEvent.click(screen.getByRole('button',{name:'Apply filters'}));
    expect(onSearch).not.toHaveBeenCalled();
  });
  it('has a true empty state without fabricated clips or people',()=>{
    render(<ClipsPage state={{...state,clips:[]}} {...callbacks()}/>);
    expect(screen.getByText('No clips yet')).toBeVisible();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
    expect(document.querySelector('video,img')).toBeNull();
  });
  it('keeps local filters working and disables an unavailable search callback',async()=>{
    render(<MediaPage state={state} {...callbacks()}/>);
    expect(screen.getByRole('button',{name:'Apply filters'})).toBeDisabled();
    expect(screen.getByText('Filters update as you type.')).toBeVisible();
    await userEvent.type(screen.getByRole('searchbox',{name:'Search evidence'}),'unseen meteor');
    expect(screen.getByText('No matching clips')).toBeVisible();
    await userEvent.click(screen.getByRole('button',{name:'Clear filters'}));
    expect(screen.getAllByRole('listitem')).toHaveLength(state.clips.length);
  });
});
