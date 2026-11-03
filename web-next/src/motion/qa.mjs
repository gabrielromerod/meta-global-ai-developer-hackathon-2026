import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';

const viewports=[[1470,870],[1512,895],[1728,1030],[1920,960],[1536,730],[1280,600],[1366,650],[1024,768],[1180,820],[2560,1000],[390,844]];
const selected=process.env.MOTION_QA_VIEWPORT;
const subset=selected?viewports.filter(([w,h])=>`${w}x${h}`===selected):viewports;
const shard=process.env.MOTION_QA_SHARD?.split('/').map(Number);
if(shard&&(!Number.isInteger(shard[0])||!Number.isInteger(shard[1])||shard[0]<0||shard[1]<1||shard[0]>=shard[1]))throw new Error('MOTION_QA_SHARD must be zero-based part/count');
const cases=shard?subset.filter((_,index)=>index%shard[1]===shard[0]):subset;
const sha=process.env.MOTION_QA_SHA||execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const base=process.env.VIGIL_UI_BASE_URL||'http://127.0.0.1:8107';
const output=path.resolve('../qa/screens',sha);
const reportName=shard?`motion-results-shard-${shard[0]}.json`:'motion-results.json';
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist']});
const report={sha,started:new Date().toISOString(),cases:[],failures:[]};
for(const [width,height] of cases)for(const theme of ['dark','light'])for(const preference of ['no-preference','reduce']) {
  const viewport=`${width}x${height}`,name=`${viewport}-${theme}-${preference}`;
  const dir=path.join(output,viewport);await fs.mkdir(dir,{recursive:true});
  const context=await browser.newContext({viewport:{width,height},reducedMotion:preference});
  const page=await context.newPage();
  const errors=[],failed=[];page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});page.on('requestfailed',r=>failed.push(`${r.method()} ${r.url()} ${r.failure()?.errorText}`));
  let serial=0;
  const shot=async(label)=>{const filename=`motion-${theme}-${preference}-${String(serial++).padStart(3,'0')}-${label.replace(/[^a-z0-9-]+/gi,'-').slice(0,70)}.png`;await page.screenshot({path:path.join(dir,filename)});return filename;};
  const dimensions=async()=>{
    const actual=await page.evaluate(()=>({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight}));
    expect(actual.width).toBe(width);expect(actual.height).toBe(height);expect(actual.scrollWidth).toBeLessThanOrEqual(width);
    if(width>640)expect(actual.scrollHeight).toBe(height);
    return actual;
  };
  const navigate=async(route,label)=>{
    if(width<=640){await page.getByRole('button',{name:'Open navigation',exact:true}).click();await shot('mobile-navigation');await page.getByRole('navigation',{name:'Mobile navigation'}).getByRole('button',{name:label,exact:true}).click();}
    else await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:label,exact:true}).click();
    await expect(page.getByRole('region',{name:`${route} view`,exact:true})).toBeVisible();
    await page.waitForTimeout(520);
    if(width>640)await expect(page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:label,exact:true})).toBeFocused();
    await dimensions();await shot(`route-${route}`);
  };
  const hoverAll=async(scope,label)=>{
    const controls=scope.locator('button,input,textarea,select,[role="tab"],[tabindex="0"]');
    const count=await controls.count();
    for(let index=0;index<count;index++) {
      const control=controls.nth(index);
      if(!await control.isVisible())continue;
      await control.scrollIntoViewIfNeeded();
      await control.hover();
      await shot(`${label}-hover-${index}`);
    }
  };
  try {
    await page.goto(`${base}/next/src/motion/preview.html?theme=${theme}`);
    await page.waitForFunction(()=>document.body.dataset.ready==='1');await page.evaluate(()=>document.fonts.ready);
    await page.waitForTimeout(520);await dimensions();await shot('home');
    await hoverAll(page.getByRole('main'),'home');
    // Every supplied Home view is real fixture-driven input, not a fabricated camera.
    const views=page.getByRole('tablist',{name:'House views'}).getByRole('tab');
    for(let index=0;index<await views.count();index++){
      await views.nth(index).click();await page.waitForTimeout(80);await shot(`house-view-${index}`);await dimensions();
    }
    // Open a cited visit; panel entrance and inline presence preserve the Radix owner.
    const comparison=page.getByRole('button',{name:/Open household .* visit/}).first();
    await comparison.scrollIntoViewIfNeeded();await comparison.click();
    const dialog=page.getByRole('dialog',{name:'Visit evidence'});await expect(dialog).toBeVisible();await page.waitForTimeout(240);await shot('visit-panel');
    await dialog.getByRole('button',{name:'Recorded observations',exact:true}).click();await page.waitForTimeout(240);await shot('observations-open');
    await hoverAll(dialog,'visit');
    await dialog.getByRole('button',{name:'Recorded observations',exact:true}).click();
    await expect(dialog.getByRole('region',{name:'Recorded observations',exact:true})).toHaveCount(0);
    await shot('observations-closed');
    await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(comparison).toBeFocused();
    await navigate('attention','Attention');await hoverAll(page.getByRole('main'),'attention');
    await navigate('messages','Messages');
    const composer=page.getByRole('textbox',{name:'Message',exact:true});
    await composer.fill('A local draft stays in this browser.');
    await page.emulateMedia({reducedMotion:preference==='reduce'?'no-preference':'reduce'});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await expect(composer).toHaveValue('A local draft stays in this browser.');await expect(composer).toBeFocused();await shot('live-preference-preserved-draft');
    await page.emulateMedia({reducedMotion:preference});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await expect(composer).toHaveValue('A local draft stays in this browser.');
    await page.getByRole('button',{name:'Open floating Messages',exact:true}).click();
    const popup=page.getByRole('dialog',{name:'Messages',exact:true});await expect(popup).toBeVisible();
    await expect(popup.getByRole('textbox',{name:'Message',exact:true})).toHaveValue('A local draft stays in this browser.');
    await page.waitForTimeout(240);await shot('popup-shared-draft');
    await hoverAll(popup,'popup');
    await popup.getByRole('button',{name:'Share options',exact:true}).click();await shot('share-menu');
    await hoverAll(page.getByRole('menu'),'share-menu');await page.keyboard.press('Escape');
    await popup.getByRole('button',{name:'Send message',exact:true}).click();await expect(popup.getByText('A local draft stays in this browser.',{exact:true})).toBeVisible();await shot('actual-local-send');
    await popup.getByRole('tab',{name:'Ask your home',exact:true}).click();await expect(popup.getByRole('textbox',{name:'Message',exact:true})).toBeDisabled();await shot('ask-unavailable');
    await popup.getByRole('tab',{name:'Household',exact:true}).click();
    await popup.getByRole('button',{name:'Close messages',exact:true}).click();await expect(popup).toHaveCount(0);await expect(page.getByRole('button',{name:'Open floating Messages',exact:true})).toBeFocused();
    // Native keyboard traversal exercises focus without moving it on animation completion.
    if(width<=640)await page.getByRole('button',{name:'Open navigation',exact:true}).focus();
    else await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Home',exact:true}).focus();
    await page.keyboard.press('Tab');await shot('keyboard-focus');
    const focusVisible=await page.evaluate(()=>{const el=document.activeElement;return el instanceof HTMLElement&&el!==document.body&&getComputedStyle(el).outlineStyle!=='none';});
    expect(focusVisible).toBe(true);
    await navigate('home','Home');
    const button=page.getByRole('button',{name:/Notifications/}).first();await button.click();await shot('notifications');await hoverAll(page.getByRole('menu'),'notifications');await page.keyboard.press('Escape');
    // Read actual styles after an OS preference change, including nested theme scopes.
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const reduced=await page.locator('.v-motion-view').evaluate(el=>({transform:getComputedStyle(el).transform,opacity:Number(getComputedStyle(el).opacity),tokens:[document.documentElement,document.querySelector('.v-app-shell')].map(node=>getComputedStyle(node).getPropertyValue('--v-motion-view').trim())}));
    expect(reduced.transform).toBe('none');expect(reduced.opacity).toBe(1);expect(reduced.tokens).toEqual(['0ms','0ms']);
    await shot('reduced-actual-style');await dimensions();
    expect(errors).toEqual([]);expect(failed).toEqual([]);
    report.cases.push({name,viewport:{width,height},theme,preference,screenshots:serial,errors,failed,dimensions:await dimensions(),reduced});
    console.log(`PASS ${name}: ${serial} states`);
  } catch(error) {
    const failure={name,error:String(error),errors,failed,screenshots:serial};report.failures.push(failure);await shot('FAILURE').catch(()=>{});console.log(`FAIL ${name}: ${error}`);
  } finally {await context.close();await fs.writeFile(path.join(output,reportName),JSON.stringify(report,null,2));}
}
report.finished=new Date().toISOString();await fs.writeFile(path.join(output,reportName),JSON.stringify(report,null,2));await browser.close();if(report.failures.length)process.exitCode=1;
