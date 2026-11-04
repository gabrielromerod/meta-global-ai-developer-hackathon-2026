// @vitest-environment jsdom
import {afterEach,describe,it,expect,vi} from 'vitest';
import '@testing-library/jest-dom/vitest';
import {render,screen,cleanup,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import fixture from '../fixtures/state.json';
import chat from '../fixtures/chat.json';
import {VigilApp} from './index';
vi.mock('../twin',()=>({HouseView:()=> <div>House model loaded</div>}));
function mount(){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><VigilApp/></MemoryRouter></QueryClientProvider>);}
afterEach(()=>{cleanup();vi.unstubAllGlobals();sessionStorage.clear();localStorage.clear();});
describe('production API integration',()=>{
  it('shows a service failure and retries without substituting authored demo data',async()=>{
    const fetcher=vi.fn().mockRejectedValue(new TypeError('offline'));vi.stubGlobal('fetch',fetcher);mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be reached');
    expect(screen.queryByText('Same action, different context')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'Try again'}));
    await waitFor(()=>expect(fetcher.mock.calls.filter(([url])=>url==='/api/ui/state').length).toBeGreaterThan(1));
  });
  it('uses server inventory and keeps sandbox owner controls disabled',async()=>{
    vi.stubGlobal('fetch',vi.fn(async(url:string)=>({ok:true,json:async()=>url.endsWith('/state')?fixture:url.endsWith('/chat')?chat:{cameras:[]}})));
    mount();expect(await screen.findByText('House model loaded')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button',{name:'Settings'}));
    expect(screen.getAllByText('Front left Duo').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('tab',{name:'Owner access'}));
    expect(screen.getAllByText('Owner-only on the home box').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('button',{name:'Protection'}));
    expect(screen.getByRole('button',{name:"I'm outside"})).toBeDisabled();
  });
  it('asks the owner to pick a camera in the house view instead of guessing one',async()=>{
    vi.stubGlobal('fetch',vi.fn(async(url:string)=>({ok:true,json:async()=>url.endsWith('/state')?fixture:url.endsWith('/chat')?chat:{cameras:[]}})));
    mount();await screen.findByText('House model loaded');
    expect(screen.getByText('Tap a camera in the house view to see what it recorded.')).toBeInTheDocument();
  });
  it('returns keyboard focus to the same floating Messages trigger after Escape',async()=>{
    vi.stubGlobal('fetch',vi.fn(async(url:string)=>({ok:true,json:async()=>url.endsWith('/state')?fixture:url.endsWith('/chat')?chat:{cameras:[]}})));
    mount();await screen.findByText('House model loaded');
    const trigger=screen.getAllByRole('button',{name:'Messages'}).at(-1)!;
    await userEvent.click(trigger);
    await screen.findByRole('dialog',{name:'Messages'});
    await userEvent.keyboard('{Escape}');
    await waitFor(()=>expect(trigger).toHaveFocus());
  });
});
