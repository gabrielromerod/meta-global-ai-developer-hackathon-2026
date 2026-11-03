import {chromium,expect} from 'file:///C:/Users/lords/.codex/worktrees/rr-motion/meta-global-ai-developer-hackathon-2026/web-next/node_modules/@playwright/test/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const sha=process.env.MOTION_QA_SHA||execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const output=path.resolve('qa/screens',sha,'1280x600');await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:600},reducedMotion:'no-preference'});
const errors=[],failures=[],results=[];page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});page.on('requestfailed',r=>failures.push(r.url()));
try {
await page.addInitScript(()=>{
  const original=window.matchMedia.bind(window),nativeListeners=new Set();
  window.motionNativePreferenceListeners=nativeListeners;
  window.matchMedia=query=>{
    const media=original(query);
    if(query==='(prefers-reduced-motion: reduce)'){
      const add=media.addEventListener.bind(media),remove=media.removeEventListener.bind(media);
      media.addEventListener=(type,listener,...rest)=>{if(type==='change')nativeListeners.add(listener);return add(type,listener,...rest);};
      media.removeEventListener=(type,listener,...rest)=>{if(type==='change')nativeListeners.delete(listener);return remove(type,listener,...rest);};
    }
    return media;
  };
});
await page.goto('http://127.0.0.1:8117/next/src/motion/preview.html');await page.waitForFunction(()=>document.body.dataset.ready==='1');await page.evaluate(()=>document.fonts.ready);
await page.waitForTimeout(700);
await page.getByRole('tablist',{name:'House view presets',exact:true}).getByRole('tab',{name:'Backyard',exact:true}).click();await page.waitForTimeout(600);
// A wall-clock wait is not proof that the final WebGL pose has rendered under load.
await page.evaluate(async()=>{
  const fiber=await import('/next/node_modules/.vite/deps/@react-three_fiber.js');
  await new Promise((resolve,reject)=>{
    let previous=null,stable=0;
    const timeout=setTimeout(()=>{stop();reject(new Error('Camera did not reach five identical rendered poses'));},5000);
    const stop=fiber.addAfterEffect(()=>{
      const state=[...fiber._roots.values()][0].store.getState(),values=[...state.camera.position.toArray(),...state.controls.target.toArray()];
      stable=previous&&values.every((value,index)=>Math.abs(value-previous[index])<1e-10)?stable+1:0;previous=values;
      if(stable>=5){stop();clearTimeout(timeout);resolve();}
    });
  });
});
const before=await page.evaluate(async()=>{
  const fiber=await import('/next/node_modules/.vite/deps/@react-three_fiber.js');
  const state=[...fiber._roots.values()][0].store.getState();
  window.motionCanvasBefore=document.querySelector('canvas');
  return {position:state.camera.position.toArray(),target:state.controls.target.toArray(),nativeListeners:window.motionNativePreferenceListeners.size};
});
for(const preference of ['reduce','no-preference','reduce','no-preference']){
  await page.emulateMedia({reducedMotion:preference});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const actual=await page.evaluate(async()=>{
    const fiber=await import('/next/node_modules/.vite/deps/@react-three_fiber.js');const state=[...fiber._roots.values()][0].store.getState();
    return {sameCanvas:window.motionCanvasBefore===document.querySelector('canvas'),position:state.camera.position.toArray(),target:state.controls.target.toArray(),policy:window.vigilMotionReview.policy,nativeListeners:window.motionNativePreferenceListeners.size};
  });
  results.push({preference,...actual});
  expect(actual.sameCanvas).toBe(true);expect(actual.policy.reduced).toBe(preference==='reduce');expect(actual.nativeListeners).toBe(1);
  for(let axis=0;axis<3;axis++){expect(Math.abs(actual.position[axis]-before.position[axis])).toBeLessThan(1e-7);expect(Math.abs(actual.target[axis]-before.target[axis])).toBeLessThan(1e-7);}
  await page.screenshot({path:path.join(output,`review-motion-r2-adaptive-canvas-${results.length}-${preference}.png`)});
}
await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Messages',exact:true}).click();await page.waitForTimeout(520);
const field=page.getByRole('textbox',{name:'Message',exact:true});await field.fill('The same draft and input node survive preference changes.');
await field.evaluate(el=>window.motionFieldBefore=el);
for(const preference of ['reduce','no-preference']){
  await page.emulateMedia({reducedMotion:preference});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const actual=await field.evaluate(el=>({sameField:el===window.motionFieldBefore,focused:document.activeElement===el,value:el.value,nativeListeners:window.motionNativePreferenceListeners.size}));
  expect(actual.sameField).toBe(true);expect(actual.focused).toBe(true);expect(actual.value).toBe('The same draft and input node survive preference changes.');expect(actual.nativeListeners).toBe(1);
  results.push({preference,...actual});await page.screenshot({path:path.join(output,`review-motion-r2-adaptive-draft-${preference}.png`)});
}
// Route churn must not accumulate native preference subscriptions or duplicate pages.
for(let index=0;index<20;index++){
  await page.evaluate(route=>window.vigilMotionReview.navigate(route),index%2?'messages':'attention');
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));
  expect(await page.locator('.v-motion-view').count()).toBe(1);expect(await page.evaluate(()=>window.motionNativePreferenceListeners.size)).toBe(1);
}
await page.waitForTimeout(520);await page.screenshot({path:path.join(output,'review-motion-r2-adaptive-route-churn.png')});
// Stress an in-flight route transition, then request reduced motion immediately.
await page.emulateMedia({reducedMotion:'no-preference'});
const moving=await page.evaluate(()=>{
  document.documentElement.style.setProperty('--v-motion-view','1920ms');
  window.vigilMotionReview.navigate('attention');
  return new Promise(resolve=>{
    let frames=0;
    const inspect=()=>{
      const node=document.querySelector('.v-motion-view'),style=getComputedStyle(node),matrix=new DOMMatrixReadOnly(style.transform);
      if(matrix.m42>1||frames++>30)resolve({y:matrix.m42,opacity:Number(style.opacity),frames});else requestAnimationFrame(inspect);
    };requestAnimationFrame(inspect);
  });
});
await page.emulateMedia({reducedMotion:'reduce'});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
const stopped=await page.locator('.v-motion-view').evaluate(el=>({transform:getComputedStyle(el).transform,opacity:Number(getComputedStyle(el).opacity)}));
expect(moving.y).toBeGreaterThan(1);expect(stopped.transform).toBe('none');expect(stopped.opacity).toBe(1);
await page.evaluate(()=>document.documentElement.style.removeProperty('--v-motion-view'));
await page.screenshot({path:path.join(output,'review-motion-r2-adaptive-in-flight-reduced.png')});
expect(errors).toEqual([]);expect(failures).toEqual([]);
const report={sha,before,results,churn:20,inFlight:{moving,stopped,stressDuration:'QA-only 1920ms override; source token file unchanged'},errors,failedRequests:failures};await fs.writeFile(path.resolve(output,'../motion-adaptive-results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({checks:results.length,churn:20,inFlight:report.inFlight,errors,failedRequests:failures}));
} catch(error) {
  await fs.writeFile(path.resolve(output,'../motion-adaptive-failure.json'),JSON.stringify({sha,results,error:String(error),errors,failedRequests:failures},null,2));throw error;
} finally {await browser.close();}

