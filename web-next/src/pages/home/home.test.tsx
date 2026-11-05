// @vitest-environment jsdom
import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render as rtlRender, screen, within} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import fixture from '../../fixtures/state.json';
import type {UIState} from '../../contracts';
import {HomePage} from './index';
import {AttentionPage} from '../attention/index';

const state = fixture as unknown as UIState;
// The rich visit cards fetch cited sentences and routes; offline tests render without them.
const render = (ui:React.ReactElement) => rtlRender(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>{ui}</QueryClientProvider>);
const callbacks = () => ({onOpenVisit:vi.fn(),onOpenClip:vi.fn()});
afterEach(cleanup);

it('full Attention can filter normal visits outside the urgent preview IDs',async()=>{
  const current=structuredClone(state);current.attention_ids=current.visits.filter(v=>v.verdict!=='normal').map(v=>v.id);
  render(<AttentionPage state={current} {...callbacks()}/>);
  await userEvent.click(screen.getByRole('tab',{name:'Normal'}));
  const list=screen.getByLabelText('Filtered visits');
  expect(within(list).getAllByRole('button')).toHaveLength(current.visits.filter(v=>v.verdict==='normal').length);
});

describe('Home cards and selection (FR-017, FR-044)', () => {
  it('keeps Home focused on what to review and links to the full list', () => {
    render(<HomePage state={state} {...callbacks()} />);
    expect(screen.getByRole('heading',{name:/to review$/})).toBeVisible();
    expect(screen.queryByRole('region',{name:'Same action, different context'})).not.toBeInTheDocument();
    expect(screen.getByRole('link',{name:'See all visits'})).toHaveAttribute('href','#/attention');
  });
  it('keeps verdict, spatial basis and supplied rule reason visible for both gate touches', async () => {
    render(<AttentionPage state={state} {...callbacks()} />);
    await userEvent.click(screen.getByText(/Why did two side gate touches/));
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
    render(<AttentionPage state={state} {...props} />);
    await userEvent.click(screen.getByText(/Why did two side gate touches/));
    await userEvent.click(screen.getByRole('button',{name:/Open household side gate visit/i}));
    expect(props.onOpenVisit).toHaveBeenCalledWith('v_ap');
  });
  it('renders the house and player slots once and lets the house expand', async () => {
    render(<HomePage state={state} {...callbacks()}
      twinSlot={<div data-testid="twin-slot">House view</div>}
      playerSlot={<div data-testid="player-slot">Camera player</div>} />);
    expect(screen.getAllByTestId('twin-slot')).toHaveLength(1);
    expect(screen.getAllByTestId('player-slot')).toHaveLength(1);
    const expand = screen.getByRole('button',{name:'Expand house'});
    await userEvent.click(expand);
    expect(screen.getByRole('button',{name:'Show visits'})).toHaveAttribute('aria-pressed','true');
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
    expect(within(screen.getByLabelText('Filtered visits')).getByText('Not observed · 41 s')).toBeVisible();
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

describe('Rich visit pieces (Home funnel, story cards)', () => {
  it('computes the filtered share from the session counts and labels demo data', async () => {
    const {FunnelBar} = await import('./insights');
    const current = structuredClone(state);
    current.summary = {...current.summary, motion_triggers:40, visits:4, needs_attention:2};
    render(<FunnelBar state={current} onOpenVisit={vi.fn()}/>);
    const funnel = screen.getByRole('region',{name:'Alert funnel'});
    expect(within(funnel).getByText('95%')).toBeVisible();
    if (current.evidence.kind === 'fixture') expect(within(funnel).getByText(current.evidence.label)).toBeVisible();
  });
  it('opens a visit from a funnel pill', async () => {
    const {FunnelBar} = await import('./insights');
    const open = vi.fn();
    render(<FunnelBar state={state} onOpenVisit={open}/>);
    const first = state.visits.find(v => v.id === state.attention_ids[0])!;
    await userEvent.click(screen.getByRole('button',{name:new RegExp(first.title.slice(0, 12).replace(/[.*+?^${}()|[\]\\]/g,'\\$&'))}));
    expect(open).toHaveBeenCalledWith(first.id);
  });
  it('shows the recorded role, never a recurring-visitor role, and citation chips open the cited event', async () => {
    const {StoryCard} = await import('./insights');
    const visit = state.visits.find(v => v.id === 'v_c')!;
    const open = vi.fn();
    render(<StoryCard state={state} visit={visit} onOpenVisit={open}
      detail={{sentences:[{index:0,text:'They touched the side gate.',citations:[{event_id:'e18',clock:'6:14:05 PM',camera_name:'Left side'}]}]}}/>);
    expect(screen.getByText('External visitor')).toBeVisible();
    expect(screen.queryByText(/Recurring/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'Open event e18 at 6:14:05 PM'}));
    expect(open).toHaveBeenCalledWith('v_c','e18');
  });
});
