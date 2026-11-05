// @vitest-environment jsdom
import {afterEach,it,expect,vi} from 'vitest';
import '@testing-library/jest-dom/vitest';
import {render,screen,cleanup,fireEvent} from '@testing-library/react';
import {waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ProtectionPanel} from './protection';
afterEach(()=>{cleanup();vi.unstubAllGlobals();sessionStorage.clear();});
it('keeps sandbox selection locked without requesting a frame',()=>{
  const request=vi.fn();vi.stubGlobal('fetch',request);
  render(<QueryClientProvider client={new QueryClient()}><ProtectionPanel enabled={false}/></QueryClientProvider>);
  expect(screen.getByRole('button',{name:'Add object'})).toBeDisabled();
  expect(request).not.toHaveBeenCalled();
});
it('requires an explicit cost confirmation and restores focus while an approved request is pending',async()=>{
  let finish!:(value:unknown)=>void;const response=new Promise(resolve=>{finish=resolve;});
  const request=vi.fn((url:string)=>url.includes('protection-frames')?Promise.resolve({ok:true,json:async()=>({frames:[{camera_id:'side_left',name:'Left passage',url:'/media/stills/side_left.png',frame_ts:12,width:1920,height:720}],reason:null,live:{available:true,reason:null,estimate_usd:.0025}})}):response);vi.stubGlobal('fetch',request);
  render(<QueryClientProvider client={new QueryClient()}><ProtectionPanel enabled/></QueryClientProvider>);
  await userEvent.click(await screen.findByRole('button',{name:'Add object'}));
  fireEvent.load(screen.getByAltText('Left passage exported still'));
  await userEvent.type(screen.getByRole('spinbutton',{name:'Pixel X'}),'1600');await userEvent.type(screen.getByRole('spinbutton',{name:'Pixel Y'}),'600');
  const trigger=screen.getByRole('button',{name:'Detect with SAM 3.1'});await userEvent.click(trigger);
  expect(screen.getByRole('dialog',{name:'Confirm detection'})).toHaveTextContent('$0.0025');
  expect(request.mock.calls.filter(([url])=>url==='/api/protect')).toHaveLength(0);
  await userEvent.click(screen.getByRole('button',{name:'Approve and run'}));
  await waitFor(()=>expect(trigger).toHaveFocus());
  finish({ok:true,json:async()=>({live:true,notice:null,result:{object:{id:'generated-mask',label:'Gate'},outline:[[1500,500],[1600,500],[1600,600]]}})});
  expect(await screen.findByLabelText('Point model mask')).toBeInTheDocument();
});
it('uses actual frame dimensions and keeps recorded-result selection cache-only',async()=>{
  const request=vi.fn(async(url:string)=>({ok:true,json:async()=>url.includes('protection-frames')?{frames:[{camera_id:'side_left',name:'Left passage',url:'/media/stills/side_left.png',frame_ts:12,width:1920,height:720}],live:{available:false,reason:'Cache-only session',estimate_usd:.0025}}:{live:false,result:null,notice:'Nothing recorded at that point.'}}));vi.stubGlobal('fetch',request);
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ProtectionPanel enabled/></QueryClientProvider>);
  await userEvent.click(await screen.findByRole('button',{name:'Add object'}));
  fireEvent.load(screen.getByAltText('Left passage exported still'));
  await userEvent.type(screen.getByRole('spinbutton',{name:'Pixel X'}),'1600');
  await userEvent.type(screen.getByRole('spinbutton',{name:'Pixel Y'}),'600');
  await userEvent.click(screen.getByRole('button',{name:'Check recorded result'}));
  expect(await screen.findByText('Nothing recorded at this point')).toBeVisible();
  const call=request.mock.calls.find(([url])=>url==='/api/protect') as unknown as [string,RequestInit];
  expect(JSON.parse(call[1].body as string)).toMatchObject({camera_id:'side_left',frame_ts:12,point:{x:1600,y:600},frame_width:1920,frame_height:720,live:false});
  expect(screen.getByRole('button',{name:'Detect with SAM 3.1'})).toBeDisabled();
});
it('shows a recorded masked still inline, cropped to the property, and sends its still id',async()=>{
  const frame={camera_id:'front_left_duo',name:'Front left Duo',url:'/api/ui/capture-stills/front_left_duo-a-b/6885.png',frame_ts:6.885,width:1536,height:576,still_id:'front_left_duo-a-b@6885',capture_id:'front_left_duo-a-b',source:'capture',visible:[.09,.55,.91,1]};
  const request=vi.fn(async(url:string)=>({ok:true,json:async()=>url.includes('protection-frames')?{frames:[frame],reason:null,live:{available:false,reason:'Cache-only session',estimate_usd:.0025}}:{live:false,result:null,notice:'Nothing recorded for this still yet.'}}));vi.stubGlobal('fetch',request);
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ProtectionPanel enabled/></QueryClientProvider>);
  const inline=await screen.findByAltText('Front left Duo: tap an object to protect it');
  expect(screen.getByText('Street masked · cropped to property')).toBeVisible();
  expect(screen.queryByText(/No reviewed exported still/)).not.toBeInTheDocument();
  fireEvent.click(inline);
  expect(await screen.findByRole('dialog',{name:'Protect an object'})).toBeVisible();
  expect(screen.queryByRole('button',{name:'Check recorded result'})).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Detect with SAM 3.1'})).toBeDisabled();
});
