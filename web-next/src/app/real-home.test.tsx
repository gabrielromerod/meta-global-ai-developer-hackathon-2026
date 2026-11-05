// @vitest-environment jsdom
import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render as rtlRender, screen, within} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import fixture from '../fixtures/state.json';
import type {UIState} from '../contracts';
import type {Capture} from './captures';
import {CameraPanel, RealAttention, RealHome, reviewOrder} from './real-home';

/** Real-only home box (VIGIL_REAL_ONLY): the server sends no bundle visits; pages read real clips. */
const real: UIState = {...(fixture as unknown as UIState), visits: [], clips: [], notifications: [], attention_ids: [],
  evidence: {kind: 'real', label: 'Your home', source: 'Masked event clips from your cameras'} as UIState['evidence'],
  summary: {...(fixture as unknown as UIState).summary, motion_triggers: 166, visits: 11, needs_attention: 0}};
const clip = (over: Partial<Capture> = {}): Capture => ({id: 'front_left_duo-aaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbb', camera_id: 'front_left_duo', camera_name: 'Front left Duo',
  kind: 'person', started_at: '2026-11-03T23:20:11+00:00', ended_at: '2026-11-03T23:20:31+00:00', partial: false, clip_url: '/api/ui/captures/x/clip',
  masked: true, analysis: 'analysed', layer: 'camera_ai', verdict: 'normal', headline: 'A person entered the left garden.', ...over});
const render = (ui: React.ReactElement) => rtlRender(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>{ui}</QueryClientProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('real-only home', () => {
  it('orders analysed clips by verdict severity, then newest, and skips unanalysed ones', () => {
    const rows = reviewOrder([
      clip({id: 'old-normal', started_at: '2026-11-03T20:00:00+00:00'}),
      clip({id: 'cant', verdict: 'cant_confirm', started_at: '2026-11-03T19:00:00+00:00'}),
      clip({id: 'new-normal', started_at: '2026-11-03T22:00:00+00:00'}),
      clip({id: 'raw', analysis: 'not_analysed', verdict: null}),
    ]);
    expect(rows.map(r => r.id)).toEqual(['cant', 'new-normal', 'old-normal']);
  });

  it('shows the real funnel, the house and every camera as a button, with no demo data', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({camera_id: 'front_left_duo', still: null, profiles: []}), {status: 200})));
    const select = vi.fn();
    render(<RealHome state={real} captures={[clip()]} houseSlot={<div>house model</div>} activeCamera={null} onSelectCamera={select}/>);
    expect(screen.getByLabelText('What your cameras saved')).toHaveTextContent('166 clips saved by your cameras');
    expect(screen.getByLabelText('What your cameras saved')).toHaveTextContent('11 analysed by Vigil');
    expect(screen.getByText('house model')).toBeInTheDocument();
    expect(screen.queryByText('Demo data')).not.toBeInTheDocument();
    const cameras = within(screen.getByRole('group', {name: 'Cameras'}));
    expect(cameras.getAllByRole('button')).toHaveLength(real.cameras.length);
    await userEvent.click(cameras.getByRole('button', {name: /Front left Duo/}));
    expect(select).toHaveBeenCalledWith('front_left_duo');
    expect(screen.getByRole('list', {name: 'Analysed clips'})).toHaveTextContent('A person entered the left garden.');
  });

  it("opens a camera's latest masked frame and its clips, and says plainly when there are none", async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({camera_id: 'front_left_duo',
      still: {url: '/still.png', width: 1536, height: 576, visible: [0, .55, 1, 1], capture_id: clip().id, frame_ts: 2}}), {status: 200})));
    render(<CameraPanel cameraId="front_left_duo" state={real} captures={[clip(), clip({id: 'other', camera_id: 'porch'})]} onOpen={vi.fn()} onClose={vi.fn()}/>);
    expect(await screen.findByAltText('Front left Duo: latest masked frame')).toBeInTheDocument();
    expect(screen.getByText(/Not live/)).toBeInTheDocument();
    expect(screen.getByText(/1 clip recorded/)).toBeInTheDocument();
    cleanup();
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({camera_id: 'backyard_1', still: null}), {status: 200})));
    render(<CameraPanel cameraId="backyard_1" state={real} captures={[clip()]} onOpen={vi.fn()} onClose={vi.fn()}/>);
    expect(await screen.findByText('No clips recorded by this camera yet.')).toBeInTheDocument();
  });

  it('Attention lists only analysed real clips and filters them by verdict', async () => {
    render(<RealAttention captures={[clip({id: 'a'}), clip({id: 'b', verdict: 'cant_confirm', headline: 'The recording ended early.'}), clip({id: 'c', analysis: 'not_analysed', verdict: null})]}/>);
    const list = screen.getByRole('list', {name: 'Analysed clips'});
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    await userEvent.click(within(screen.getByRole('group', {name: 'Filter clips by verdict'})).getByRole('button', {name: /Can't confirm/}));
    expect(within(screen.getByRole('list', {name: 'Analysed clips'})).getAllByRole('listitem')).toHaveLength(1);
    expect(screen.getByText('The recording ended early.')).toBeInTheDocument();
  });
});
