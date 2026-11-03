import {chromium} from '../../web-next/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve('qa/screens/5f6f8893');const url='http://127.0.0.1:8116/next/src/pages/settings/preview.html';
const fixture=JSON.parse(await fs.readFile('web-next/src/fixtures/state.json','utf8'));
const browser=await chromium.launch();const results=[];const failures=[];
const assert=(v,m)=>{results.push({check:m,pass:!!v});if(!v)failures.push(m)};
for(const [width,height] of [[1280,600],[390,844]])for(const theme of ['dark','light']){
 const page=await browser.newPage({viewport:{width,height},timezoneId:'America/Los_Angeles',reducedMotion:'no-preference'});
 await page.goto(`${url}?theme=${theme}`);await page.locator('body[data-ready="1"]').waitFor();
 await page.evaluate(async({fixture,theme})=>{
  const {default:React}=await import('/next/node_modules/.vite/deps/react.js');const {createRoot}=(await import('/next/node_modules/.vite/deps/react-dom_client.js')).default;
  const {SettingsPage}=await import('/next/src/pages/settings/index.tsx');const {RulesPage}=await import('/next/src/pages/rules/index.tsx');const {BenchmarkPage}=await import('/next/src/pages/benchmark/index.tsx');const {AppShell}=await import('/next/src/shell/index.tsx');
  document.querySelector('#root').style.display='none';const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
  const rr=window.__rr={state:structuredClone(fixture),calls:[],ownerKeys:['saveToken','checkIn','createWindow','cancelWindow'],ruleKeys:['compile','confirm','recordVoice','transcribeFixture'],page:'settings',ownerExtra:{},ruleExtra:{}};
  rr.render=()=>{const own=Object.fromEntries(rr.ownerKeys.map(k=>[k,(...args)=>rr.calls.push({kind:k,args})]));const rule=Object.fromEntries(rr.ruleKeys.map(k=>[k,(...args)=>rr.calls.push({kind:k,args})]));const props={state:rr.state,ownerActions:{...own,...rr.ownerExtra},ruleActions:{...rule,...rr.ruleExtra},onOpenVisit:id=>rr.calls.push({kind:'visit',args:[id]}),onOpenClip:()=>{}};root.render(React.createElement(AppShell,{route:rr.page,onNavigate:r=>{rr.page=r;rr.render()},state:rr.state,theme,onThemeChange:()=>{},onOpenVisit:props.onOpenVisit},React.createElement(rr.page==='settings'?SettingsPage:rr.page==='rules'?RulesPage:BenchmarkPage,props)));};rr.render();
 },{fixture,theme});
 const dir=path.join(root,`${width}x${height}`);const shot=async n=>page.screenshot({path:path.join(dir,`review-controls-${theme}-independent-${n}.png`)});
 const set=async changes=>{await page.evaluate(changes=>{const r=window.__rr;for(const [k,v]of Object.entries(changes))r[k]=v;r.render()},changes);await page.waitForTimeout(80)};
 const state=structuredClone(fixture);state.mode='edge';state.owner.enabled=true;state.owner.windows.push({...fixture.owner.windows[0],id:'owner-mutable-window',recorded:false,state:'scheduled',label:'UI probe: mutable scheduled window'});
 await set({state});await page.getByRole('tab',{name:'Owner controls',exact:true}).click();
 const ownerOnly='Owner-only on the home box';
 await set({ownerKeys:[]});assert(await page.getByLabel('Owner token',{exact:true}).isDisabled(),'edge owner without callback token disabled');assert(await page.getByRole('button',{name:"I'm outside",exact:true}).isDisabled(),'edge owner without callback checkin disabled');assert(await page.getByRole('button',{name:'New expected window',exact:true}).isDisabled(),'edge owner without callback creation disabled');
 await set({ownerKeys:['saveToken','checkIn','createWindow','cancelWindow']});
 await page.getByLabel('Owner token',{exact:true}).fill('offline-review-only');await page.getByRole('button',{name:'Save owner token',exact:true}).click();
 assert(await page.getByLabel('Owner token',{exact:true}).inputValue()==='','token clears');assert(await page.evaluate(()=>!location.href.includes('offline-review-only')&&!JSON.stringify(localStorage).includes('offline-review-only')&&!JSON.stringify(sessionStorage).includes('offline-review-only')),'no token in URL/localStorage/sessionStorage');
 // Do not emit callback args: they contain the deliberately fake token.
 await page.getByRole('article',{name:'UI probe: mutable scheduled window'}).getByRole('button',{name:'Cancel window'}).click();assert(await page.evaluate(()=>window.__rr.calls.some(c=>c.kind==='cancelWindow'&&c.args[0]==='owner-mutable-window')),'cancellation receives exact mutable window ID');
 assert(await page.getByRole('article',{name:'deliveries',exact:true}).getByRole('button',{name:'Cancel window'}).isDisabled(),'recorded B-prime cannot cancel');
 // A legal zone-only window must not be relabelled as an all-camera window.
 state.owner.windows.push({...fixture.owner.windows[0],id:'zone-scope-probe',recorded:false,state:'scheduled',label:'UI probe: side-alley-only scope',cameras:[],zones:['side_alley']});
 await set({state});await page.getByRole('article',{name:'UI probe: side-alley-only scope',exact:true}).scrollIntoViewIfNeeded();await shot('zone-scope');
 assert((await page.getByRole('article',{name:'UI probe: side-alley-only scope',exact:true}).innerText()).includes('Zones: Side alley'),'zone-only window exposes actual supplied zone scope');
 await set({ownerExtra:{checkinExpiresAt:new Date(Date.now()+2300).toISOString()}});assert((await page.getByRole('status').last().innerText()).includes('remaining'),'server supplied countdown visible');await page.waitForTimeout(3000);assert(await page.getByText('Check-in window ended',{exact:true}).isVisible(),'countdown expires without mutating props');await shot('checkin-ended');
 await set({ownerExtra:{}});await page.getByRole('button',{name:'New expected window',exact:true}).click();await page.getByRole('button',{name:'Create expected window',exact:true}).click();assert((await page.getByRole('alert').innerText()).includes('valid start and end'),'empty native date validation');
 await page.getByLabel('Window label',{exact:true}).fill('UI probe: expected delivery');await page.getByLabel('Window starts',{exact:true}).fill('2026-11-04T12:00');await page.getByLabel('Window ends',{exact:true}).fill('2026-11-05T00:00');await page.getByLabel('Window camera',{exact:true}).selectOption('doorbell');await page.getByRole('button',{name:'Create expected window',exact:true}).click();
 const input=await page.evaluate(()=>window.__rr.calls.findLast(c=>c.kind==='createWindow').args[0]);assert(input.start==='2026-11-04T20:00:00.000Z'&&input.end==='2026-11-05T08:00:00.000Z'&&input.cameras[0]==='doorbell','12h boundary sends browser timezone as correct UTC instant');
 state.owner.windows.push({...input,id:'recorded-server-probe',recorded:true,state:'scheduled',created_at:input.start});await set({state});assert(await page.getByRole('dialog',{name:'New expected window',exact:true}).isVisible(),'matching recorded row does not acknowledge create');
 state.owner.windows.push({...input,id:'unrelated-server-probe',label:'Unrelated window',recorded:false,state:'scheduled',created_at:input.start});await set({state});assert(await page.getByRole('dialog',{name:'New expected window',exact:true}).isVisible(),'unrelated server prop does not acknowledge create');await shot('awaiting-matching-prop');
 state.owner.windows.push({...input,id:'matching-server-probe',recorded:false,state:'scheduled',created_at:input.start});await set({state});assert(await page.getByRole('dialog').count()===0,'matching new server owned prop closes create');
 // Pending errors render from caller; all mutators must disable even authenticated.
 await set({ownerExtra:{pending:true,error:'UI probe: server refused this owner change'}});assert(await page.getByRole('button',{name:"I'm outside",exact:true}).isDisabled(),'pending disables checkin');assert(await page.getByRole('button',{name:'New expected window',exact:true}).isDisabled(),'pending disables create');await shot('pending-error');
 // Known and unknown privacy props exercise exact bool and blocked override.
 state.cameras[0].privacy_reviewed=true;state.cameras[1].privacy_reviewed=false;state.cameras[2].privacy_reviewed=true;state.cameras[2].status='privacy_blocked';delete state.cameras[3].privacy_reviewed;
 await set({state});await page.getByRole('tab',{name:'Privacy',exact:true}).click();assert(await page.getByText('Reviewed',{exact:true}).count()===1,'exact true only review approval');await shot('privacy-exact-props');
 await set({page:'rules',ruleExtra:{draft:{...state.rules[0],id:'ui-probe-draft',state:'draft'},notice:'UI probe: supplied recorded compilation notice',voiceFixtures:[{id:'phone-fixture-id',label:'UI probe: consented phone sample',url:null}]}});
 await page.getByLabel('Rule text').fill('  Package removed  ');await page.getByRole('button',{name:'Review rule draft',exact:true}).click();assert(await page.evaluate(()=>window.__rr.calls.some(c=>c.kind==='compile'&&c.args[0]==='Package removed')),'compile receives trimmed draft text');
 await page.getByRole('button',{name:'UI probe: consented phone sample',exact:true}).click();await page.getByRole('button',{name:'Record a voice rule',exact:true}).click();assert(await page.evaluate(()=>window.__rr.calls.some(c=>c.kind==='transcribeFixture'&&c.args[0]==='phone-fixture-id')&&window.__rr.calls.some(c=>c.kind==='recordVoice')),'phone sample and recording callbacks remain separate');
 await page.getByRole('button',{name:'Confirm rule',exact:true}).click();assert(await page.evaluate(()=>window.__rr.calls.some(c=>c.kind==='confirm'&&c.args[0]==='ui-probe-draft')),'confirmation passes supplied draft ID');await shot('draft-owner');
 state.owner.enabled=false;await set({state});assert(await page.getByRole('button',{name:'Confirm rule',exact:true}).isDisabled(),'confirmation disabled after owner revoked');assert(await page.getByText(ownerOnly,{exact:true}).isVisible(),'revoked confirmation has exact guard');await shot('draft-owner-revoked');
 await set({page:'benchmark'});state.benchmark={measured:false,note:'UI probe: model examples are authored',metrics:[{label:'Must not appear',value:'99.999%'}]};await set({state});assert(await page.getByText('99.999%',{exact:true}).count()===0,'unmeasured metrics suppressed');await shot('benchmark-unmeasured');
 state.benchmark={measured:true,note:'UI probe only: not actual field results',metrics:[{id:'synthetic-probe',label:'Supplied test metric',value:7.25,unit:'s',note:'Authored solely to test measured branch'}]};await set({state});assert(await page.getByText('7.25 s',{exact:true}).isVisible(),'measured branch uses exact provided metric');await shot('benchmark-measured-prop');
 await page.close();
}
await browser.close();await fs.writeFile(path.join(root,'review-controls-edge-results.json'),JSON.stringify({results,failures},null,2));console.log(JSON.stringify({checks:results.length,failures}));
