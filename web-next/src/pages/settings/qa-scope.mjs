// Authored prop probe only. Intercepts the local preview module, never an API.
import {chromium,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const sha=execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const phase=process.env.CONTROLS_SCOPE_PHASE||'after';
const root=path.resolve('..','qa','screens',sha,`scope-${phase}`);await mkdir(root,{recursive:true});
const report={sha,phase,started:new Date().toISOString(),cases:[],errors:[]};
const browser=await chromium.launch();
for(const [width,height] of [[1280,600],[390,844]])for(const theme of ['dark','light']){
 const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'});
 page.on('pageerror',e=>report.errors.push(e.message));page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text());});
 page.on('requestfailed',r=>report.errors.push(r.url()));page.on('response',r=>{if(r.status()>=400)report.errors.push(`${r.status()} ${r.url()}`);});
 await page.route('**/src/pages/settings/preview.tsx*',async route=>{
  const response=await route.fetch();const source=await response.text();
  const marker='if (context?.startsWith("edge"))';
  if(!source.includes(marker))throw new Error('Preview module scope-probe insertion point changed');
  const probe=`const observedZone=state.events.find(e=>e.target==='side_alley')?.target;
  if(!observedZone)throw new Error('No supplied side alley zone in source fixture');
  const template=state.owner.windows[0];const camera=state.cameras.find(c=>c.id==='doorbell');
  if(!template||!camera)throw new Error('Missing source expected window or camera');
  state.owner.windows=[template,...[
    {label:'Zone scope test',cameras:[],zones:[observedZone]},
    {label:'Camera scope test',cameras:[camera.id],zones:[]},
    {label:'Combined scope test',cameras:[camera.id],zones:[observedZone]},
    {label:'Unrestricted scope test',cameras:[],zones:[]}
  ].map((scope,index)=>({...template,...scope,id:'scope-'+index,recorded:false,state:'scheduled'}))];
  `;
  await route.fulfill({response,body:source.replace(marker,probe+marker)});
 });
 await page.goto(`http://127.0.0.1:8106/next/src/pages/settings/preview.html?theme=${theme}`);await page.evaluate(()=>document.fonts.ready);
 await page.getByRole('tab',{name:'Owner controls'}).click();
 const panel=page.getByLabel('Owner controls settings',{exact:true});
 const prefix=`${width}x${height}-${theme}`;const checks=[];
 for(const [label,lines] of [['Zone scope test',['Zones: Side alley']],['Camera scope test',['Cameras: Doorbell']],['Combined scope test',['Cameras: Doorbell','Zones: Side alley']],['Unrestricted scope test',['All configured cameras']]]){
  const row=page.getByRole('article',{name:label,exact:true});await row.scrollIntoViewIfNeeded();
  for(const line of lines){const actual=await row.innerText();const passed=actual.includes(line)&&(!(line.startsWith('Zones:')||line.startsWith('Cameras:'))||!actual.includes('All configured cameras'));checks.push({label,line,passed,actual});if(phase!=='before')await expect(row).toContainText(line);}
  await page.screenshot({path:path.join(root,`${prefix}-${label.replaceAll(' ','-')}.png`)});
 }
 for(const position of ['top','bottom']){
  if(width>640)await panel.evaluate((e,pos)=>e.scrollTo({top:pos==='top'?0:e.scrollHeight,behavior:'instant'}),position);
  else await page.evaluate(pos=>scrollTo({top:pos==='top'?0:document.documentElement.scrollHeight,behavior:'instant'}),position);
  await page.screenshot({path:path.join(root,`${prefix}-list-${position}.png`)});
 }
 const geometry=await page.evaluate(()=>({width:innerWidth,height:innerHeight,docWidth:document.documentElement.scrollWidth,docHeight:document.documentElement.scrollHeight,scrollY}));
 expect(geometry.width).toBe(width);expect(geometry.height).toBe(height);expect(geometry.docWidth).toBeLessThanOrEqual(width);if(width>640){expect(geometry.docHeight).toBeLessThanOrEqual(height);expect(geometry.scrollY).toBe(0);}
 report.cases.push({width,height,theme,checks,geometry});await page.close();
}
await browser.close();report.finished=new Date().toISOString();await writeFile(path.join(root,'scope-results.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({cases:report.cases.length,checks:report.cases.flatMap(c=>c.checks).length,failed:report.cases.flatMap(c=>c.checks).filter(c=>!c.passed).length,errors:report.errors}));
expect(report.errors).toEqual([]);
