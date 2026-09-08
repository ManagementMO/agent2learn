import {chromium} from 'playwright';
import {mkdir,readFile} from 'node:fs/promises';
const revision=JSON.parse(await readFile('src/launchflow-cues.json','utf8')).exportPrefix;
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
  const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
  page.on('pageerror',e=>console.error(e));
  await page.goto('http://localhost:3017/api/projects/a2l-cinematic/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player');
  await page.waitForFunction(()=>window.__a2lSeek&&document.fonts.status==='loaded');
  await page.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth>0));
  await mkdir('.checks',{recursive:true});
  for(const time of [1.6,2.85,5.4,5.9,6.3,6.75,7.5,8.03,10.2,12.15,14.5,17.2]){
    await page.evaluate(t=>window.__a2lSeek(t),time);
    await page.screenshot({path:`.checks/${revision}-${time}.png`});
  }
  console.log('Twelve full-resolution signalflow checkpoints saved.');
}finally{await browser.close();}
