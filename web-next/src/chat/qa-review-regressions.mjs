import {chromium} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';

const browser=await chromium.launch();
const root=path.resolve(process.env.QA_OUTPUT||'../data/chat-review-regressions');await mkdir(root,{recursive:true});
const viewports=[['mac-air',1470,870],['mac-pro-14',1512,895],['mac-pro-16',1728,1030],['windows-100',1920,960],['windows-125',1536,730],['windows-150',1280,600],['laptop',1366,650],['four-three',1024,768],['tablet',1180,820],['ultrawide',2560,1000],['phone',390,844]];
const failures=[],results=[];
for(const [name,width,height] of viewports){
  const folder=path.join(root,`${name}-${width}x${height}`);await mkdir(folder,{recursive:true});
  for(const theme of ['dark','light'])for(const thread of ['ask-home','household'])for(const state of ['empty','pending-0','pending-1']){
    const pending=state!=='empty',messages=state==='pending-1'?1:0;
    const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'});
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    page.on('requestfailed',request=>errors.push(`${request.url()}: ${request.failure()?.errorText}`));
    await page.goto(`http://127.0.0.1:8104/next/src/chat/review-preview.html?thread=${thread}&popup=1&messages=${messages}&pending=${pending?1:0}`);
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    const popup=page.getByRole('dialog',{name:'Messages',exact:true});await popup.waitFor();
    await page.evaluate(()=>document.fonts.ready);
    await page.waitForTimeout(250);
    const bounds=await popup.evaluate((element,pending)=>{
      const history=element.querySelector('.v-chat-history').getBoundingClientRect();
      const nodes=pending?[element.querySelector('[role=status]')]:[...element.querySelectorAll('.v-chat-empty h3,.v-chat-empty p')];
      const text=nodes.map(node=>({text:node.textContent,rect:node.getBoundingClientRect().toJSON()}));
      return {history:history.toJSON(),text,visible:text.every(({rect})=>rect.top>=history.top&&rect.bottom<=history.bottom)};
    },pending);
    await page.screenshot({path:path.join(folder,`chat-round2-${theme}-${thread}-${state}.png`)});
    const help=await page.locator('.v-chat-page .v-chat-composer-tools p').textContent();
    if(help!=='Enter to send \u00b7 Shift+Enter for a new line')errors.push('Keyboard help has corrupted punctuation');
    if(pending){
      const expected=thread==='ask-home'?'Searching the visit ledger\u2026':'Saving your local message\u2026';
      if(bounds.text[0].text!==expected)errors.push('Pending text has corrupted punctuation');
      if(!await popup.getByRole('button',{name:'Send message'}).isDisabled())errors.push('Pending state allows a duplicate send');
    }
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth||document.documentElement.scrollHeight>innerHeight);
    if(overflow)errors.push('Document overflow');
    results.push({name,width,height,theme,thread,state,bounds,errors});
    if(!bounds.visible)failures.push(`${name}/${theme}/${thread}/${state}: copy extends beyond message history`);
    failures.push(...errors.map(error=>`${name}/${theme}/${thread}/${state}: ${error}`));
    await page.close();
  }
  console.log(`${name} ${width}x${height}: empty and pending states in both themes checked`);
}
await browser.close();
await writeFile(path.join(root,'chat-round2-report.json'),JSON.stringify({results,failures},null,2));
console.log(JSON.stringify({states:results.length,failures},null,2));
if(failures.length)process.exitCode=1;
