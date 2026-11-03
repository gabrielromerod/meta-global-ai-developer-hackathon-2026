import {chromium} from '@playwright/test';
import {writeFile,mkdir} from 'node:fs/promises';
const browser=await chromium.launch({headless:true});
const records=[];
for(const theme of ['dark','light']){
  const page=await browser.newPage({viewport:{width:1280,height:600},reducedMotion:'reduce'});
  await page.goto('http://127.0.0.1:8104/next/src/chat/preview.html');
  if(theme==='light')await page.getByRole('button',{name:'Change theme'}).click();
  await page.getByRole('tab',{name:'Household',exact:true}).click();
  await page.getByRole('textbox',{name:'Message',exact:true}).fill('Local contrast check');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  for(const layout of ['page','popup']){
    if(layout==='popup')await page.getByRole('button',{name:'Show popup',exact:true}).click();
    const result=await page.evaluate(layout=>{
      const rgba=value=>{const parts=value.match(/[\d.]+/g)?.map(Number)??[0,0,0,0];return [...parts.slice(0,3),parts[3]??1];};
      const composite=(a,b)=>a.slice(0,3).map((v,i)=>v*a[3]+b[i]*(1-a[3]));
      const background=element=>{
        if(!element)return [255,255,255];
        const color=rgba(getComputedStyle(element).backgroundColor);
        return color[3]===1?color.slice(0,3):composite(color,background(element.parentElement));
      };
      const luminance=rgb=>rgb.map(value=>{const s=value/255;return s<=.04045?s/12.92:((s+.055)/1.055)**2.4;}).reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
      return [...document.querySelectorAll(`.v-chat-${layout} p,.v-chat-${layout} h2,.v-chat-${layout} h3,.v-chat-${layout} strong,.v-chat-${layout} small,.v-chat-${layout} .v-chat-message-author`)].filter(element=>element.getBoundingClientRect().height&&element.textContent.trim()&&!element.closest(':disabled')).map(element=>{
        const css=getComputedStyle(element),text=rgba(css.color).slice(0,3),bg=background(element);
        const a=luminance(text),b=luminance(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        const large=parseFloat(css.fontSize)>=24||(parseFloat(css.fontSize)>=18.66&&parseFloat(css.fontWeight)>=700);
        return {text:element.textContent.trim(),color:css.color,background:bg,ratio:Math.round(ratio*100)/100,minimum:large?3:4.5,pass:ratio>=(large?3:4.5)};
      });
    },layout);
    records.push({theme,layout,checks:result});
  }
  await page.close();
}
await browser.close();
await mkdir('../data/chat-inspection',{recursive:true});
await writeFile('../data/chat-inspection/contrast.json',JSON.stringify(records,null,2));
const failures=records.flatMap(record=>record.checks.filter(check=>!check.pass).map(check=>({...check,theme:record.theme,layout:record.layout})));
console.log(JSON.stringify({checks:records.reduce((sum,record)=>sum+record.checks.length,0),minimumRatio:Math.min(...records.flatMap(record=>record.checks.map(check=>check.ratio))),failures},null,2));
if(failures.length)process.exitCode=1;
