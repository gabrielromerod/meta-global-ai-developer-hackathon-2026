import {chromium} from '@playwright/test';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';

// The owner's numeric CSS viewports; physical hardware/browser chrome is not simulated.
const viewports=[['mac-air',1470,870],['mac-pro-14',1512,895],['mac-pro-16',1728,1030],['windows-100',1920,960],['windows-125',1536,730],['windows-150',1280,600],['laptop',1366,650],['four-three',1024,768],['tablet',1180,820],['ultrawide',2560,1000],['phone',390,844]];
const sha=process.env.QA_SHA||execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const root=path.resolve('..','qa','screens',sha);
const browser=await chromium.launch({headless:true});
const report=[];
let failures=[];
for(const [name,width,height] of viewports){
  for(const theme of ['dark','light']){
    const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
    const page=await context.newPage();
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    page.on('requestfailed',request=>errors.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`));
    const folder=path.join(root,`${name}-${width}x${height}`);
    await mkdir(folder,{recursive:true});
    const shot=async state=>{
      const filename=`chat-${theme}-${state}.png`;
      await page.screenshot({path:path.join(folder,filename)});
      const overflow=await page.evaluate(()=>({width:document.documentElement.scrollWidth>innerWidth,height:document.documentElement.scrollHeight>innerHeight}));
      if(overflow.width||overflow.height)failures.push(`${name}/${theme}/${state}: document overflow ${JSON.stringify(overflow)}`);
    };
    await page.goto('http://127.0.0.1:8104/next/src/chat/preview.html');
    await page.waitForSelector('.v-chat-page');
    if(theme==='light')await page.getByRole('button',{name:'Change theme'}).click();
    await page.getByRole('tab',{name:'Ask your home',exact:true}).hover();await shot('page-ask-empty-hover');
    await page.getByRole('tab',{name:'Household',exact:true}).focus();await shot('page-thread-focus');
    await page.keyboard.press('Enter');
    await shot('page-household-empty');
    const input=page.getByRole('textbox',{name:'Message',exact:true});
    await input.fill('The gate clip is ready to review.');
    await page.getByRole('button',{name:'Send message',exact:true}).hover();await shot('page-send-hover');
    await page.getByRole('button',{name:'Send message',exact:true}).click();
    await page.getByText('The gate clip is ready to review.',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Share options',exact:true}).hover();await shot('page-share-hover');
    await page.getByRole('button',{name:'Share options',exact:true}).click();await shot('page-share-menu');
    const items=page.getByRole('menuitem');
    for(let i=0;i<await items.count();i++){await items.nth(i).hover();await shot(`page-share-menu-hover-${i}`);}
    await page.getByRole('menuitem',{name:'Share a clip',exact:true}).click();await shot('page-clip-picker');
    const picker=page.getByRole('dialog',{name:'Share a clip'});
    await picker.locator('.v-chat-preview-clip-list').hover();await page.mouse.wheel(0,10000);
    await picker.locator('.v-chat-preview-clip-list button').last().click();
    await page.getByRole('button',{name:/Shared clip /}).hover();await shot('page-shared-clip-hover');
    await page.getByRole('button',{name:/Shared clip /}).click();
    await page.getByRole('button',{name:'Dismiss',exact:true}).click();
    for(let i=1;i<=12;i++){
      await input.fill(`QA local note ${i}. This note stays in the browser.\nNo person receives this message.`);
      await input.press('Enter');
    }
    const log=page.getByRole('log');
    await log.hover();await page.mouse.wheel(0,10000);await shot('page-scroll-bottom');
    await page.mouse.wheel(0,-10000);await shot('page-scroll-top');
    await input.focus();await shot('page-composer-focus');
    for(let i=0;i<5;i++){await page.keyboard.press('Tab');await shot(`page-keyboard-focus-${i}`);}
    await page.getByRole('button',{name:'Show popup',exact:true}).hover();await shot('page-layout-switch-hover');
    await page.getByRole('button',{name:'Show popup',exact:true}).click();
    await page.getByRole('dialog',{name:'Messages',exact:true}).waitFor();await shot('popup-household');
    const popup=page.getByRole('dialog',{name:'Messages',exact:true});
    await popup.getByRole('log').hover();await page.mouse.wheel(0,-10000);await shot('popup-scroll-top');
    await page.mouse.wheel(0,10000);await shot('popup-scroll-bottom');
    await popup.getByRole('tab',{name:'Ask your home',exact:true}).hover();await shot('popup-thread-hover');
    await popup.getByRole('tab',{name:'Ask your home',exact:true}).click();await shot('popup-ask-empty');
    await popup.getByRole('tab',{name:'Household',exact:true}).click();
    await popup.getByRole('button',{name:'Share options',exact:true}).click();await shot('popup-share-menu');
    await page.keyboard.press('Escape');
    await popup.getByRole('textbox',{name:'Message',exact:true}).focus();await shot('popup-composer-focus');
    await popup.getByRole('button',{name:'Close messages',exact:true}).hover();await shot('popup-close-hover');
    await page.keyboard.press('Escape');
    if(await page.getByRole('dialog',{name:'Messages',exact:true}).count())failures.push(`${name}/${theme}: Escape did not close popup`);
    await page.getByRole('button',{name:'Messages',exact:true}).hover();await shot('popup-pill-hover');
    await page.getByRole('button',{name:'Messages',exact:true}).click();
    await page.getByRole('button',{name:'Close messages',exact:true}).click();
    const bounds=await page.evaluate(()=>[...document.querySelectorAll('button,textarea')].filter(element=>element.getBoundingClientRect().width&&element.getBoundingClientRect().height).map(element=>({name:element.getAttribute('aria-label')||element.textContent,rect:element.getBoundingClientRect().toJSON()})).filter(({rect})=>rect.x<0||rect.y<0||rect.right>innerWidth||rect.bottom>innerHeight));
    if(bounds.length)failures.push(`${name}/${theme}: controls outside viewport: ${JSON.stringify(bounds)}`);
    if(errors.length)failures.push(...errors.map(error=>`${name}/${theme}: ${error}`));
    report.push({viewport:name,width,height,theme,errors,controlsOutside:bounds.length});
    await context.close();
    console.log(`${name} ${width}x${height} ${theme}: checked`);
  }
}
await browser.close();
await writeFile(path.join(root,'chat-report.json'),JSON.stringify({sha,viewports,report,failures},null,2));
console.log(JSON.stringify({sha,states:report.length,failures},null,2));
if(failures.length)process.exitCode=1;
