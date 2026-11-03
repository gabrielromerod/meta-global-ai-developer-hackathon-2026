import {chromium,expect} from '../web-next/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve('qa/screens/7c2ea321');
const source='http://127.0.0.1:8115/next/src/pages/clips/preview.html';
const fixture=JSON.parse(await fs.readFile('web-next/src/fixtures/state.json','utf8'));
const matrix=[[1470,870],[1512,895],[1728,1030],[1920,960],[1536,730],[1280,600],[1366,650],[1024,768],[1180,820],[2560,1000],[390,844]].filter(([w])=>!process.env.REVIEW_WIDTHS||process.env.REVIEW_WIDTHS.split(',').includes(String(w)));
const resultFile=`review-clips-results${process.env.REVIEW_PART?'-part'+process.env.REVIEW_PART:''}.json`;
const report={source,sha:'7c2ea321bde6ff0e753be4c855f424d983ea2efb',started:new Date().toISOString(),cases:[],failures:[]};
const browser=await chromium.launch();
const ordered=[...fixture.clips].sort((a,b)=>b.t0-a.t0||a.id.localeCompare(b.id));
const cameraNames=Object.fromEntries(fixture.cameras.map(c=>[c.id,c.name]));
const verdictNames={'':'All verdicts',normal:'Normal',noteworthy:'Noteworthy',needs_attention:'Needs attention',cant_confirm:"Can't confirm"};
function assert(value,message){if(!value)throw Error(message);}
for(const [width,height] of matrix) for(const theme of ['dark','light']) for(const route of ['clips','media']){
 const folder=path.join(root,`${width}x${height}`);await fs.mkdir(folder,{recursive:true});
 const context=await browser.newContext({viewport:{width,height},timezoneId:'America/Los_Angeles',reducedMotion:'reduce',deviceScaleFactor:1});
 const page=await context.newPage();page.setDefaultTimeout(6000);
 const entry={width,height,theme,route,errors:[],requests:[],checks:[],contrast:[],focus:[],screens:[]};
 page.on('pageerror',e=>entry.errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')entry.errors.push(m.text());});
 page.on('requestfailed',r=>entry.requests.push(r.url()));page.on('response',r=>{if(r.status()>=400)entry.requests.push(r.status()+' '+r.url());});
 let n=0;
 async function snap(label,element){const file=`review-clips-${route}-${theme}-${String(n++).padStart(3,'0')}-${label}.png`;await (element??page).screenshot({path:path.join(folder,file),...(element?{}:{fullPage:false})});entry.screens.push(file);}
 const clear=()=>page.getByRole('button',{name:'Clear filters',exact:true}).click();
 const list=()=>page.locator('.evidence-grid li');
 async function select(name,label){await page.getByRole('combobox',{name,exact:true}).click();await page.getByRole('option',{name:label,exact:true}).click();}
 async function geometry(label){entry.checks.push({label,...await page.evaluate(()=>({width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,documentHeight:document.documentElement.scrollHeight,firstTitleBottom:document.querySelector('.v-clip-caption strong')?.getBoundingClientRect().bottom,firstVerdictBottom:document.querySelector('.evidence-grid .v-verdict')?.getBoundingClientRect().bottom,clipped:[...document.querySelectorAll('.v-clip-card,.v-clip-caption')].filter(e=>e.scrollHeight>e.clientHeight+1).length}))});const g=entry.checks.at(-1);assert(g.width===width&&g.height===height,'exact CSS viewport');assert(g.documentWidth<=width,'horizontal overflow');if(width>640){assert(g.documentHeight<=height,'desktop document scroll');if(label==='initial')assert(g.firstTitleBottom<=height&&g.firstVerdictBottom<=height,'initial verdict/story below fold');}assert(g.clipped===0,'shrunk card caption');}
 async function contrast(el,label){entry.contrast.push({label,...await el.evaluate(el=>{
  const rgb=v=>(v.match(/[\d.]+/g)||[]).map(Number);const blend=(fg,bg)=>fg.slice(0,3).map((v,i)=>v*(fg[3]??1)+bg[i]*(1-(fg[3]??1)));
  const surf=e=>e?blend(rgb(getComputedStyle(e).backgroundColor),surf(e.parentElement)):[255,255,255];
  const lum=c=>c.map(v=>v/255).map(s=>s<=.04045?s/12.92:((s+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  const ratio=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);const s=getComputedStyle(el),outer=surf(el.parentElement),inner=surf(el),border=blend(rgb(s.borderTopColor),outer);
  return {text:ratio(blend(rgb(s.color),inner),inner),inside:ratio(border,inner),outside:ratio(border,outer),outline:s.outline};
 })});const v=entry.contrast.at(-1);assert(v.text>=4.5,`${label} text contrast ${v.text}`);assert(v.inside>=3&&v.outside>=3,`${label} field boundary ${v.inside}/${v.outside}`);}
 try{
  await page.goto(`${source}?route=${route}&theme=${theme}`);await page.waitForFunction(()=>document.body.dataset.ready==='1');await page.evaluate(()=>document.fonts.ready);await expect(list()).toHaveCount(5);await geometry('initial');await snap('initial');
  assert(await page.locator('.evidence-page img,.evidence-page video').count()===0,'invented media');await expect(page.getByText('Demo data',{exact:true})).toBeVisible();
  for(const el of await page.locator('.evidence-page button,.evidence-page input').all()){await el.hover();await snap('hover',el);}
  for(const el of await page.locator('.evidence-page input,.evidence-page button:not([role=tab]):not(.v-clip-card)').all()){
   if(await el.isEnabled()){await el.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');await snap('focus',el);const f=await el.evaluate(e=>({outline:getComputedStyle(e).outlineStyle,width:parseFloat(getComputedStyle(e).outlineWidth),name:e.getAttribute('aria-label')||e.textContent}));entry.focus.push(f);assert(f.width>0&&f.outline!=='none','missing keyboard focus '+f.name);}
  }
  for(const el of await page.locator('.evidence-control').all()){await page.mouse.move(0,0);await el.evaluate(e=>e.blur());await contrast(el,'rest');await el.hover();await contrast(el,'hover');await el.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');await contrast(el,'focus');}
  for(const name of ['Camera','Verdict']){
   const trigger=page.getByRole('combobox',{name,exact:true});await trigger.click();await expect(page.getByRole('listbox')).toBeVisible();await snap(`${name}-menu`);await expect(page.getByRole('listbox')).toBeVisible();
   for(const option of await page.getByRole('option').all()){await option.hover();await snap(`${name}-option-hover`,option);}
   await page.keyboard.press('Escape');await expect(trigger).toBeFocused();await trigger.press('Enter');await expect(page.getByRole('listbox')).toBeVisible();await expect(page.getByRole('option').first()).toBeFocused();await page.keyboard.press('ArrowDown');await expect(page.getByRole('option').nth(1)).toBeFocused();await page.keyboard.press('Enter');await expect(page.getByRole('listbox')).toHaveCount(0);await expect(trigger).toContainText(name==='Camera'?'Front left Duo':'Normal');await clear();
  }
  for(const camera of fixture.cameras){await select('Camera',camera.name);await expect(list()).toHaveCount(fixture.clips.filter(c=>c.camera_id===camera.id).length);await clear();}
  for(const [id,label] of Object.entries(verdictNames)){await select('Verdict',label);await expect(list()).toHaveCount(fixture.clips.filter(c=>!id||c.verdict===id).length);if(id)await clear();}
  for(const [label,kind] of [['People','person'],['Vehicles','vehicle'],['Packages','package'],['All clips','']]){await page.getByRole('tab',{name:label,exact:true}).click();await expect(list()).toHaveCount(fixture.clips.filter(c=>!kind||c.kind===kind).length);if(kind==='vehicle')await snap('unavailable-category');}
  const search=page.getByRole('searchbox',{name:'Search evidence'});await search.fill('unseen meteor');await expect(list()).toHaveCount(0);await snap('empty-query');await clear();
  await search.fill('gate');await select('Camera','Doorbell');await select('Verdict','Needs attention');await page.getByRole('tab',{name:'People',exact:true}).click();await expect(list()).toHaveCount(1);
  if(route==='media'){
   const open=()=>page.getByRole('button',{name:/^Time range/}).click();await open();await snap('time-dialog');
   const from=page.getByLabel('From (local time)',{exact:true}),until=page.getByLabel('Until (local time)',{exact:true});
   for(const el of await page.getByRole('dialog').locator('input,button').all()){await el.hover();await snap('date-hover',el);if(await el.isEnabled()){await el.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');await snap('date-focus',el);}}
   for(const el of [from,until])for(const state of ['rest','hover','focus']){await el.evaluate(e=>e.blur());if(state==='hover')await el.hover();if(state==='focus')await el.focus();await contrast(el,'date '+state);}
   await from.fill('2026-11-02T18:00');await until.fill('2026-11-02T18:15');await page.getByRole('button',{name:'Done',exact:true}).click();
   const clip=fixture.clips.find(c=>c.camera_id==='doorbell'&&c.verdict==='needs_attention');const actualAt=Date.parse(fixture.session.start)+clip.t0*1000;
   const expected=fixture.clips.filter(c=>c.camera_id==='doorbell'&&c.verdict==='needs_attention'&&c.kind==='person'&&actualAt>=Date.parse('2026-11-02T18:00-08:00')&&actualAt<=Date.parse('2026-11-02T18:15-08:00')).length;
   await expect(list()).toHaveCount(expected);
  }
  await page.getByRole('button',{name:'Apply filters',exact:true}).click();let submitted=await page.evaluate(()=>window.clipsReview.lastSearch);assert(submitted.q==='gate'&&submitted.camera==='doorbell'&&submitted.verdict==='needs_attention'&&submitted.kind==='person','filter intersection callback');if(route==='media'){assert(submitted.start==='2026-11-03T02:00:00.000Z'&&submitted.end==='2026-11-03T02:15:00.000Z','timezone-aware ISO dates');}entry.submitted=submitted;await snap('intersection');await clear();
  if(route==='media'){
   await page.getByRole('button',{name:'Time range',exact:true}).click();await page.getByLabel('From (local time)',{exact:true}).fill('2026-11-03T19:00');await page.getByLabel('Until (local time)',{exact:true}).fill('2026-11-03T18:00');await expect(page.getByRole('alert')).toContainText('end time on or after');await snap('reversed-range');await page.getByRole('button',{name:'Done',exact:true}).click();await expect(page.getByRole('button',{name:'Apply filters',exact:true})).toBeDisabled();await expect(list()).toHaveCount(0);await clear();
   await page.getByRole('button',{name:'Time range',exact:true}).click();await page.getByLabel('From (local time)',{exact:true}).fill('2026-11-02T14:00');await page.getByRole('button',{name:'Clear time range',exact:true}).click();await expect(page.getByLabel('From (local time)',{exact:true})).toHaveValue('');await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:'Time range',exact:true})).toBeFocused();
  }
  for(let i=0;i<ordered.length;i++){
   const card=page.locator('.v-clip-card').nth(i);await card.click();assert(await page.evaluate(()=>window.clipsReview.lastClipId)===ordered[i].id,'actual clip ID');await expect(page.getByRole('dialog').getByText('Media unavailable',{exact:true})).toBeVisible();await snap(`clip-${ordered[i].id}`);await page.locator('.v-dialog-body').evaluate(e=>e.scrollTop=e.scrollHeight);await snap(`clip-${i}-scroll-bottom`);
   if(i===0){await page.getByRole('button',{name:'Open visit evidence',exact:true}).click();assert(await page.evaluate(()=>window.clipsReview.lastVisitId)===ordered[i].visit_id,'actual visit ID');await snap('visit-evidence');await page.getByRole('button',{name:'Close Visit evidence',exact:true}).click();}else{await page.keyboard.press('Escape');await expect(card).toBeFocused();}
  }
  await page.getByRole('region',{name:'Clip results',exact:true}).evaluate(e=>e.scrollTop=0);await snap('results-top');await page.getByRole('region',{name:'Clip results',exact:true}).evaluate(e=>e.scrollTop=e.scrollHeight);await page.waitForTimeout(100);await snap('results-bottom');
  if(width<641){await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));await snap('document-bottom');}await geometry('final');
  assert(entry.errors.length===0,'console errors');assert(entry.requests.length===0,'request failures');report.cases.push(entry);
 }catch(e){entry.error=String(e);await snap('FAILURE').catch(()=>{});report.failures.push(entry);console.log('FAIL',width,height,theme,route,String(e));}finally{await context.close();await fs.writeFile(path.join(root,resultFile),JSON.stringify(report,null,2));}
 console.log('CASE',width,height,theme,route,entry.error??'PASS',n);
}
await browser.close();report.finished=new Date().toISOString();await fs.writeFile(path.join(root,resultFile),JSON.stringify(report,null,2));console.log('FINISHED',report.cases.length,report.failures.length);if(report.failures.length)process.exitCode=1;
