import {chromium,expect} from '../web-next/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';import path from 'node:path';
const root=path.resolve('qa/screens/7c2ea321');const base='http://127.0.0.1:8115/next/src/pages/clips/preview.html';
const matrix=[[1470,870],[1512,895],[1728,1030],[1920,960],[1536,730],[1280,600],[1366,650],[1024,768],[1180,820],[2560,1000],[390,844]];
const report={cases:[],failures:[]};const browser=await chromium.launch();
for(const [width,height] of matrix)for(const theme of ['dark','light'])for(const route of ['clips','media']){
 const ctx=await browser.newContext({viewport:{width,height},reducedMotion:'no-preference',timezoneId:'America/Los_Angeles'});const page=await ctx.newPage();page.setDefaultTimeout(6000);const rec={width,height,route,theme,errors:[],focus:[],text:[]};page.on('pageerror',e=>rec.errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')rec.errors.push(m.text());});
 const dir=path.join(root,`${width}x${height}`);await fs.mkdir(dir,{recursive:true});const snap=label=>page.screenshot({path:path.join(dir,`review-clips-${route}-${theme}-extra-${label}.png`),fullPage:width<=640});
 try{
  await page.goto(`${base}?route=${route}&theme=${theme}&empty=1`);await page.waitForFunction(()=>document.body.dataset.ready==='1');await page.evaluate(()=>document.fonts.ready);await expect(page.getByText('No clips yet',{exact:true})).toBeVisible();expect(await page.locator('.evidence-page img,.evidence-page video').count()).toBe(0);await snap('true-empty');
  await page.goto(`${base}?route=${route}&theme=${theme}`);await page.waitForFunction(()=>document.body.dataset.ready==='1');await page.evaluate(()=>document.fonts.ready);await expect(page.locator('.v-clip-card')).toHaveCount(5);await snap('normal-motion-initial');expect(await page.locator('.evidence-results').evaluate(e=>getComputedStyle(e).scrollBehavior)).toBe('smooth');
  rec.text=await page.locator('.evidence-page').evaluate(root=>{
   const rgb=v=>(v.match(/[\d.]+/g)||[]).map(Number);const blend=(fg,bg)=>fg.slice(0,3).map((v,i)=>v*(fg[3]??1)+bg[i]*(1-(fg[3]??1)));const bg=e=>e?blend(rgb(getComputedStyle(e).backgroundColor),bg(e.parentElement)):[255,255,255];const L=c=>c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
   return [...root.querySelectorAll('*')].filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())&&!e.closest('[disabled]')&&e.getBoundingClientRect().width>0).map(e=>{const b=bg(e),a=L(blend(rgb(getComputedStyle(e).color),b)),z=L(b);return {text:e.textContent,ratio:(Math.max(a,z)+.05)/(Math.min(a,z)+.05)};});
  });expect(rec.text.every(t=>t.ratio>=4.5)).toBe(true);
  await page.evaluate(()=>{document.body.tabIndex=-1;document.body.focus();document.body.removeAttribute('tabindex');});
  for(let i=0;i<32;i++){await page.keyboard.press('Tab');const f=await page.evaluate(()=>{const e=document.activeElement,s=getComputedStyle(e),r=e.getBoundingClientRect();return {tag:e.tagName,name:e.getAttribute('aria-label')||e.textContent,owned:!!e.closest('.evidence-page'),outline:s.outlineStyle,width:parseFloat(s.outlineWidth),visible:r.width>0&&r.height>0};});if(f.owned&&f.visible){rec.focus.push(f);expect(f.width).toBeGreaterThan(0);}}
  expect(rec.focus.some(f=>f.tag==='INPUT')).toBe(true);expect(rec.focus.some(f=>f.name==='Camera')).toBe(true);await snap('keyboard-traversal');
  await page.getByRole('tab',{name:'All clips',exact:true}).focus();await page.keyboard.press('ArrowRight');await expect(page.getByRole('tab',{name:'People',exact:true})).toHaveAttribute('data-state','active');await expect(page.locator('.v-clip-card')).toHaveCount(3);await snap('keyboard-tab-selection');await page.keyboard.press('Home');await expect(page.getByRole('tab',{name:'All clips',exact:true})).toHaveAttribute('data-state','active');
  await page.locator('.v-clip-card').first().focus();await page.keyboard.press('Enter');await expect(page.getByRole('dialog',{name:'Clip evidence',exact:true})).toBeVisible();await page.keyboard.press('Escape');await expect(page.locator('.v-clip-card').first()).toBeFocused();
  // Actual shell controls demonstrate a theme transition and page unmount/remount.
  if(width<=640)await page.getByRole('button',{name:'Open navigation',exact:true}).click();await page.getByRole('navigation',{name:width<=640?'Mobile navigation':'Main navigation',exact:true}).getByRole('button',{name:route==='clips'?'Media library':'Clips',exact:true}).click();await expect(page.locator('.v-clip-card')).toHaveCount(5);
  await page.getByRole('button',{name:`Use ${theme==='dark'?'light':'dark'} theme`,exact:true}).click();await snap('route-and-theme-transition');expect(rec.errors).toEqual([]);report.cases.push(rec);
 }catch(e){rec.error=String(e);report.failures.push(rec);await snap('FAILURE').catch(()=>{});console.log('FAIL',width,height,route,theme,String(e));}finally{await ctx.close();await fs.writeFile(path.join(root,'review-clips-extra-results.json'),JSON.stringify(report,null,2));}
 console.log('EXTRA',width,height,route,theme,rec.error??'PASS');
}
await browser.close();console.log('FINISHED',report.cases.length,report.failures.length);if(report.failures.length)process.exitCode=1;
