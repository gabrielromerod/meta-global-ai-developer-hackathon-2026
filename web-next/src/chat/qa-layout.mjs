import {chromium} from '@playwright/test';
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1280,height:600},reducedMotion:'reduce'});
await page.goto('http://127.0.0.1:8104/next/src/chat/preview.html');
await page.getByRole('tab',{name:'Household',exact:true}).click();
const result=await page.evaluate(()=>{
  const history=document.querySelector('.v-chat-history').getBoundingClientRect();
  const text=[...document.querySelectorAll('.v-chat-empty p')].at(-1).getBoundingClientRect();
  return {visible:text.top>=history.top&&text.bottom<=history.bottom,historyBottom:history.bottom,textBottom:text.bottom};
});
await browser.close();
console.log(JSON.stringify(result));
if(!result.visible)throw new Error('The empty-state explanation must fit within the short-window message history.');
