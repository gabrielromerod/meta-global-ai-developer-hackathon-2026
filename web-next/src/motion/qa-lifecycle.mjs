import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const sha=process.env.MOTION_QA_SHA||execFileSync('git',['rev-parse','--short','HEAD'],{encoding:'utf8'}).trim();
const output=path.resolve('../qa/screens',sha);await fs.mkdir(path.join(output,'1280x600'),{recursive:true});
const report={sha,started:new Date().toISOString(),errors:[],failedRequests:[]};
const browser=await chromium.launch(),page=await browser.newPage({viewport:{width:1280,height:600},reducedMotion:'no-preference'});
page.on('pageerror',e=>report.errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text());});page.on('requestfailed',r=>report.failedRequests.push(r.url()));
try {
 await page.addInitScript(()=>{
  const original=window.matchMedia.bind(window),queries=new Map();window.motionLifecycleQueries=queries;
  window.matchMedia=query=>{
   const media=original(query);if(!query.includes('prefers-reduced-motion'))return media;
   if(!queries.has(query))queries.set(query,new Set());const listeners=queries.get(query);
   const add=media.addEventListener.bind(media),remove=media.removeEventListener.bind(media),legacyAdd=media.addListener.bind(media),legacyRemove=media.removeListener.bind(media);
   media.addEventListener=(type,listener,...rest)=>{if(type==='change')listeners.add(listener);return add(type,listener,...rest);};
   media.removeEventListener=(type,listener,...rest)=>{if(type==='change')listeners.delete(listener);return remove(type,listener,...rest);};
   media.addListener=listener=>{listeners.add(listener);return legacyAdd(listener);};
   media.removeListener=listener=>{listeners.delete(listener);return legacyRemove(listener);};return media;
  };
 });
 await page.goto('http://127.0.0.1:8107/next/');
 await page.evaluate(async()=>{
  const reactModule=await import('/next/node_modules/.vite/deps/react.js'),DOM=await import('/next/node_modules/.vite/deps/react-dom_client.js'),module=await import('/next/src/motion/index.tsx'),React=reactModule.default??reactModule;
  const create=React.createElement,host=document.createElement('div'),root=(DOM.createRoot??DOM.default.createRoot)(host);document.body.append(host);
  function Probe(){const reduced=module.useMotionPreference(),[draft,setDraft]=React.useState('');return create('section',null,create('h2',null,'Motion listener lifecycle'),create('output',{'aria-label':'Reduced preference'},String(reduced)),create('input',{'aria-label':'Preserved draft',value:draft,onChange:event=>setDraft(event.target.value)}));}
  const read=()=>({queries:[...window.motionLifecycleQueries].map(([query,set])=>({query,count:set.size})),total:[...window.motionLifecycleQueries.values()].reduce((sum,set)=>sum+set.size,0)});
  window.motionLifecycle={root,Probe,create,read,host,baseline:read(),mount:()=>root.render(create(React.Fragment,null,create(Probe),create(Probe,{key:'second'})))};
  window.motionLifecycle.mount();
 });
 await page.getByRole('textbox',{name:'Preserved draft'}).first().waitFor();
 report.baseline=await page.evaluate(()=>window.motionLifecycle.baseline);report.mounted=await page.evaluate(()=>window.motionLifecycle.read());
 const field=page.getByRole('textbox',{name:'Preserved draft'}).first();await field.fill('Draft survives device preference changes.');await field.evaluate(el=>window.lifecycleInput=el);
 report.preferences=[];
 for(const preference of ['reduce','no-preference']){
  await page.emulateMedia({reducedMotion:preference});await expect(page.getByLabel('Reduced preference').first()).toHaveText(preference==='reduce'?'true':'false');
  const state=await field.evaluate(el=>({sameInput:el===window.lifecycleInput,focused:document.activeElement===el,draft:el.value,listeners:window.motionLifecycle.read()}));report.preferences.push({preference,...state});
 }
 await page.screenshot({path:path.join(output,'1280x600','motion-isolated-listener-context.png')});
 await page.evaluate(()=>window.motionLifecycle.root.unmount());
 report.unmounted=await page.evaluate(()=>window.motionLifecycle.read());
 expect({baseline:report.baseline.total,mounted:report.mounted.total,unmounted:report.unmounted.total}).toEqual({baseline:0,mounted:1,unmounted:0});
 for(const state of report.preferences){expect(state.sameInput).toBe(true);expect(state.focused).toBe(true);expect(state.draft).toBe('Draft survives device preference changes.');expect(state.listeners.total).toBe(1);}
 expect(report.errors).toEqual([]);expect(report.failedRequests).toEqual([]);
 report.passed=true;
} catch(error){report.passed=false;report.failure=String(error);process.exitCode=1;}
finally {report.finished=new Date().toISOString();await fs.writeFile(path.join(output,'motion-isolated-listener-results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));await browser.close();}
