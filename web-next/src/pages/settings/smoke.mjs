import {chromium,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve('..','qa','controls-regressions');await mkdir(root,{recursive:true});
const browser=await chromium.launch();const results=[];
for(const theme of ['dark','light']){
 const page=await browser.newPage({viewport:{width:1280,height:600},reducedMotion:'reduce'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});page.on('requestfailed',r=>errors.push(r.url()));
 for(const route of ['settings','rules','benchmark']){
  await page.goto(`http://127.0.0.1:8106/next/src/pages/settings/preview.html?route=${route}&theme=${theme}`);await page.evaluate(()=>document.fonts.ready);
  await expect(page.locator('.controls-page')).toBeVisible();await page.screenshot({path:path.join(root,`${route}-${theme}.png`)});
  const dimensions=await page.evaluate(()=>({w:innerWidth,h:innerHeight,sw:document.documentElement.scrollWidth,sh:document.documentElement.scrollHeight}));
  expect(dimensions.sw).toBeLessThanOrEqual(dimensions.w);expect(dimensions.sh).toBeLessThanOrEqual(dimensions.h);
  if(route==='settings'){for(const name of ['Privacy','Household','Owner controls']){await page.getByRole('tab',{name,exact:true}).click();await page.screenshot({path:path.join(root,`${route}-${theme}-${name.replaceAll(' ','-')}.png`)});}}
  results.push({theme,route,dimensions,errors:[...errors]});
 }
 await page.close();
}
await browser.close();await writeFile(path.join(root,'results.json'),JSON.stringify(results,null,2));
if(results.some(r=>r.errors.length))throw new Error('Console or network failures');console.log(JSON.stringify(results));
