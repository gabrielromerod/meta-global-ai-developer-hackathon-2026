import {chromium} from '../../web-next/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';import path from 'node:path';
const root=path.resolve('qa/screens/5f6f8893');const url='http://127.0.0.1:8116/next/src/pages/settings/preview.html';
const fixture=JSON.parse(await fs.readFile('web-next/src/fixtures/state.json','utf8'));
const browser=await chromium.launch();const report={cases:[],checks:[],errors:[]};
const check=(pass,label)=>{report.checks.push({pass,label});if(!pass)throw Error(label)};
for(const [width,height] of [[1470,870],[1512,895],[1728,1030],[1920,960],[1536,730],[1280,600],[1366,650],[1024,768],[1180,820],[2560,1000],[390,844]])for(const theme of ['dark','light']){
 const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'});page.on('pageerror',e=>report.errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text())});page.on('requestfailed',r=>report.errors.push(r.url()));
 const dir=path.join(root,`${width}x${height}`);await fs.mkdir(dir,{recursive:true});const shot=n=>page.screenshot({path:path.join(dir,`review-controls-${theme}-round2-${n}.png`)});
 await page.goto(`${url}?theme=${theme}`);await page.locator('body[data-ready="1"]').waitFor();
 await page.evaluate(async({fixture,theme})=>{
  const {default:React}=await import('/next/node_modules/.vite/deps/react.js');const {createRoot}=(await import('/next/node_modules/.vite/deps/react-dom_client.js')).default;
  const {SettingsPage}=await import('/next/src/pages/settings/index.tsx');const {AppShell}=await import('/next/src/shell/index.tsx');document.querySelector('#root').style.display='none';const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
  const state=structuredClone(fixture);state.mode='edge';state.owner.enabled=true;
  const template={...fixture.owner.windows[0],recorded:false,state:'scheduled'};
  const longZone='review_fixture_very_long_zone_identifier_without_a_break_012345678901234567890123456789';
  state.owner.windows=[...fixture.owner.windows,
   {...template,id:'probe-zone-only',label:'Authored zone-only window',cameras:[],zones:['side_alley']},
   {...template,id:'probe-camera-only',label:'Authored camera-only window',cameras:['doorbell'],zones:[]},
   {...template,id:'probe-combined',label:'Authored camera and zone window',cameras:['doorbell'],zones:['side_alley']},
   {...template,id:'probe-all',label:'Authored unrestricted window',cameras:[],zones:[]},
   {...template,id:'probe-long-zone',label:'Authored long multiple-zone scope wrapping and scrolling review fixture',cameras:[],zones:['side_alley','front_door_egress','backyard_interior',longZone,'another_authored_zone_identifier_for_multiline_scope']},
   {...template,id:'probe-long-combined',label:'Authored long combined scope wrapping and scrolling review fixture',cameras:['doorbell','front_left','authored_missing_camera_identifier_0123456789012345678901234567890123456789'],zones:['side_alley',longZone]}];
  const rr=window.__r2={state,calls:[],pending:false};rr.render=()=>root.render(React.createElement(AppShell,{route:'settings',onNavigate:()=>{},state:rr.state,theme,onThemeChange:()=>{},onOpenVisit:()=>{}},React.createElement(SettingsPage,{state:rr.state,onOpenVisit:()=>{},onOpenClip:()=>{},ownerActions:{pending:rr.pending,saveToken:()=>rr.calls.push('saveToken'),checkIn:()=>rr.calls.push('checkIn'),createWindow:()=>rr.calls.push('createWindow'),cancelWindow:id=>rr.calls.push(id)}})));rr.render();
 },{fixture,theme});
 await page.getByRole('tab',{name:'Owner controls',exact:true}).click();await page.evaluate(()=>document.fonts.ready);
 const descriptions=[['Authored zone-only window',['Zones: Side alley'],['Cameras:','All configured cameras']],['Authored camera-only window',['Cameras: Doorbell'],['Zones:','All configured cameras']],['Authored camera and zone window',['Cameras: Doorbell','Zones: Side alley'],['All configured cameras']],['Authored unrestricted window',['All configured cameras'],['Cameras:','Zones:']]];
 for(const [label,present,absent]of descriptions){const row=page.getByRole('article',{name:label,exact:true});const text=await row.innerText();for(const v of present)check(text.includes(v),`${width}/${theme}/${label} includes ${v}`);for(const v of absent)check(!text.includes(v),`${width}/${theme}/${label} omits ${v}`);}
 const layout=await page.evaluate(()=>({width:innerWidth,height:innerHeight,sw:document.documentElement.scrollWidth,sh:document.documentElement.scrollHeight,gutter:getComputedStyle([...document.querySelectorAll('.controls-scroll')].find(e=>e.getClientRects().length)).scrollbarGutter}));check(layout.width===width&&layout.height===height,'exact CSS viewport');check(layout.sw===width,'no horizontal document overflow');if(width>640){check(layout.sh===height,'no desktop document scroll');check(layout.gutter==='stable','stable panel gutter');}
 await shot('list-top');
 const rows=page.locator('.controls-window');for(let i=0;i<await rows.count();i++){
  const row=rows.nth(i);await row.scrollIntoViewIfNeeded();const dims=await row.evaluate(e=>({id:e.getAttribute('aria-label'),sw:e.scrollWidth,cw:e.clientWidth,rect:e.getBoundingClientRect().toJSON(),text:[...e.querySelectorAll('p')].map(n=>({text:n.textContent,rect:n.getBoundingClientRect().toJSON(),sw:n.scrollWidth,cw:n.clientWidth}))}));
  check(dims.sw<=dims.cw,`${width}/${theme}/${dims.id}: no row overflow`);for(const t of dims.text)check(t.sw<=t.cw,`${width}/${theme}/${dims.id}: scope text wraps`);
  await row.getByRole('button',{name:'Cancel window',exact:true}).hover({force:true});await shot(`row-${i}`);
 }
 const scroller=page.getByLabel('Owner controls settings',{exact:true});if(width>640){const b=await scroller.boundingBox();await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.wheel(0,20000);await page.waitForTimeout(50);check(await scroller.evaluate(e=>e.scrollTop+e.clientHeight>=e.scrollHeight-2),'complete internal wheel scroll');}else{await page.mouse.move(width-10,height/2);await page.mouse.wheel(0,20000);await page.waitForTimeout(50);check(await page.evaluate(()=>scrollY+innerHeight>=document.documentElement.scrollHeight-2),'complete phone scroll');}await shot('list-bottom');
 // The four scope combinations use the same mutable ID callback and owner guards.
 if(width===1280||width===390){
  for(const [label]of descriptions){const row=page.getByRole('article',{name:label,exact:true});const button=row.getByRole('button',{name:'Cancel window',exact:true});check(await button.isEnabled(),'owner callback allows mutable row');await button.click();}
  check(await page.evaluate(()=>['probe-zone-only','probe-camera-only','probe-combined','probe-all'].every(id=>window.__r2.calls.includes(id))),'all four actual cancellation IDs');check(await page.getByRole('article',{name:'deliveries',exact:true}).getByRole('button',{name:'Cancel window'}).isDisabled(),'recorded row remains immutable');
  await page.evaluate(()=>{window.__r2.pending=true;window.__r2.render()});await page.waitForTimeout(50);for(const [label]of descriptions)check(await page.getByRole('article',{name:label,exact:true}).getByRole('button',{name:'Cancel window'}).isDisabled(),'pending disables each scoped row');await shot('pending');
  await page.evaluate(()=>{window.__r2.pending=false;window.__r2.state.owner.enabled=false;window.__r2.render()});await page.waitForTimeout(50);check(await page.getByRole('button',{name:'New expected window',exact:true}).isDisabled(),'revoked owner cannot create');for(const [label]of descriptions)check(await page.getByRole('article',{name:label,exact:true}).getByRole('button',{name:'Cancel window'}).isDisabled(),'revoked owner cannot cancel scope');
  await page.getByText('Owner-only on the home box',{exact:true}).scrollIntoViewIfNeeded();await shot('owner-revoked');
 }
 report.cases.push({width,height,theme,layout});await page.close();
}
await browser.close();await fs.writeFile(path.join(root,'review-controls-round2-results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({cases:report.cases.length,checks:report.checks.length,errors:report.errors,failed:report.checks.filter(c=>!c.pass)}));
