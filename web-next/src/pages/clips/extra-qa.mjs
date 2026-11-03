import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const base=process.env.VIGIL_UI_BASE_URL || 'http://127.0.0.1:8105/next/src/pages/clips/preview.html';
const root=path.resolve('..','qa','screens',process.env.VIGIL_QA_SHA || 'c820bb4','additional');
await fs.mkdir(root,{recursive:true});
const browser=await chromium.launch({headless:true});
const report=[];
try {
  for(const [width,height] of [[1280,600],[1024,768],[390,844]])for(const theme of ['dark','light'])for(const route of ['clips','media']) {
    const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:1,reducedMotion:'no-preference'});
    const page=await context.newPage();const errors=[];
    page.on('pageerror',error=>errors.push(String(error)));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    await page.goto(`${base}?route=${route}&theme=${theme}&empty=1`);
    await page.waitForFunction(()=>document.body.dataset.ready==='1');await page.evaluate(()=>document.fonts.ready);
    await expect(page.getByText('No clips yet',{exact:true})).toBeVisible();
    expect(await page.locator('.evidence-results').evaluate(el=>getComputedStyle(el).scrollBehavior)).toBe('smooth');
    await page.screenshot({path:path.join(root,`${width}x${height}-${route}-${theme}-true-empty.png`),fullPage:width<=640});
    if(route==='media') {
      const trigger=page.getByRole('button',{name:'Time range',exact:true});
      await trigger.click();await expect(page.getByRole('dialog',{name:'Time range',exact:true})).toBeVisible();
      await page.keyboard.press('Escape');await expect(trigger).toBeFocused();
    }
    await page.goto(`${base}?route=${route}&theme=${theme}`);
    await page.waitForFunction(()=>document.body.dataset.ready==='1');
    const trigger=page.getByRole('combobox',{name:'Camera',exact:true});await trigger.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('option',{name:'All cameras',exact:true})).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(page.getByRole('option',{name:'Front left Duo',exact:true})).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.getByText('No matching clips',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Clear filters',exact:true}).click();
    await page.getByRole('tab',{name:'All clips',exact:true}).focus();await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('tab',{name:'People',exact:true})).toHaveAttribute('data-state','active');
    await expect(page.locator('.evidence-grid li')).toHaveCount(3);
    const contrast=await page.evaluate(()=>{
      const rgb=value=>(value.match(/[\d.]+/g)||[]).map(Number);
      const luminance=channels=>channels.slice(0,3).map(channel=>{const x=channel/255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;}).reduce((sum,x,i)=>sum+x*[.2126,.7152,.0722][i],0);
      return [...document.querySelectorAll('.evidence-page-heading h2,.evidence-field label,.evidence-control,.evidence-results-heading,.evidence-camera-name,.v-clip-caption strong,.v-clip-caption>span,.v-verdict')].filter(el=>el.getBoundingClientRect().width>0&&!el.closest('[disabled]')).map(el=>{
        let ancestor=el,bg;
        while(ancestor){const candidate=rgb(getComputedStyle(ancestor).backgroundColor);if(candidate.length===3||candidate[3]>0){bg=candidate;break;}ancestor=ancestor.parentElement;}
        const foreground=luminance(rgb(getComputedStyle(el).color)),background=luminance(bg||rgb(getComputedStyle(document.body).backgroundColor));
        return {text:el.textContent?.slice(0,80),ratio:(Math.max(foreground,background)+.05)/(Math.min(foreground,background)+.05)};
      });
    });
    expect(contrast.every(item=>item.ratio>=4.5)).toBe(true);
    await page.screenshot({path:path.join(root,`${width}x${height}-${route}-${theme}-keyboard-filters.png`),fullPage:width<=640});
    expect(errors).toEqual([]);report.push({width,height,theme,route,errors,contrast});await context.close();
  }
}finally{await browser.close();}
await fs.writeFile(path.join(root,'extra-results.json'),JSON.stringify(report,null,2));
console.log(`${report.length} normal-motion/empty/keyboard cases passed`);
