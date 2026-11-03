import {chromium, expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const source=process.env.VIGIL_QA_SHA || 'boundary-red';
const root=path.resolve('..','qa','screens',source,'field-boundaries');
await fs.mkdir(root,{recursive:true});
const browser=await chromium.launch({headless:true});
const cases=[];const failures=[];const started=new Date().toISOString();
try {
 for(const [width,height] of [[1280,600],[390,844]])for(const theme of ['dark','light'])for(const route of ['clips','media']) {
  const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});const page=await context.newPage();const errors=[];
  page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  page.on('requestfailed',r=>errors.push(r.url()+': '+r.failure()?.errorText));
  await page.goto(`http://127.0.0.1:8105/next/src/pages/clips/preview.html?route=${route}&theme=${theme}`);
  await page.waitForFunction(()=>document.body.dataset.ready==='1');await page.evaluate(()=>document.fonts.ready);
  const measures=[];
  async function check(field,label){
   for(const state of ['rest','hover','focus']) {
    await page.mouse.move(0,0);await field.evaluate(el=>el.blur());
    if(state==='hover')await field.hover();if(state==='focus')await field.focus();
    const value=await field.evaluate(el=>{
     const rgb=v=>(v.match(/[\d.]+/g)||[]).map(Number);
     const blend=(fg,bg)=>fg.slice(0,3).map((v,i)=>v*(fg[3]??1)+bg[i]*(1-(fg[3]??1)));
     function surface(node){if(!node)return [255,255,255];return blend(rgb(getComputedStyle(node).backgroundColor),surface(node.parentElement));}
     const luminance=c=>c.map(v=>{const s=v/255;return s<=.04045?s/12.92:((s+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
     const ratio=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
     const css=getComputedStyle(el),inside=surface(el),outside=surface(el.parentElement),border=blend(rgb(css.borderTopColor),outside);
     return {border:css.borderTopColor,inside,outside,insideRatio:ratio(border,inside),outsideRatio:ratio(border,outside),box:{width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height},outline:css.outline};
    });
    measures.push({label,state,...value});
    if(Math.min(value.insideRatio,value.outsideRatio)<3)failures.push(`${width}x${height} ${theme} ${route} ${label} ${state}: ${Math.min(value.insideRatio,value.outsideRatio)}`);
    await page.screenshot({path:path.join(root,`${width}x${height}-${route}-${theme}-${label}-${state}.png`)});
   }
  }
  await check(page.getByRole('searchbox',{name:'Search evidence'}),'search');
  await check(page.getByRole('combobox',{name:'Camera',exact:true}),'camera');
  await check(page.getByRole('combobox',{name:'Verdict',exact:true}),'verdict');
  if(route==='media') {
   await page.getByRole('button',{name:'Time range',exact:true}).click();
   await check(page.getByLabel('From (local time)',{exact:true}),'from');
   await check(page.getByLabel('Until (local time)',{exact:true}),'until');
   await page.keyboard.press('Escape');
  }
  cases.push({width,height,theme,route,measures,errors});failures.push(...errors);await context.close();
 }
}finally{await browser.close();}
await fs.writeFile(path.join(root,'results.json'),JSON.stringify({source,started,finished:new Date().toISOString(),cases,failures},null,2));
console.log(`${cases.length} cases, ${failures.length} failures`);
expect(failures,'Every enabled field boundary must contrast >=3:1 with both adjoining surfaces').toEqual([]);
