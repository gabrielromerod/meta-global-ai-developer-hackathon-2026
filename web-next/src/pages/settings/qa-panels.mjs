import {chromium,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const sha=execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const root=path.resolve('..','qa','screens',sha,'panel-scroll');await mkdir(root,{recursive:true});
const sizes=[[1470,870],[1512,895],[1728,1030],[1920,960],[1536,730],[1280,600],[1366,650],[1024,768],[1180,820],[2560,1000],[390,844]];
const browser=await chromium.launch();const report={sha,started:new Date().toISOString(),cases:[],errors:[]};
for(const [width,height] of sizes){for(const theme of ['dark','light']){
 const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'});
 page.on('pageerror',e=>report.errors.push(e.message));page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text());});
 await page.goto(`http://127.0.0.1:8106/next/src/pages/settings/preview.html?theme=${theme}`);await page.evaluate(()=>document.fonts.ready);
 for(const tab of ['Cameras','Privacy','Household','Owner controls']){
  const trigger=page.getByRole('tab',{name:tab,exact:true});await trigger.click();await expect(trigger).toHaveAttribute('aria-selected','true');
  const panel=page.getByLabel(`${tab} settings`,{exact:true});await expect(panel).toBeVisible();
  if(width>640)await panel.evaluate(e=>e.scrollTo({top:0,behavior:'instant'}));else await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
  const name=tab.replaceAll(' ','-');await page.screenshot({path:path.join(root,`${width}x${height}-${theme}-${name}-top.png`)});
  if(width>640)await panel.evaluate(e=>e.scrollTo({top:e.scrollHeight,behavior:'instant'}));else await page.evaluate(()=>scrollTo({top:document.documentElement.scrollHeight,behavior:'instant'}));
  if(tab==='Cameras'){
   const last=page.getByRole('article',{name:'Backyard 2 camera'});const box=await last.boundingBox();expect(box.y+box.height).toBeLessThanOrEqual(height);expect(box.y).toBeGreaterThanOrEqual(0);
  }
  const actual=await page.evaluate(()=>({docHeight:document.documentElement.scrollHeight,scrollY,selected:document.querySelector('[role="tab"][aria-selected="true"]')?.textContent}));
  expect(actual.selected).toBe(tab);if(width>640){expect(actual.docHeight).toBeLessThanOrEqual(height);expect(actual.scrollY).toBe(0);}
  await page.screenshot({path:path.join(root,`${width}x${height}-${theme}-${name}-bottom.png`)});report.cases.push({width,height,theme,tab,actual});
 }
 await page.close();
}}
report.finished=new Date().toISOString();await writeFile(path.join(root,'panel-results.json'),JSON.stringify(report,null,2));await browser.close();expect(report.errors).toEqual([]);console.log(JSON.stringify({cases:report.cases.length,errors:report.errors}));
