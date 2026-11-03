// @vitest-environment jsdom
import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import fixture from '../../fixtures/state.json';
import type {UIState} from '../../contracts';
import {HomePage} from './index';
import {AttentionPage} from '../attention/index';

const state = fixture as unknown as UIState;
const callbacks = () => ({onOpenVisit:vi.fn(),onOpenClip:vi.fn()});
afterEach(cleanup);

describe('Home cards and selection (FR-017, FR-044)', () => {
  it('keeps verdict, spatial basis and supplied rule reason visible for both gate touches', () => {
    render(<HomePage state={state} {...callbacks()} />);
    const comparison = screen.getByRole('region',{name:'Same action, different context'});
    expect(within(comparison).getByText('Normal')).toBeVisible();
    expect(within(comparison).getByText('Needs attention')).toBeVisible();
    expect(within(comparison).getByText(state.visits.find(v=>v.id==='v_ap')!.role_basis)).toBeVisible();
    expect(within(comparison).getByText(state.visits.find(v=>v.id==='v_ap')!.reason)).toBeVisible();
    expect(within(comparison).getByText(state.visits.find(v=>v.id==='v_c')!.reason)).toBeVisible();
    expect(within(comparison).getByText('6:02:28 PM')).toBeVisible();
    expect(within(comparison).getByText('6:14:05 PM')).toBeVisible();
  });
  it('opens the actual compared visit when its card is selected', async () => {
    const props = callbacks();
    render(<HomePage state={state} {...props} />);
    await userEvent.click(screen.getByRole('button',{name:/Open household side gate visit/i}));
    expect(props.onOpenVisit).toHaveBeenCalledWith('v_ap');
  });
  it('uses config tabs and emits the selected view while rendering lead slots once', async () => {
    const onViewChange = vi.fn();
    render(<HomePage state={state} {...callbacks()} onViewChange={onViewChange}
      twinSlot={<div data-testid="twin-slot">House view</div>}
      playerSlot={<div data-testid="player-slot">Camera player</div>} />);
    expect(screen.getAllByTestId('twin-slot')).toHaveLength(1);
    expect(screen.getAllByTestId('player-slot')).toHaveLength(1);
    await userEvent.click(screen.getByRole('tab',{name:'Night'}));
    expect(onViewChange).toHaveBeenCalledWith('night');
  });
  it('shows measured summary data and explicitly keeps unknown prefilter counts unavailable', () => {
    render(<HomePage state={state} {...callbacks()} />);
    expect(screen.getByText('5 visits → 1 needs attention')).toBeVisible();
    expect(screen.getByText(state.summary.note)).toBeVisible();
    expect(screen.queryByText(/0 street events/)).not.toBeInTheDocument();
  });
  it('shows empty states rather than a fabricated gate comparison or visit', () => {
    render(<HomePage state={{...state,visits:[],events:[],attention_ids:[],summary:{...state.summary,visits:0,needs_attention:0}}} {...callbacks()} />);
    expect(screen.getByText('No visits to review')).toBeVisible();
    expect(screen.queryByRole('region',{name:'Same action, different context'})).not.toBeInTheDocument();
  });
  it('opens the matching clip ID rather than treating a configured camera ID as a clip', async () => {
    const props = callbacks();
    const camera = {...state.cameras[0],clip_url:'/media/recorded-event.mp4'};
    const clip = {...state.clips[0],id:'clip-front-left',camera_id:camera.id,clip_url:camera.clip_url};
    render(<HomePage state={{...state,cameras:[camera,...state.cameras.slice(1)],clips:[clip]}}
      activeView={`camera_${camera.id}`} {...props}/>);
    await userEvent.click(screen.getByRole('button',{name:`Open ${camera.name} clip`}));
    expect(props.onOpenClip).toHaveBeenCalledWith(clip.id);
  });
});

describe('Attention center', () => {
  it('keeps all ranked visits available on the full Attention page beyond the five-card Home preview', () => {
    const visits = Array.from({length:7},(_,index)=>({...state.visits[0],id:`visit-${index}`,title:`Recorded visit ${index}`}));
    render(<AttentionPage state={{...state,visits,attention_ids:visits.map(visit=>visit.id)}} {...callbacks()}/>);
    expect(screen.getAllByRole('button',{name:/Open visit Recorded visit/})).toHaveLength(7);
  });
  it('keeps supplied gaps visible and opens a visit from the ranked list', async () => {
    const props = callbacks();
    render(<AttentionPage state={state} {...props} />);
    expect(screen.getByText('Not observed · 41 s')).toBeVisible();
    await userEvent.click(screen.getByRole('button',{name:/Open visit C ·/}));
    expect(props.onOpenVisit).toHaveBeenCalledWith('v_c');
  });
  it('lets the user filter the existing list by verdict with keyboard accessible tabs', async () => {
    render(<AttentionPage state={state} {...callbacks()} />);
    await userEvent.click(screen.getByRole('tab',{name:'Needs attention'}));
    expect(screen.getAllByRole('button',{name:/Open visit/})).toHaveLength(1);
    expect(screen.getByRole('button',{name:/Open visit C ·/})).toBeVisible();
  });
});
