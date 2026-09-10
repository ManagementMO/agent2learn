import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {readFile,writeFile} from 'node:fs/promises';
import {promisify} from 'node:util';
import {chromium} from 'playwright';
const exec=promisify(execFile),report={variants:[],invalidVariantRefused:false};
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
  const brands=JSON.parse(await readFile('src/brand-variant.json','utf8'));
  for(const [variant,asset] of Object.entries(brands.variants)){
    await exec('node',['tools/build.mjs',`--brand=${variant}`]);
    const page=await browser.newPage({viewport:{width:1920,height:1080}});
    await page.goto('http://localhost:3017/api/projects/a2l-cinematic/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player');
    await page.waitForFunction(()=>window.__a2lSeek&&document.fonts.status==='loaded'&&[...document.images].every(i=>i.complete&&i.naturalWidth));
    assert.equal(await page.locator('html').getAttribute('data-brand-variant'),variant);
    await page.evaluate(()=>window.__a2lSeek(17.2));
    const geometry=await page.locator('#brand-mark').boundingBox();
    assert.equal(geometry.width,variant==='frontend'?170:420);
    assert.equal(geometry.height,variant==='frontend'?170:variant==='waterloo-gold'?168:210);
    const path=asset.src;
    const src=await page.locator('#brand-mark').getAttribute('src');
    const data=`data:image/${path.endsWith('.svg')?'svg+xml':'png'};base64,${(await readFile(path)).toString('base64')}`;
    assert.ok(src===path||src===data,'Preview may embed SVGs; the selected artwork bytes must still match');
    await page.screenshot({path:`.checks/signalflow-polish-brand-${variant}.png`});
    report.variants.push({variant,geometry,passed:true});await page.close();
  }
  const before=await readFile('index.html');
  await assert.rejects(exec('node',['tools/build.mjs','--brand=not-a-variant']));
  assert.deepEqual(await readFile('index.html'),before,'Invalid variant cannot replace the valid composition');
  report.invalidVariantRefused=true;
  report.status='passed';
  await writeFile('.checks/signalflow-polish-brand-variants.json',JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
}finally{
  await browser.close();
  await exec('node',['tools/build.mjs']);
}
