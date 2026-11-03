import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';

const source=process.env.VIGIL_QA_SHA || execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const root=path.resolve(process.cwd(),'..','qa','screens',source);
const base=process.env.VIGIL_UI_BASE_URL || 'http://127.0.0.1:8105/next/src/pages/clips/preview.html';
const matrix=process.env.VIGIL_QA_SMOKE ? [[1280,600]] : [[1470,870],[1512,895],[1728,1030],[1920,960],[1536,730],[1280,600],[1366,650],[1024,768],[1180,820],[2560,1000],[390,844]];
const browser=await chromium.launch({headless:true});
const report={source,base,started:new Date().toISOString(),cases:[],failures:[]};
try {
  for(const [width,height] of matrix) for(const theme of ['dark','light']) for(const route of ['clips','media']) {
    const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:1,reducedMotion:'reduce'});
    const page=await context.newPage();
    const errors=[],requests=[];
    page.on('pageerror',error=>errors.push(String(error)));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    page.on('requestfailed',request=>requests.push(request.url()));
    page.on('response',response=>{if(response.status()>=400)requests.push(`${response.status()} ${response.url()}`);});
    const folder=path.join(root,`${width}x${height}`);
    await fs.mkdir(folder,{recursive:true});
    const prefix=`${route}-${theme}`;
    let index=0;
    async function capture(name) {await page.screenshot({path:path.join(folder,`${prefix}-${String(index++).padStart(3,'0')}-${name}.png`),fullPage:width<=640});}
    async function geometry() {
      const values=await page.evaluate(()=>({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,
        clippedCards:[...document.querySelectorAll('.evidence-grid .v-clip-card')].filter(el=>el.scrollHeight>el.clientHeight+1).length,
        firstVerdictBottom:document.querySelector('.evidence-grid .v-verdict')?.getBoundingClientRect().bottom,
        firstStoryBottom:document.querySelector('.evidence-grid .v-clip-caption strong')?.getBoundingClientRect().bottom,
        pageBottom:document.querySelector('.evidence-page')?.getBoundingClientRect().bottom}));
      expect(values.width).toBe(width);expect(values.height).toBe(height);
      expect(values.scrollWidth).toBeLessThanOrEqual(width);
      if(width>640) {expect(values.scrollHeight).toBeLessThanOrEqual(height);expect(values.pageBottom).toBeLessThanOrEqual(height);}
      expect(values.clippedCards).toBe(0);
      if(width>640 && values.firstVerdictBottom!==undefined)expect(values.firstVerdictBottom).toBeLessThanOrEqual(height);
      if(width>640 && values.firstStoryBottom!==undefined)expect(values.firstStoryBottom).toBeLessThanOrEqual(height);
      return values;
    }
    try {
      await page.goto(`${base}?route=${route}&theme=${theme}`);
      await page.waitForFunction(()=>document.body.dataset.ready==='1');
      await page.evaluate(()=>document.fonts.ready);
      await expect(page.locator('.evidence-grid li')).toHaveCount(5);
      await capture('initial');
      const initial=await geometry();
      const controls=page.locator('.evidence-page button,.evidence-page input');
      for(let n=0;n<await controls.count();n++) {
        const control=controls.nth(n);
        if(!await control.isVisible())continue;
        await control.scrollIntoViewIfNeeded();await control.hover();
        await capture(`hover-${n}`);
      }
      for(const name of ['Camera','Verdict']) {
        const trigger=page.getByRole('combobox',{name,exact:true});
        await trigger.click();
        await expect(page.getByRole('listbox')).toBeVisible();
        await capture(`${name.toLowerCase()}-open`);
        const options=page.getByRole('option');
        for(let n=0;n<await options.count();n++) {
          await options.nth(n).hover();await capture(`${name.toLowerCase()}-option-${n}`);
        }
        await page.keyboard.press('Escape');
        await expect(trigger).toBeFocused();
      }
      await page.getByRole('combobox',{name:'Camera',exact:true}).click();
      await page.getByRole('option',{name:'Left passage',exact:true}).click();
      await expect(page.getByText('No matching clips',{exact:true})).toBeVisible();await capture('empty-camera');
      await page.getByRole('button',{name:'Clear filters',exact:true}).click();
      await page.getByRole('combobox',{name:'Verdict',exact:true}).click();
      await page.getByRole('option',{name:'Needs attention',exact:true}).click();
      await expect(page.locator('.evidence-grid li')).toHaveCount(1);await capture('verdict-filter');
      await page.getByRole('button',{name:'Clear filters',exact:true}).click();
      for(const name of ['People','Vehicles','Packages','All clips']) {
        await page.getByRole('tab',{name,exact:true}).click();await capture(`category-${name.replaceAll(' ','-').toLowerCase()}`);
      }
      const search=page.getByRole('searchbox',{name:'Search evidence'});
      await search.fill('unseen meteor');await expect(page.getByText('No matching clips',{exact:true})).toBeVisible();await capture('empty-search');
      await search.fill('gate');await page.getByRole('button',{name:'Apply filters',exact:true}).click();
      expect(await page.evaluate(()=>window.clipsReview.lastSearch.q)).toBe('gate');await capture('text-query');
      await page.getByRole('button',{name:'Clear filters',exact:true}).click();
      if(route==='media') {
        await page.getByRole('button',{name:'Time range',exact:true}).click();
        await expect(page.getByRole('dialog',{name:'Time range',exact:true})).toBeVisible();await capture('time-range-open');
        for(const control of await page.getByRole('dialog').locator('button,input').all()) {await control.hover();await capture('time-range-hover');}
        await page.getByLabel('From (local time)',{exact:true}).fill('2026-11-03T19:00');
        await page.getByLabel('Until (local time)',{exact:true}).fill('2026-11-03T18:00');
        await expect(page.getByRole('alert')).toContainText('end time on or after');await capture('invalid-date-range');
        await page.getByRole('button',{name:'Done',exact:true}).click();
        await expect(page.getByRole('button',{name:'Apply filters',exact:true})).toBeDisabled();
        await page.getByRole('button',{name:'Clear filters',exact:true}).click();
        await page.getByRole('button',{name:'Time range',exact:true}).click();
        await page.getByLabel('From (local time)',{exact:true}).fill('2026-11-02T17:59');
        await page.getByLabel('Until (local time)',{exact:true}).fill('2026-11-02T18:16');
        await page.getByRole('button',{name:'Done',exact:true}).click();
        await page.getByRole('button',{name:'Apply filters',exact:true}).click();
        const dates=await page.evaluate(()=>window.clipsReview.lastSearch);
        expect(dates.start.endsWith('Z')).toBe(true);expect(dates.end.endsWith('Z')).toBe(true);await capture('date-filter');
        await page.getByRole('button',{name:'Clear filters',exact:true}).click();
      }
      const cards=page.locator('.evidence-grid .v-clip-card');
      const count=await cards.count();
      for(let n=0;n<count;n++) {
        await cards.nth(n).click();
        await expect(page.getByRole('dialog',{name:'Clip evidence',exact:true})).toBeVisible();
        await expect(page.getByRole('dialog').getByText('Media unavailable',{exact:true})).toBeVisible();
        expect(await page.evaluate(()=>window.clipsReview.lastClipId)).toBeTruthy();
        await capture(`clip-${n}-evidence`);
        const dialogBody=page.locator('.v-dialog-body');
        await dialogBody.evaluate(el=>{el.scrollTop=el.scrollHeight;});await capture(`clip-${n}-evidence-bottom`);
        await page.keyboard.press('Escape');await expect(cards.nth(n)).toBeFocused();
      }
      const panel=page.getByRole('region',{name:'Clip results',exact:true});
      await panel.evaluate(el=>{el.scrollTop=0;});await capture('results-top');
      await panel.evaluate(el=>{el.scrollTop=el.scrollHeight;});await capture('results-bottom');
      await page.evaluate(()=>{document.body.setAttribute('tabindex','-1');document.body.focus();document.body.removeAttribute('tabindex');});
      await page.keyboard.press('Tab');
      const focusStates=[];
      for(let n=0;n<44;n++) {
        const focused=await page.evaluate(()=>{
          const el=document.activeElement;if(!(el instanceof HTMLElement))return null;
          const style=getComputedStyle(el);return {tag:el.tagName,outline:style.outlineStyle,width:parseFloat(style.outlineWidth),visible:el.getBoundingClientRect().width>0,owned:Boolean(el.closest('.evidence-page')),name:el.getAttribute('aria-label')||el.textContent};
        });
        if(focused?.visible && focused.tag!=='BODY')expect(focused.width).toBeGreaterThan(0);
        if(focused?.owned){focusStates.push(focused);await capture(`keyboard-${n}`);}await page.keyboard.press('Tab');
      }
      expect(focusStates.some(state=>state.tag==='INPUT')).toBe(true);
      expect(focusStates.some(state=>state.name==='Camera')).toBe(true);
      const final=await geometry();
      expect(errors).toEqual([]);expect(requests).toEqual([]);
      report.cases.push({width,height,theme,route,initial,final,images:index,focusStates,errors,requests});
    } catch(error) {
      await capture('failure').catch(()=>{});
      report.failures.push({width,height,theme,route,error:String(error),errors,requests});
    } finally {await context.close();}
  }
} finally {await browser.close();}
report.finished=new Date().toISOString();
await fs.mkdir(root,{recursive:true});
await fs.writeFile(path.join(root,'clips-results.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({source,cases:report.cases.length,failures:report.failures},null,2));
if(report.failures.length)process.exitCode=1;
