import {chromium,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const sha=execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const root=path.resolve('..','qa','screens',sha,'followup');await mkdir(root,{recursive:true});
const sizes=[[1470,870],[1512,895],[1728,1030],[1920,960],[1536,730],[1280,600],[1366,650],[1024,768],[1180,820],[2560,1000],[390,844]];
const browser=await chromium.launch();const report={sha,started:new Date().toISOString(),cases:[],errors:[]};
for(const [width,height] of sizes){for(const theme of ['dark','light']){
 const page=await browser.newPage({viewport:{width,height},reducedMotion:'no-preference'});
 page.on('pageerror',e=>report.errors.push(e.message));page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text());});page.on('requestfailed',r=>report.errors.push(r.url()));
 await page.goto(`http://127.0.0.1:8106/next/src/pages/settings/preview.html?context=edge-owner&theme=${theme}`);await page.evaluate(()=>document.fonts.ready);
 await page.getByRole('tab',{name:'Owner controls'}).click();await page.getByRole('button',{name:'New expected window'}).click();
 const contrasts=await page.locator('.v-dialog-content input,.v-dialog-content select').evaluateAll(elements=>{
  const l=value=>(value.match(/[\d.]+/g)||[]).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  const ratio=(a,b)=>(Math.max(l(a),l(b))+.05)/(Math.min(l(a),l(b))+.05);
  return elements.map(e=>{const c=getComputedStyle(e);return{boundary:ratio(c.borderTopColor,c.backgroundColor),text:ratio(c.color,c.backgroundColor)};});
 });
 expect(contrasts.every(c=>c.boundary>=3&&c.text>=4.5)).toBe(true);
 const tabs=[];
 for(let index=0;index<24;index++){
  await page.keyboard.press(index<16?'Tab':'Shift+Tab');
  const focus=await page.evaluate(()=>{const e=document.activeElement;return{tag:e?.tagName,type:e?.getAttribute('type'),label:e?.getAttribute('aria-label')||e?.id,inside:!!e?.closest('[role="dialog"]'),outline:e?getComputedStyle(e).outlineStyle:null,visible:e?.matches(':focus-visible'),within:e?.matches(':focus-within')};});
  if(focus.outline==='none'){console.log(JSON.stringify({width,height,theme,index,focus}));await page.screenshot({path:path.join(root,'keyboard-native-focus-before.png')});await writeFile(path.join(root,'keyboard-native-focus-before.json'),JSON.stringify({width,height,theme,index,focus},null,2));}
  expect(focus.inside).toBe(true);expect(focus.outline).not.toBe('none');tabs.push(focus);
 }
 await page.screenshot({path:path.join(root,`${width}x${height}-${theme}-keyboard-dialog.png`),animations:'disabled'});
 await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:'New expected window'})).toBeFocused();
 const scroll=page.locator('.controls-scroll');if(width>640){await scroll.hover();await page.mouse.wheel(0,3000);await expect.poll(()=>scroll.evaluate(e=>Math.abs(e.scrollTop-(e.scrollHeight-e.clientHeight)))).toBeLessThanOrEqual(1);}else{await page.mouse.wheel(0,3000);await expect.poll(()=>page.evaluate(()=>Math.abs(scrollY-(document.documentElement.scrollHeight-innerHeight)))).toBeLessThanOrEqual(1);}
 await page.screenshot({path:path.join(root,`${width}x${height}-${theme}-ordinary-scroll-bottom.png`),animations:'disabled'});
 report.cases.push({width,height,theme,contrasts,tabs});await page.close();
}}
report.finished=new Date().toISOString();await writeFile(path.join(root,'followup-results.json'),JSON.stringify(report,null,2));await browser.close();expect(report.errors).toEqual([]);console.log(JSON.stringify({cases:report.cases.length,keyboardSteps:report.cases.reduce((n,c)=>n+c.tabs.length,0),errors:report.errors}));
