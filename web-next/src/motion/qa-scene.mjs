import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const sha=process.env.MOTION_QA_SHA||execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const sizes=[[1470,870],[1512,895],[1728,1030],[1920,960],[1536,730],[1280,600],[1366,650],[1024,768],[1180,820],[2560,1000],[390,844]];
const root=path.resolve('../qa/screens',sha),report={sha,cases:[],failures:[]};await fs.mkdir(root,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl','--ignore-gpu-blocklist']});
try {
for(const [width,height] of sizes)for(const theme of ['dark','light'])for(const preference of ['no-preference','reduce']) {
 const page=await browser.newPage({viewport:{width,height},reducedMotion:preference}),name=`${width}x${height}-${theme}-${preference}`,errors=[];
 page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});page.on('requestfailed',r=>errors.push(r.url()));
 const output=path.join(root,`${width}x${height}`);await fs.mkdir(output,{recursive:true});
 const shot=label=>page.screenshot({path:path.join(output,`motion-scene-${theme}-${preference}-${label}.png`)});
 const state=()=>page.evaluate(async()=>{const fiber=await import('/next/node_modules/.vite/deps/@react-three_fiber.js');const s=[...fiber._roots.values()][0].store.getState();return {p:s.camera.position.toArray(),t:s.controls.target.toArray(),distance:s.camera.position.distanceTo(s.controls.target),damping:s.controls.enableDamping,clearance:parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--v-twin-camera-clearance')),min:s.controls.minDistance,max:s.controls.maxDistance};});
 try {
  await page.goto(`http://127.0.0.1:8107/next/src/motion/preview.html?theme=${theme}`);await page.locator('canvas').waitFor();await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(700);
  const scene=page.getByRole('region',{name:'Property camera view',exact:true}),presets=scene.getByRole('tablist',{name:'House view presets'}),samples=[];
  for(const label of ['Front','Left passage','Backyard','Top-down']){
   await presets.getByRole('tab',{name:label,exact:true}).click();await page.waitForTimeout(700);
   const actual=await state();expect(actual.p[1]).toBeGreaterThanOrEqual(actual.clearance-1e-7);expect(actual.distance).toBeGreaterThanOrEqual(actual.min-1e-7);expect(actual.distance).toBeLessThanOrEqual(actual.max+1e-7);expect(actual.damping).toBe(preference!=='reduce');samples.push({label,...actual});await shot(label.replaceAll(' ','-'));
  }
  const coverage=scene.getByRole('button',{name:'Toggle camera coverage',exact:true}),pressed=await coverage.getAttribute('aria-pressed');await coverage.click();expect(await coverage.getAttribute('aria-pressed')).not.toBe(pressed);await shot('coverage-hidden');await coverage.click();await shot('coverage-shown');
  await scene.getByRole('button',{name:'Zoom in',exact:true}).click();await page.waitForTimeout(120);await shot('zoom-in');
  await scene.getByRole('button',{name:'Zoom out',exact:true}).click();await page.waitForTimeout(120);await shot('zoom-out');
  await scene.getByRole('button',{name:'Reset view',exact:true}).click();await page.waitForTimeout(700);
  const menu=scene.getByRole('button',{name:'Select camera',exact:true});
  if(await menu.isVisible()) {
   await menu.click();await shot('camera-menu');const labels=await page.getByRole('menu').getByRole('menuitem').allTextContents();await page.keyboard.press('Escape');
   for(let index=0;index<labels.length;index++){await menu.click();await page.getByRole('menu').getByRole('menuitem').nth(index).hover();await shot(`camera-menu-hover-${index}`);await page.getByRole('menu').getByRole('menuitem').nth(index).click();await page.waitForTimeout(100);await shot(`camera-selected-${index}`);}
  } else {
   const cameras=scene.locator('.twin-camera-list').getByRole('button');
   for(let index=0;index<await cameras.count();index++){await cameras.nth(index).hover();await shot(`camera-hover-${index}`);await cameras.nth(index).click();await page.waitForTimeout(100);await shot(`camera-selected-${index}`);}
  }
  const final=await state();expect(final.p[1]).toBeGreaterThanOrEqual(final.clearance-1e-7);expect(errors).toEqual([]);report.cases.push({name,samples,final,errors});console.log(`PASS scene ${name}`);
 }catch(error){report.failures.push({name,error:String(error),errors});await shot('FAILURE');console.log(`FAIL scene ${name}: ${error}`);}
 finally{await page.close();await fs.writeFile(path.join(root,'motion-scene-results.json'),JSON.stringify(report,null,2));}
}
}finally{await browser.close();}
if(report.failures.length)process.exitCode=1;
