import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root=path.resolve('..');
const sha=execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const phase=process.env.VIGIL_QA_PHASE||'before';
const folder=path.join(root,'qa','screens',sha,'shell-round2',phase);
await fs.mkdir(folder,{recursive:true});
const stress=JSON.parse(await fs.readFile(path.join(root,'qa','reviews','shell-round2','stress-state.json'),'utf8'));
const dimensions=[['air13',1470,870],['pro14',1512,895],['pro16',1728,1030],['win100',1920,960],['win125',1536,730],['win150',1280,600],['laptop',1366,650],['four-three',1024,768],['tablet',1180,820],['ultrawide',2560,1000],['phone',390,844]];
const selected=process.env.VIGIL_QA_FOCUSED?dimensions.filter(([,w,h])=>w===1280&&h===600):dimensions;
const browser=await chromium.launch();
const report={phase,sha,started:new Date().toISOString(),results:[],failures:[],errors:[],requests:[]};
const base=process.env.VIGIL_UI_BASE_URL||'http://127.0.0.1:8101/next/src/shell/preview.html';
for(const [name,width,height] of selected){
  const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'});
  page.on('pageerror',e=>report.errors.push({name,error:e.message}));
  page.on('console',message=>{if(message.type()==='error')report.errors.push({name,error:message.text()});});
  page.on('response',response=>{if(response.status()>=400)report.requests.push({name,url:response.url(),status:response.status()});});
  await page.route('**/src/fixtures/state.json*',route=>route.fulfill({contentType:'text/javascript',body:`export default ${JSON.stringify(stress)};`}));
  await page.goto(base);await page.locator('[data-testid="twin-canvas"][data-webgl="ready"]').waitFor();await page.evaluate(()=>document.fonts.ready);
  const dir=path.join(folder,`${width}x${height}`);await fs.mkdir(dir,{recursive:true});
  const shot=state=>page.screenshot({path:path.join(dir,`${state}.png`)});
  const result={name,width,height,cards:[],focus:null,stacking:null};
  const bell=page.getByRole('button',{name:/^Notifications/});
  await bell.focus();await page.keyboard.press('Enter');await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');await expect(page.getByRole('dialog')).toBeVisible();await shot('notification-keyboard-dialog');await page.keyboard.press('Escape');
  try{await expect(bell).toBeFocused();result.focus='bell';}catch{result.focus=await page.evaluate(()=>document.activeElement?.tagName);report.failures.push(`${name}: notification visit focus returned to ${result.focus}`);}
  await shot('notification-focus-return');
  await bell.click();await page.getByRole('menuitem').first().click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('button',{name:/^Close /}).click();await expect(bell).toBeFocused();
  await bell.click();await page.locator('.v-notification-scroll').evaluate(el=>el.scrollTop=el.scrollHeight);await shot('stress-notifications-footer');
  const z=await page.evaluate(()=>({menu:Number(getComputedStyle(document.querySelector('.v-notifications')).zIndex),chat:Number(getComputedStyle(document.querySelector('.v-preview-message')).zIndex)}));result.stacking=z;
  if(z.menu<=z.chat)report.failures.push(`${name}: notification layer ${z.menu} is below chat ${z.chat}`);
  await page.getByRole('menuitem',{name:'Open Attention',exact:true}).click();await expect(page.getByRole('main')).toHaveAttribute('aria-label','Attention');
  {
    for(const theme of ['dark','light']){
      if(theme==='light')await page.getByRole('button',{name:'Use light theme'}).click();
      for(const route of ['Clips','Media library']){
        if(width>640)await page.locator('.v-sidebar').getByRole('button',{name:route,exact:true}).click();
        else{await page.getByRole('button',{name:'Open navigation'}).click();await page.locator('.v-navigation-mobile').getByRole('button',{name:route,exact:true}).click();await expect(page.getByRole('dialog',{name:'Navigation'})).toHaveCount(0);}
        const grid=page.locator('.v-preview-clips');
        const cards=await page.locator('.v-clip-card').evaluateAll(elements=>elements.map(el=>{const r=el.getBoundingClientRect(),caption=el.querySelector('.v-clip-caption').getBoundingClientRect();return {id:el.textContent,client:el.clientHeight,scroll:el.scrollHeight,cardBottom:r.bottom,captionBottom:caption.bottom};}));
        result.cards.push({theme,route,cards});
        for(const card of cards)if(card.scroll>card.client+1||card.captionBottom>card.cardBottom+1)report.failures.push(`${name}/${theme}/${route}: card caption clips ${card.scroll-card.client}px`);
        await grid.evaluate(el=>el.scrollTop=0);await page.evaluate(()=>window.scrollTo(0,0));await shot(`${theme}-${route==='Clips'?'clips':'media'}-top`);
        await grid.evaluate(el=>el.scrollTop=el.scrollHeight);if(width<=640)await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));await shot(`${theme}-${route==='Clips'?'clips':'media'}-bottom`);
        await page.locator('.v-clip-card').last().click();await expect(page.getByRole('dialog')).toBeVisible();await page.keyboard.press('Escape');
      }
    }
  }
  const bounds=await page.evaluate(()=>({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight}));
  expect(bounds.scrollWidth).toBe(width);if(width>640)expect(bounds.scrollHeight).toBe(height);result.bounds=bounds;
  report.results.push(result);await page.close();
}
report.finished=new Date().toISOString();await fs.writeFile(path.join(folder,'report.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify({folder,results:report.results.length,failures:report.failures,errors:report.errors,requests:report.requests}));if(report.failures.length||report.errors.length||report.requests.length)process.exitCode=1;
