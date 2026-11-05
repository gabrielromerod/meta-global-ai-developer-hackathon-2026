// @vitest-environment jsdom
import React from 'react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render as rtlRender, screen} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';
import {CapturedClips, describeTrack, fitView, frameStyle, groupCaptures, groupTracks, roleNote, storyRows, type Capture} from './captures';

afterEach(cleanup);
const render = (ui: React.ReactElement) => rtlRender(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
const clip = (over: Partial<Capture> = {}): Capture => ({id: 'porch-aaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbb', camera_id: 'porch', camera_name: 'Porch', kind: 'person', started_at: '2026-11-03T23:20:11+00:00', ended_at: '2026-11-03T23:20:18+00:00', partial: false, clip_url: '/api/ui/captures/porch-aaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbb/clip', masked: false, analysis: 'not_analysed', layer: 'camera_ai', ...over});

describe('real captured clips', () => {
  it('renders nothing until a camera has recorded a clip', () => {
    const {container} = render(<CapturedClips captures={[]}/>);
    expect(container).toBeEmptyDOMElement();
  });
  it('labels clips as camera alerts not analysed by Vigil and plays one', async () => {
    render(<CapturedClips captures={[clip(), clip({id: 'doorbell-x', camera_id: 'doorbell', camera_name: 'Doorbell', kind: 'doorbell_press', clip_url: null})]}/>);
    expect(screen.getByText(/Vigil has not analysed them/i)).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /Doorbell pressed at Doorbell/})).toBeDisabled();
    await userEvent.click(screen.getByRole('button', {name: /Person at Porch/}));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.querySelector('video')?.getAttribute('src')).toBe(clip().clip_url);
    expect(screen.getByText(/Vigil has not analysed this clip yet/)).toBeInTheDocument();
    expect(screen.getByText(/only shown on your home network/)).toBeInTheDocument();
  });
});

