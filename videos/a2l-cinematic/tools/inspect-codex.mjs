import {chromium} from 'playwright';
import {mkdir} from 'node:fs/promises';
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
  const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
  page.on('pageerror',e=>console.error(e));
  await page.goto('http://localhost:3017/api/projects/a2l-cinematic/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player');
  await page.waitForFunction(()=>window.__a2lSeek&&document.fonts.status==='loaded');
  await page.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth>0));
  await mkdir('.checks',{recursive:true});
  for(const time of [.8,2.95,4.3,5.9,6.5,8.5,10.3,13.2]){
    await page.evaluate(t=>window.__a2lSeek(t),time);
    await page.screenshot({path:`.checks/codex-${time}.png`});
  }
  console.log('Eight 1920x1080 inspection frames saved.');
}finally{await browser.close();}
