import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
const browser=await chromium.launch();
const page=await browser.newPage({viewport:{width:1470,height:870}});
await page.goto('http://127.0.0.1:8101/next/src/shell/preview.html');
await page.locator('.v-app-shell').waitFor();
const luminance=color=>{const n=color.replace('#','');const rgb=[0,2,4].map(i=>parseInt(n.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];};
const contrast=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);};
const result=[];
for(const theme of ['dark','light']){
  if(theme==='light')await page.getByRole('button',{name:'Use light theme'}).click();
  const values=await page.locator('.v-app-shell').evaluate(el=>{const style=getComputedStyle(el);return Object.fromEntries(['bg','surface','raised','text','muted','accent','accent-ink','danger','warning','success','unknown'].map(key=>[key,style.getPropertyValue('--v-'+key).trim()]));});
  for(const bg of ['bg','surface','raised'])for(const fg of ['text','muted','accent','danger','warning','success','unknown']){const ratio=contrast(values[bg],values[fg]);result.push({theme,fg,bg,ratio:Number(ratio.toFixed(2))});expect(ratio,`${theme} ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);}
  const ratio=contrast(values.accent,values['accent-ink']);expect(ratio).toBeGreaterThanOrEqual(4.5);result.push({theme,fg:'accent-ink',bg:'accent',ratio:Number(ratio.toFixed(2))});
}
await fs.writeFile('../qa/shell-contrast.json',JSON.stringify(result,null,2));await browser.close();console.log(`PASS: ${result.length} text/background pairs meet 4.5:1; lowest ${Math.min(...result.map(item=>item.ratio))}:1`);
