import {chromium,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';

const sha=process.env.VIGIL_QA_SHA||execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const root=path.resolve('..','qa','screens',sha,process.env.VIGIL_QA_PHASE||'final');
const base=process.env.VIGIL_UI_BASE_URL||'http://127.0.0.1:8106/next/src/pages/settings/preview.html';
const sizes=[['air13',1470,870],['pro14',1512,895],['pro16',1728,1030],['win100',1920,960],['win125',1536,730],['win150',1280,600],['laptop',1366,650],['four-three',1024,768],['tablet',1180,820],['ultrawide',2560,1000],['phone',390,844]];
const selected=process.env.VIGIL_QA_FOCUSED?sizes.filter(([,w,h])=>w===1280&&h===600):sizes;
const browser=await chromium.launch();
const report={sha,started:new Date().toISOString(),cases:[],errors:[],failures:[],focus:[]};
for(const [label,width,height] of selected){for(const theme of ['dark','light']){
 const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
 const page=await context.newPage();const errors=[];let index=0;
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 page.on('requestfailed',r=>errors.push(`request ${r.url()}: ${r.failure()?.errorText}`));page.on('response',r=>{if(r.status()>=400)errors.push(`HTTP ${r.status()} ${r.url()}`);});
 const dir=path.join(root,`${label}-${width}x${height}`);await mkdir(dir,{recursive:true});
 const shot=async name=>page.screenshot({path:path.join(dir,`controls-${theme}-${String(index++).padStart(3,'0')}-${name}.png`),fullPage:width<=640&&await page.locator('.v-dialog-content:visible').count()===0,animations:'disabled'});
 const go=async(route='settings',extra='')=>{await page.goto(`${base}?theme=${theme}&route=${route}${extra}`,{waitUntil:'networkidle'});await page.evaluate(()=>document.fonts.ready);await expect(page.locator('.controls-page')).toBeVisible();};
 const layout=async(name)=>{
  const value=await page.evaluate(()=>({width:innerWidth,height:innerHeight,sw:document.documentElement.scrollWidth,sh:document.documentElement.scrollHeight,scrollY,cardOverflow:[...document.querySelectorAll('.controls-page .v-card,.controls-window')].filter(e=>e.scrollWidth>e.clientWidth||e.scrollHeight>e.clientHeight).map(e=>({text:e.textContent.slice(0,80),cw:e.clientWidth,sw:e.scrollWidth,ch:e.clientHeight,sh:e.scrollHeight}))}));
  expect(value.width).toBe(width);expect(value.height).toBe(height);expect(value.sw,`${label} ${theme} ${name} horizontal`).toBeLessThanOrEqual(width);
  if(width>640){expect(value.sh,`${label} ${theme} ${name} page scroll`).toBeLessThanOrEqual(height);expect(value.scrollY).toBe(0);}
  expect(value.cardOverflow,`${label} ${theme} ${name} intrinsic content`).toEqual([]);
  report.cases.push({label,width,height,theme,name,layout:value});
 };
 const hoverFocus=async(name,scope='.controls-page')=>{
  const controls=page.locator(`${scope} button:visible,${scope} input:visible,${scope} textarea:visible,${scope} select:visible`);
  for(let i=0;i<await controls.count();i++){
   const element=controls.nth(i);await element.scrollIntoViewIfNeeded();await element.hover();await shot(`${name}-hover-${i}`);
   if(await element.isEnabled()){
    await page.keyboard.press('Tab');await element.focus();const result=await element.evaluate(e=>({tag:e.tagName,controlLabel:e.getAttribute('aria-label')||e.textContent.slice(0,60),outline:getComputedStyle(e).outlineStyle,outlineWidth:parseFloat(getComputedStyle(e).outlineWidth),focused:document.activeElement===e}));
    report.focus.push({label,width,height,theme,name,...result});expect(result.focused).toBe(true);expect(result.outline).not.toBe('none');expect(result.outlineWidth).toBeGreaterThan(0);await shot(`${name}-focus-${i}`);
   }
  }
 };
 const scroll=async(name)=>{
  for(const panel of await page.locator('.controls-scroll:visible,.v-dialog-body:visible').all()){
   await panel.evaluate(e=>e.scrollTo({top:e.scrollHeight,behavior:'instant'}));
   await expect.poll(()=>panel.evaluate(e=>Math.abs(e.scrollTop-Math.max(0,e.scrollHeight-e.clientHeight)))).toBeLessThanOrEqual(1);
   await shot(`${name}-scroll-bottom`);await panel.evaluate(e=>e.scrollTo({top:0,behavior:'instant'}));await shot(`${name}-scroll-top`);
  }
 };
 try{
  await go();await layout('cameras');await shot('cameras');await hoverFocus('camera-tabs');await scroll('cameras');
  for(const tab of ['Privacy','Household','Owner controls']){
   await page.getByRole('tab',{name:tab,exact:true}).click();await layout(tab);await shot(tab.replaceAll(' ','-'));await hoverFocus(tab.replaceAll(' ','-'));await scroll(tab.replaceAll(' ','-'));
  }
  await expect(page.getByRole('button',{name:"I'm outside"})).toBeDisabled();await expect(page.getByRole('button',{name:'New expected window'})).toBeDisabled();await expect(page.getByLabel('Owner token')).toBeDisabled();
  await go('rules');await layout('rules');await shot('rules');await hoverFocus('rules');await scroll('rules');
  const observed=page.getByRole('button',{name:'Open observed visit'});await observed.scrollIntoViewIfNeeded();await observed.click();await expect(page.getByRole('dialog')).toBeVisible();await shot('protected-object-visit');await page.keyboard.press('Escape');await expect(observed).toBeFocused();
  await go('benchmark');await layout('benchmark');await expect(page.getByText('No field benchmark yet')).toBeVisible();await shot('benchmark');await scroll('benchmark');
  await go('settings','&context=edge');await page.getByRole('tab',{name:'Owner controls'}).click();await expect(page.getByRole('button',{name:"I'm outside"})).toBeDisabled();await page.getByLabel('Owner token').fill('authored-ui-test-value');await page.getByRole('button',{name:'Save owner token'}).click();await expect(page.getByRole('dialog',{name:'Fixture callback verification'})).toContainText('value not logged');await shot('edge-token-callback');await page.keyboard.press('Escape');await expect(page.getByLabel('Owner token')).toHaveValue('');
  await go('settings','&context=edge-owner');await page.getByRole('tab',{name:'Owner controls'}).click();await page.getByRole('button',{name:"I'm outside"}).click();await expect(page.getByRole('dialog')).toContainText('Check-in callback captured');await shot('checkin-callback');await page.keyboard.press('Escape');
  const opener=page.getByRole('button',{name:'New expected window'});await opener.click();await expect(page.getByRole('dialog',{name:'New expected window'})).toBeVisible();await shot('window-dialog');await hoverFocus('window-dialog','.v-dialog-content');
  await page.getByLabel('Window label').fill('Authored callback test');await page.getByLabel('Window starts').fill('2026-11-04T12:00');await page.getByLabel('Window ends').fill('2026-11-04T11:00');await page.getByRole('button',{name:'Create expected window'}).click();await expect(page.getByRole('alert')).toContainText('after');await shot('window-reversed');
  await page.getByLabel('Window ends').fill('2026-11-05T01:00');await page.getByRole('button',{name:'Create expected window'}).click();await expect(page.getByRole('alert')).toContainText('12 hours');await shot('window-too-long');
  await page.getByLabel('Window ends').fill('2026-11-04T13:00');await page.getByLabel('Window camera').click();await shot('camera-native-select');await page.keyboard.press('Escape');await page.getByLabel('Window camera').selectOption('doorbell');
  await page.getByRole('button',{name:'Create expected window'}).click();await expect(page.getByRole('dialog',{name:'Fixture callback verification'})).toContainText('Expected window callback captured');await shot('window-callback');await page.keyboard.press('Escape');await page.keyboard.press('Escape');await expect(opener).toBeFocused();
  await go('settings','&context=edge-owner&pending=1&error=1');await page.getByRole('tab',{name:'Owner controls'}).click();await expect(page.getByRole('alert')).toBeVisible();await expect(page.getByRole('button',{name:"I'm outside"})).toBeDisabled();await shot('owner-error-pending');
  await go('rules','&context=edge-owner&draft=1&notice=1');await page.getByLabel('Rule text').fill('Alert when a package is removed');await page.getByRole('button',{name:'Review rule draft'}).click();await expect(page.getByRole('dialog')).toContainText('Compile draft callback captured');await shot('compile-callback');await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Record a voice rule'}).click();await expect(page.getByRole('dialog')).toContainText('Phone recording callback captured');await shot('voice-callback');await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Confirm rule'}).scrollIntoViewIfNeeded();await shot('draft-and-notice');await page.getByRole('button',{name:'Confirm rule'}).click();await expect(page.getByRole('dialog')).toContainText('Confirm draft callback captured');await shot('confirm-callback');await page.keyboard.press('Escape');
  for(const route of ['settings','rules']){await go(route,'&context=empty');await layout(`empty-${route}`);await shot(`empty-${route}`);}
  await go();await page.getByRole('tab',{name:'Cameras',exact:true}).focus();await page.keyboard.press('ArrowRight');await expect(page.getByRole('tab',{name:'Privacy',exact:true})).toBeFocused();await page.keyboard.press('Tab');await shot('keyboard-panel');
  expect(errors).toEqual([]);
 }catch(error){report.failures.push({label,width,height,theme,error:String(error)});await shot('FAILURE');}
 report.errors.push(...errors.map(error=>({label,theme,error})));await context.close();
}}
report.finished=new Date().toISOString();await writeFile(path.join(root,'controls-results.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify({sha,cases:report.cases.length,focus:report.focus.length,failures:report.failures,errors:report.errors}));
if(report.failures.length||report.errors.length)process.exitCode=1;
