import {chromium} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve('..');
const out=path.join(root,'qa','references','shell');
await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1470,height:870}});
const results=[];
for(const [name,url] of [['instagram-public','https://www.instagram.com/'],['meta-public','https://www.meta.com/'],['messenger-public','https://www.messenger.com/']]){
  try{await page.goto(url,{waitUntil:'domcontentloaded',timeout:30000});await page.waitForTimeout(2000);results.push({name,url,title:await page.title(),finalUrl:page.url(),status:'captured'});await page.screenshot({path:path.join(out,`${name}.png`),fullPage:false});}
  catch(error){results.push({name,url,status:'unavailable',error:String(error)});}
}
await fs.writeFile(path.join(out,'capture.json'),JSON.stringify(results,null,2));
await browser.close();
console.log(JSON.stringify(results));