describe('grouping clips into moments', () => {
  it('joins a parking car and the person who walks in into one arrival, newest moment first', () => {
    const car = clip({id: 'car', camera_id: 'front_left_duo', camera_name: 'Front left Duo', kind: 'vehicle', started_at: '2026-11-03T23:00:00+00:00', ended_at: '2026-11-03T23:00:40+00:00'});
    const walk = clip({id: 'walk', started_at: '2026-11-03T23:01:10+00:00', ended_at: '2026-11-03T23:01:20+00:00'});
    const passing = clip({id: 'passing', kind: 'vehicle', started_at: '2026-11-03T23:10:00+00:00', ended_at: '2026-11-03T23:10:05+00:00'});
    const back = clip({id: 'back', started_at: '2026-11-03T23:20:00+00:00', ended_at: '2026-11-03T23:20:30+00:00'});
    const groups = groupCaptures([passing, back, walk, car]);
    expect(groups.map(g => g.items.map(x => x.id))).toEqual([['back'], ['car', 'walk']]);
    expect(groups[1].hasPerson && groups[1].hasVehicle).toBe(true);
    expect(groups[1].lead.id).toBe('walk');
    expect(groups[1].cameras).toEqual(['Front left Duo', 'Porch']);
  });
  it('never chains moments through a stream of passing cars', () => {
    const cars = Array.from({length: 20}, (_, i) => clip({id: `car${i}`, kind: 'vehicle', started_at: new Date(Date.parse('2026-11-03T22:00:00Z') + i * 30_000).toISOString(), ended_at: new Date(Date.parse('2026-11-03T22:00:20Z') + i * 30_000).toISOString()}));
    const a = clip({id: 'a', started_at: '2026-11-03T22:01:00Z', ended_at: '2026-11-03T22:01:10Z'});
    const b = clip({id: 'b', started_at: '2026-11-03T22:09:00Z', ended_at: '2026-11-03T22:09:10Z'});
    const groups = groupCaptures([...cars, a, b]);
    expect(groups.map(g => g.lead.id)).toEqual(['b', 'a']);
    expect(groups.every(g => g.items.length < 8)).toBe(true);
  });
  it('shows people first and keeps passing cars under All', async () => {
    render(<CapturedClips captures={[clip({id: 'car', kind: 'vehicle'})]}/>);
    expect(screen.getByText(/No person recorded yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', {name: 'All clips'}));
    expect(screen.getByRole('button', {name: /Vehicle at Porch/})).toBeInTheDocument();
  });
});

describe('analysed captures', () => {
  const track = {tag: 'T6', phrase: 'person', class: 'person', upper_color: 'white', lower_color: 'black', vehicle_color: null, vehicle_body: null, carrying: [], from: 2, to: 6};
  it('describes tracks in plain words and leaves unknown colours out', () => {
    expect(describeTrack(track)).toEqual({kind: 'person', notes: 'white top, black bottom'});
    expect(describeTrack({...track, phrase: 'car', class: 'vehicle', vehicle_color: 'white', vehicle_body: 'sedan'}).notes).toBe('white sedan');
    expect(describeTrack({...track, class: null, upper_color: 'unknown', lower_color: null}).notes).toBe('');
  });
  it('shows tracks with the same description once, listing every tag', () => {
    const rows = groupTracks([track, {...track, tag: 'T7'}, {...track, tag: 'T4', phrase: 'car', class: 'vehicle', vehicle_color: 'white'}]);
    expect(rows.map(r => r.tags)).toEqual([['T6', 'T7'], ['T4']]);
    expect(rows[0].colors).toEqual(['white', 'black']);
  });
  it('folds repeated sentences into one row with each cited moment, and keeps gaps out of the list', () => {
    const line = (text: string, at: number|null, source = 'wonder') => ({text, source, event_ids: at === null ? [] : ['e'], gap_id: null, at, kind: 'person'});
    const rows = storyRows([line('A person entered.', 2.2), line('A person entered.', 16), line('Gap.', null, 'code')]);
    expect(rows).toEqual([{text: 'A person entered.', times: [2.2, 16], kind: 'person'}]);
  });
  it('explains a person\'s role from where they were first seen, never who they are', () => {
    expect(roleNote([{id: 's1', actor_role: 'unknown', role_basis: 'origin_null:t', kind: 'person'}])).toMatch(/first seen in the yard/i);
    expect(roleNote([{id: 's1', actor_role: 'external_visitor', role_basis: 'perimeter:street', kind: 'person'}])).toMatch(/from the street/);
    expect(roleNote([{id: 's1', actor_role: 'unknown', role_basis: 'origin_null:car', kind: 'vehicle'}])).toBeNull();
  });
});

describe('cropping to the property', () => {
  const view = {x0: 0.08, y0: 0.35, x1: 0.92, y1: 1};
  it('keeps the whole unmasked view in the player and narrows thumbnails around the subject', () => {
    expect(fitView(view, 8 / 3)).toEqual(view);
    const thumb = fitView(view, 8 / 3, 16 / 9, 0.85);
    expect(thumb.y0).toBe(0.35);
    expect(thumb.y1).toBe(1);
    expect(thumb.x1).toBeCloseTo(0.92);  // clamped to the view, never into the masked side
    expect(((thumb.x1 - thumb.x0) * 8 / 3) / (thumb.y1 - thumb.y0)).toBeCloseTo(16 / 9);
  });
  it('places the full frame so only the region shows', () => {
    const style = frameStyle({x0: 0, y0: 0.35, x1: 1, y1: 1});
    expect(style.width).toBe('100%');
    expect(parseFloat(String(style.height))).toBeCloseTo(153.85, 1);
    expect(parseFloat(String(style.top))).toBeCloseTo(-53.85, 1);
  });
  it('marks masked thumbnails and shows the subject crop and SAM box', () => {
    render(<CapturedClips captures={[clip({masked: true, frame_aspect: 8 / 3, crop: view, crop_top: 0.35, analysis: 'analysed',
      subject: {track_id: 'cam-person-1', label: 'T3 person', t: 4.2, box: [0.4, 0.5, 0.45, 0.9], image_url: '/api/ui/captures/x/subject.jpg'}})]}/>);
    expect(screen.getByText('Street masked · cropped to property')).toBeInTheDocument();
    expect(screen.getByText('T3 person')).toBeInTheDocument();
    expect(document.querySelector('img.capture-subject')?.getAttribute('src')).toBe('/api/ui/captures/x/subject.jpg');
  });
});

describe('people seen inside the property', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('lists real profiles with their count and filters the clips to one person', async () => {
    const other = 'porch-cccccccccccccccccccc-dddddddddddd';
    const profiles = {enabled: true, models_ready: true, note: '', profiles: [
      {id: 'ap_1', name: null, flagged: false, count: 2, seen_label: 'Seen 2 times on the property', basis: 'clothing', label: 'white top, black bottoms',
        sightings: [{capture_id: clip().id, seen_at: '2026-11-03T23:20:11+00:00'}], crops: ['/c1.jpg', '/c2.jpg'], crop_times: []},
    ]};
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(profiles), {status: 200})));
    render(<CapturedClips captures={[clip(), clip({id: other, started_at: '2026-11-03T21:00:00+00:00', ended_at: '2026-11-03T21:00:05+00:00'})]}/>);
    const person = await screen.findByRole('button', {name: /Recurring visitor.*Seen 2 times.*white top, black bottoms/});
    expect(screen.queryByText(/Household|Courier/)).toBeNull();
    await userEvent.click(person);
    expect(screen.getByRole('button', {name: /Showing clips with white top, black bottoms/})).toBeInTheDocument();
    expect(screen.getAllByRole('button', {name: /Person at Porch/})).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', {name: /Showing clips with/}));
    expect(screen.getByRole('button', {name: 'All clips'})).toBeInTheDocument();
  });
});

describe('rule alerts on a clip', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('shows which rule raised the alert and the object SAM marked, never a face match', async () => {
    const analysis = {id: clip().id, verdict: 'needs_attention', story_source: 'template', visits: 1, clip: {duration: 20},
      alerts: [{rule_id: 'r_carried_object', rule: 'Possible knife or gun carried by a non-household person', event_id: 'e9', type: 'carry', object: 'knife', at: 12.4}],
      story: [], subjects: [], gaps: [], tracks: [], zones: [], tagged: [], moment: null};
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(String(url).endsWith('/analysis') ? analysis : {enabled: false, profiles: []}), {status: 200})));
    render(<CapturedClips captures={[clip({analysis: 'analysed'})]}/>);
    await userEvent.click(screen.getByRole('button', {name: /Person at Porch/}));
    const alert = await screen.findByRole('alert', {name: 'Alert'});
    expect(alert).toHaveTextContent('Possible knife or gun carried by a non-household person');
    expect(alert).toHaveTextContent('SAM 3.1 marked a possible knife at 0:12');
    expect(alert).toHaveTextContent(/never from their face/);
  });
});
