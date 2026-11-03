import {chromium} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';

const sha=execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const root=path.resolve('..','qa','screens',sha);
const viewports=[['air13',1470,870],['pro14',1512,895],['pro16',1728,1030],['win100',1920,960],['win125',1536,730],['win150',1280,600],['laptop',1366,650],['four-three',1024,768],['tablet',1180,820],['ultrawide',2560,1000],['phone',390,844]];
const browser=await chromium.launch({headless:true});
const results=[];
for(const [label,width,height] of viewports) {
 for(const theme of ['dark','light']) {
  const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
  const page=await context.newPage();
  const errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  page.on('requestfailed',request=>errors.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`));
  page.on('response',response=>{if(response.status()>=400)errors.push(`${response.status()} ${response.url()}`);});
  const directory=path.join(root,`${label}-${width}x${height}`);
  await mkdir(directory,{recursive:true});
  const shot=async name=>page.screenshot({path:path.join(directory,`home-${theme}-${name}.png`),fullPage:true,animations:'disabled'});
  await page.goto(`http://127.0.0.1:8103/next/src/pages/home/preview.html?theme=${theme}`,{waitUntil:'networkidle'});
  await page.getByRole('region',{name:'Same action, different context'}).waitFor();
  await shot('overview');
  const layout=await page.evaluate(()=>({width:innerWidth,height:innerHeight,docWidth:document.documentElement.scrollWidth,docHeight:document.documentElement.scrollHeight,comparisonBottom:document.querySelector('.home-context').getBoundingClientRect().bottom,twinHeight:document.querySelector('.home-twin').getBoundingClientRect().height}));
  if(layout.docWidth>width)errors.push(`Document horizontal overflow ${layout.docWidth}>${width}`);
  if(width>640&&layout.docHeight>height)errors.push(`Desktop document scroll ${layout.docHeight}>${height}`);
  if(width>640&&layout.comparisonBottom>height)errors.push(`Comparison clipped at ${layout.comparisonBottom}`);
  if(width>640&&layout.twinHeight<184)errors.push(`House hero collapsed to ${layout.twinHeight}px`);
  const slot=await page.locator('.home-twin').evaluate(element=>({width:element.clientWidth,childWidth:element.firstElementChild?.getBoundingClientRect().width ?? 0}));
  if(slot.childWidth<slot.width-2)errors.push(`House slot child collapsed to ${slot.childWidth}px within ${slot.width}px`);
  const tabs=page.getByRole('tab');
  const tabCount=await tabs.count();
  for(let i=0;i<tabCount;i++) {
    const tab=tabs.nth(i);
    await tab.scrollIntoViewIfNeeded(); await tab.hover(); await shot(`view-${i}-hover`);
    await tab.click();
    if(await tab.getAttribute('aria-selected')!=='true')errors.push(`View tab ${i} did not select`);
  }
  await tabs.first().click();
  const touch=page.getByRole('button',{name:'Open household side gate visit'});
  await touch.scrollIntoViewIfNeeded();await touch.hover();await shot('household-hover');await touch.focus();await shot('household-focus');
  await page.keyboard.press('Enter'); await page.getByRole('dialog',{name:'Visit evidence'}).waitFor();await shot('household-dialog');
  await page.keyboard.press('Escape');
  if(!(await touch.evaluate(element=>element===document.activeElement)))errors.push('Dialog did not restore opener focus');
  const external=page.getByRole('button',{name:'Open external side gate visit'});
  await external.scrollIntoViewIfNeeded();await external.hover();await shot('external-hover');await external.click();
  await page.getByRole('dialog',{name:'Visit evidence'}).waitFor();await shot('external-dialog');await page.keyboard.press('Escape');
  const visits=page.locator('.home-attention-list').getByRole('button');
  for(let i=0;i<await visits.count();i++){await visits.nth(i).scrollIntoViewIfNeeded();await visits.nth(i).hover();await shot(`review-${i}-hover`);await visits.nth(i).click();await page.getByRole('dialog',{name:'Visit evidence'}).waitFor();await page.keyboard.press('Escape');}
  await page.locator('.home-attention-list').evaluate(element=>element.scrollTop=element.scrollHeight);await shot('review-bottom');
  await page.goto(`http://127.0.0.1:8103/next/src/pages/home/preview.html?route=attention&theme=${theme}`,{waitUntil:'networkidle'});
  await page.getByRole('tab',{name:'All visits'}).waitFor();await shot('attention-all');
  const filters=page.getByRole('tab');
  for(let i=0;i<await filters.count();i++){await filters.nth(i).scrollIntoViewIfNeeded();await filters.nth(i).hover();await shot(`attention-filter-${i}-hover`);await filters.nth(i).click();await shot(`attention-filter-${i}`);}
  await filters.first().click();
  const attentionVisits=page.locator('.attention-visit-list').getByRole('button');
  for(let i=0;i<await attentionVisits.count();i++){await attentionVisits.nth(i).scrollIntoViewIfNeeded();await attentionVisits.nth(i).hover();await shot(`attention-visit-${i}-hover`);await attentionVisits.nth(i).focus();await page.keyboard.press('Enter');await page.getByRole('dialog',{name:'Visit evidence'}).waitFor();await shot(`attention-visit-${i}-dialog`);await page.keyboard.press('Escape');}
  await page.locator('.attention-visit-list').evaluate(element=>element.scrollTop=element.scrollHeight);await shot('attention-bottom');
  results.push({viewport:label,theme,layout,errors});
  await context.close();
 }
}
await browser.close();
await writeFile(path.join(root,'home-results.json'),JSON.stringify({sha,cssViewports:viewports,results},null,2));
console.log(JSON.stringify({root,states:results.length,failures:results.filter(item=>item.errors.length)},null,2));
if(results.some(item=>item.errors.length))process.exitCode=1;
