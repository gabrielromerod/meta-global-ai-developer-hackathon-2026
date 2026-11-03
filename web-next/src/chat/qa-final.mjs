import {chromium} from '@playwright/test';
import {mkdir,writeFile,copyFile} from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const sha=execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const root=path.resolve('../qa/screens',sha);
const viewports=[['mac-air',1470,870],['mac-pro-14',1512,895],['mac-pro-16',1728,1030],['windows-100',1920,960],['windows-125',1536,730],['windows-150',1280,600],['laptop',1366,650],['four-three',1024,768],['tablet',1180,820],['ultrawide',2560,1000],['phone',390,844]];
const browser=await chromium.launch();
const runs=[];
for(const [name,width,height] of viewports){
  for(const theme of ['dark','light']){
    const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    page.on('requestfailed',request=>errors.push(`${request.url()}: ${request.failure()?.errorText}`));
    const folder=path.join(root,`${name}-${width}x${height}`);await mkdir(folder,{recursive:true});
    const shot=async state=>page.screenshot({path:path.join(folder,`chat-${theme}-${state}.png`)});
    await page.goto('http://127.0.0.1:8104/next/src/chat/preview.html');
    if(theme==='light')await page.getByRole('button',{name:'Change theme'}).click();
    await shot('page-ask-empty');
    await page.getByRole('tab',{name:'Household',exact:true}).click();await shot('page-household-empty');
    await page.getByRole('textbox',{name:'Message',exact:true}).fill('This local note stays in the browser.');
    await page.getByRole('button',{name:'Send message',exact:true}).click();
    await page.getByRole('textbox',{name:'Message',exact:true}).focus();await shot('page-composer-focus');
    await page.getByRole('button',{name:'Share options',exact:true}).click();await shot('page-share-menu');
    await page.keyboard.press('Escape');
    await page.getByRole('button',{name:'Show popup',exact:true}).click();await shot('popup-household');
    await page.getByRole('dialog',{name:'Messages',exact:true}).getByRole('button',{name:'Share options'}).click();await shot('popup-share-menu');
    const overflow=await page.evaluate(()=>({width:document.documentElement.scrollWidth>innerWidth,height:document.documentElement.scrollHeight>innerHeight}));
    if(overflow.width||overflow.height)errors.push(`Document overflow ${JSON.stringify(overflow)}`);
    runs.push({name,width,height,theme,errors});await page.close();
  }
  console.log(`${name} ${width}x${height}: final dark/light screenshots captured`);
}
await browser.close();
await writeFile(path.join(root,'chat-final-report.json'),JSON.stringify({sha,runs},null,2));
await copyFile('../data/chat-inspection/contrast.json',path.join(root,'chat-contrast-report.json'));
console.log(JSON.stringify({sha,runs:runs.length,failures:runs.flatMap(run=>run.errors)},null,2));
if(runs.some(run=>run.errors.length))process.exitCode=1;
