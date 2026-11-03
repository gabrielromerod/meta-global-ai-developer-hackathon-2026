import {chromium} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
const browser=await chromium.launch();const results=[];
for(const theme of ['dark','light']){
 const page=await browser.newPage({viewport:{width:1280,height:600},reducedMotion:'reduce'});
 await page.goto(`http://127.0.0.1:8106/next/src/pages/settings/preview.html?context=edge-owner&theme=${theme}`);
 await page.getByRole('tab',{name:'Owner controls'}).click();
 await page.getByRole('button',{name:'New expected window'}).click();
 const values=await page.locator('.v-dialog-content input,.v-dialog-content select').evaluateAll(elements=>{
  const rgb=value=>(value.match(/[\d.]+/g)||[]).slice(0,3).map(Number);
  const luminance=value=>rgb(value).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
  const ratio=(a,b)=>{const x=luminance(a),y=luminance(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
  return elements.map(element=>{const css=getComputedStyle(element);return{label:document.querySelector(`label[for="${element.id}"]`)?.textContent,border:css.borderTopColor,background:css.backgroundColor,text:css.color,boundaryRatio:ratio(css.borderTopColor,css.backgroundColor),textRatio:ratio(css.color,css.backgroundColor)};});
 });
 results.push({theme,values});await page.close();
}
await browser.close();const dir=path.resolve('..','qa','controls-regressions');await mkdir(dir,{recursive:true});await writeFile(path.join(dir,'form-contrast.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
if(results.some(r=>r.values.some(v=>v.boundaryRatio<3||v.textRatio<4.5)))throw new Error('Enabled form boundaries require 3:1 and text requires 4.5:1 contrast.');
