import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const sha=process.env.MOTION_QA_SHA||execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const sizes=[[1470,870],[1512,895],[1728,1030],[1920,960],[1536,730],[1280,600],[1366,650],[1024,768],[1180,820],[2560,1000],[390,844]];
const output=path.resolve('../qa/screens',sha),report={sha,started:new Date().toISOString(),cases:[],failures:[]};await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist']});
try {
 for(const [width,height] of sizes)for(const theme of ['dark','light']){
  const page=await browser.newPage({viewport:{width,height},reducedMotion:'no-preference'}),errors=[],failedRequests=[],name=`${width}x${height}-${theme}`;
  page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});page.on('requestfailed',r=>failedRequests.push(r.url()));
  const folder=path.join(output,`${width}x${height}`);await fs.mkdir(folder,{recursive:true});
  try {
   await page.goto(`http://127.0.0.1:8107/next/src/motion/preview.html?theme=${theme}`);await page.waitForFunction(()=>document.body.dataset.ready==='1');await page.evaluate(()=>document.fonts.ready);
   // Preview readiness precedes the first asynchronous WebGL draw; capture rendered geometry.
   await page.waitForFunction(async()=>{const fiber=await import('/next/node_modules/.vite/deps/@react-three_fiber.js');return [...fiber._roots.values()].some(root=>root.store.getState().gl.info.render.calls>0);});
   await page.locator('.twin-canvas button').first().waitFor({state:'attached'});
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   await page.evaluate(()=>window.preferenceCanvas=document.querySelector('canvas'));
   const states=[];
   for(const preference of ['no-preference','reduce','no-preference']){
    await page.emulateMedia({reducedMotion:preference});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const actual=await page.evaluate(()=>({policy:window.vigilMotionReview.policy,sameCanvas:window.preferenceCanvas===document.querySelector('canvas'),views:document.querySelectorAll('.v-motion-view').length,transform:getComputedStyle(document.querySelector('.v-motion-view')).transform,width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight}));
    expect(actual.policy.reduced).toBe(preference==='reduce');expect(actual.sameCanvas).toBe(true);expect(actual.views).toBe(1);
    if(preference==='reduce'){expect(actual.policy.duration).toBe(0);expect(actual.policy.viewDuration).toBe(0);expect(actual.policy.offset).toBe(0);expect(actual.transform).toBe('none');}
    else expect(actual.policy.viewDuration).toBeGreaterThan(0);
    expect(actual.scrollWidth).toBeLessThanOrEqual(width);if(width>640)expect(actual.scrollHeight).toBeLessThanOrEqual(height);
    states.push({preference,...actual});await page.screenshot({path:path.join(folder,`motion-r2-preference-${theme}-${states.length}-${preference}.png`)});
   }
   expect(errors).toEqual([]);expect(failedRequests).toEqual([]);report.cases.push({name,states,errors,failedRequests});
   console.log(`PASS preference ${name}`);
  } catch(error){report.failures.push({name,error:String(error),errors,failedRequests});console.log(`FAIL preference ${name}: ${error}`);}
  finally{await page.close();}
 }
}finally{report.finished=new Date().toISOString();await fs.writeFile(path.join(output,'motion-r2-preference-results.json'),JSON.stringify(report,null,2));await browser.close();}
if(report.failures.length)process.exitCode=1;
