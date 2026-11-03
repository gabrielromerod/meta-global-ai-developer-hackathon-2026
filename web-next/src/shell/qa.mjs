import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root=path.resolve('..');
const sha=execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const dimensions=[['air13',1470,870],['pro14',1512,895],['pro16',1728,1030],['win100',1920,960],['win125',1536,730],['win150',1280,600],['laptop',1366,650],['four-three',1024,768],['tablet',1180,820],['ultrawide',2560,1000],['phone',390,844]];
const browser=await chromium.launch({headless:true});
const report={sha,started:new Date().toISOString(),viewports:[],errors:[],failedRequests:[]};
const base=process.env.VIGIL_UI_BASE_URL||'http://127.0.0.1:8101/next/src/shell/preview.html';
for(const [name,width,height] of dimensions){
  const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'});
  page.on('pageerror',error=>report.errors.push({name,message:error.message}));
  page.on('requestfailed',request=>report.failedRequests.push({name,url:request.url(),failure:request.failure()}));
  page.on('response',response=>{if(response.status()>=400)report.failedRequests.push({name,url:response.url(),status:response.status()});});
  const dir=path.join(root,'qa','screens',sha,`${width}x${height}`);
  await fs.mkdir(dir,{recursive:true});
  const waitScene=async()=>{const canvas=page.locator('[data-testid="twin-canvas"]');if(await canvas.count()){await expect(canvas).toHaveAttribute('data-webgl','ready');const box=await canvas.boundingBox();expect(box.width).toBeGreaterThan(100);expect(box.height).toBeGreaterThan(100);await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));}};
  const shot=async state=>{await waitScene();await page.screenshot({path:path.join(dir,`shell-${state}.png`)});};
  await page.goto(base);await page.locator('.v-app-shell').waitFor();await page.evaluate(()=>document.fonts.ready);
  const layout=await page.evaluate(()=>({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,theme:document.documentElement.dataset.theme}));
  expect(layout.scrollWidth).toBe(width);if(width>640)expect(layout.scrollHeight).toBe(height);
  await shot('dark-home');
  await page.getByRole('button',{name:'Use light theme'}).hover();await shot('theme-hover');
  await page.getByRole('button',{name:'Use light theme'}).click();await shot('light-home');
  await page.getByRole('button',{name:/^Notifications/}).click();await shot('light-notifications');await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Use dark theme'}).click();
  const nav=page.locator('.v-sidebar .v-nav-item');
  if(width>640){for(let i=0;i<await nav.count();i++){await nav.nth(i).hover();await shot(`nav-hover-${i}`);await nav.nth(i).click();await shot(`route-${i}`);}await nav.first().click();}
  else{await page.getByRole('button',{name:'Open navigation'}).click();await shot('mobile-navigation');await expect(page.getByRole('dialog',{name:'Navigation'})).toBeVisible();await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:'Open navigation'})).toBeFocused();}
  const tabs=page.getByRole('tablist',{name:'House views',exact:true}).getByRole('tab');for(let i=0;i<await tabs.count();i++){await tabs.nth(i).hover();await tabs.nth(i).click();await shot(`view-${i}`);}await tabs.first().click();
  const bell=page.getByRole('button',{name:/^Notifications/});await bell.hover();await shot('bell-hover');await bell.click();await shot('notifications-top');
  await page.locator('.v-notification-scroll').evaluate(el=>{el.scrollTop=el.scrollHeight});await shot('notifications-bottom');await page.keyboard.press('Escape');await expect(bell).toBeFocused();
  await bell.click();await page.getByRole('menuitem').first().click();await expect(page.getByRole('dialog')).toBeVisible();await shot('notification-visit');await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Messages',exact:true}).last().click();await shot('messages-dialog');await page.keyboard.press('Escape');
  await page.keyboard.press('Tab');await shot('keyboard-focus');
  const scrollables=await page.locator('.v-sidebar,.home-attention-list').all();for(let i=0;i<scrollables.length;i++){await scrollables[i].evaluate(el=>{el.scrollTop=el.scrollHeight});await shot(`panel-bottom-${i}`);await scrollables[i].evaluate(el=>{el.scrollTop=0});}
  if(width<=640){await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));await shot('phone-bottom');}
  report.viewports.push({name,...layout,states:'dark/light, navigation hover/click, configured tabs, notifications, dialogs, keyboard focus, panel scroll'});
  await page.close();
}
const fontDir=path.join(root,'qa','fonts');await fs.mkdir(fontDir,{recursive:true});
for(const font of ['inter','manrope','dm-sans']){const page=await browser.newPage({viewport:{width:1470,height:870}});await page.goto(`${base}?font=${font}`);await page.locator('.v-app-shell').waitFor();await page.waitForFunction(value=>document.documentElement.dataset.font===value,font);await page.locator('[data-testid="twin-canvas"][data-webgl="ready"]').waitFor();await page.evaluate(()=>document.fonts.ready);await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));const family=await page.locator('.v-app-shell').evaluate(el=>getComputedStyle(el).fontFamily);expect(family.toLowerCase().replaceAll(' ','-')).toContain(font);await page.screenshot({path:path.join(fontDir,`${font}-home.png`)});await page.close();}
report.finished=new Date().toISOString();await fs.writeFile(path.join(root,'qa','screens',sha,'shell-report.json'),JSON.stringify(report,null,2));await browser.close();
console.log(JSON.stringify(report));if(report.errors.length||report.failedRequests.length)process.exitCode=1;
