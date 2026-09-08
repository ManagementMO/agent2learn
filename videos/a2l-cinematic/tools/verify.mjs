import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {chromium} from 'playwright';

// Exercise the real compiled composition, including head-hoisted local bundles.
// This caught a startup-order bug that lint alone could not identify.
const base=process.env.A2L_PREVIEW_URL||'http://localhost:3017';
const browser=await chromium.launch({channel:'chrome',headless:true});
const findings={runtimeErrors:[],failedAssets:[],externalRequests:[],seeks:[]};
try {
  const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
  page.setDefaultTimeout(20000);
  page.on('pageerror',e=>findings.runtimeErrors.push(e.message));
  page.on('response',r=>{if(r.status()>=400)findings.failedAssets.push({url:r.url(),status:r.status()});});
  await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(!['localhost','127.0.0.1'].includes(url.hostname)&&url.protocol!=='data:'){
      findings.externalRequests.push(url.origin);return route.abort();
    }
    return route.continue();
  });
  await page.goto(`${base}/api/projects/a2l-cinematic/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player`);
  await page.waitForFunction(()=>window.__a2lSeek&&document.fonts.status==='loaded');
  console.log('Compiled timeline and local fonts ready.');
  assert.equal(await page.evaluate(()=>typeof window.__a2lSeek(0)),'undefined','Seek setter must not return a paused thenable');
  await page.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth>0));
  assert.equal(await page.evaluate(()=>window.__a2lTimeline.duration()),13.5);
  assert.equal(await page.locator('canvas').count(),0,'The removed file-stack hero must not return');
  const logo=await readFile('assets/brand/frontend-mark.svg');
  const logoSrc=await page.locator('#brand-mark').getAttribute('src');
  // HyperFrames inlines SVGs in compiled preview; check the actual bytes, not
  // the pre-compilation URL spelling, so a compiler optimization isn't a failure.
  assert.ok(logoSrc==='assets/brand/frontend-mark.svg'||logoSrc===`data:image/svg+xml;base64,${logo.toString('base64')}`);
  // Historical cut: pin its preserved book mark, not today's rebranded website.
  assert.equal(createHash('sha256').update(logo).digest('hex'),
    'ea3b7fdb9152b63cfadc7f0bd163ced1519d5562316b95c239f6955db9461483', // pragma: allowlist secret -- public book-mark SHA-256
    'Historical film must retain its original book mark');
  assert.equal(await page.locator('#codex-banner strong').textContent(),'›_ Codex');
  assert.equal(await page.locator('#send-button,#composer').count(),0,'A terminal must not contain the old chat composer');
  assert.ok(!/Claude/.test(await page.locator('#film').textContent()),'Only one coding agent is shown');
  assert.equal(await page.locator('audio').count(),3,'Music, typing and interface stems stay independently editable');
  const expected=[[0,'showcase'],[.8,'lecture-resource'],[2.95,'local-vault'],[4.55,'codex-banner'],[6.4,'question'],[8.5,'citation-chip'],[10.3,'source-window'],[11.5,'source-proof'],[13.2,'end'],[13.491,'end']];
  const hashes=new Map();
  const pixels=new Map(),domStates=new Map();findings.rasterEdgeVariance=[];
  const readDomState=()=>[...document.querySelectorAll('#film *')].map(e=>{
    const s=getComputedStyle(e),r=e.getBoundingClientRect();
    return {id:e.id,tag:e.tagName,text:e.children.length?null:e.textContent,
      box:[r.x,r.y,r.width,r.height],opacity:s.opacity,visibility:s.visibility,
      transform:s.transform,clipPath:s.clipPath,filter:s.filter,color:s.color,
      background:s.background,border:s.border,borderRadius:s.borderRadius};
  });
  await mkdir('.checks',{recursive:true});
  for(const [time,scene] of expected){
    await page.evaluate(t=>window.__a2lSeek(t),time);
    const state=await page.evaluate(id=>{const e=document.getElementById(id);let opacity=1;for(let p=e;p;p=p.parentElement)opacity*=Number(getComputedStyle(p).opacity);return {opacity,visible:getComputedStyle(e).visibility};},scene);
    assert.equal(state.visible,'visible',`${scene} must be visible at ${time}`);
    assert.ok(Number(state.opacity)>.95,`${scene} must be fully present at ${time}`);
    const shot=await page.screenshot();
    await writeFile(`.checks/forward-${time}.png`,shot);
    hashes.set(time,createHash('sha256').update(shot).digest('hex'));
    pixels.set(time,shot.toString('base64'));
    domStates.set(time,await page.evaluate(readDomState));
    findings.seeks.push({time,scene,visible:true});
    console.log(`Hero frame ${scene} at ${time}s checked.`);
  }
  for(const [time] of [...expected].reverse()){
    await page.evaluate(t=>window.__a2lSeek(t),time);
    const shot=await page.screenshot();
    await writeFile(`.checks/reverse-${time}.png`,shot);
    assert.deepEqual(await page.evaluate(readDomState),domStates.get(time),`Every node's geometry, text and visual style must match after a reverse seek at ${time}s`);
    if(createHash('sha256').update(shot).digest('hex')!==hashes.get(time)){
      // Chrome's recycled layers vary a handful of rounded-border antialias
      // pixels. Require exact DOM/style equality, a hard 32-pixel budget, and
      // independently locate every difference on a known rounded boundary.
      // Interior text/geometry differences are never covered by this exception.
      const delta=await page.evaluate(async({a,b})=>{
        const decode=async src=>{const image=new Image();image.src=`data:image/png;base64,${src}`;await image.decode();const canvas=document.createElement('canvas');canvas.width=1920;canvas.height=1080;const c=canvas.getContext('2d');c.drawImage(image,0,0);return c.getImageData(0,0,1920,1080).data;};
        const[p,q]=await Promise.all([decode(a),decode(b)]);let count=0,max=0,offEdge=0;
        const boundaries=[...document.querySelectorAll('#camera-viewport,#terminal-content,#codex-banner,#step-labels b,#agent-window,#source-window,#source-view,.chrome-dots i,#enter-key')].map(e=>{
          const r=e.getBoundingClientRect(),s=getComputedStyle(e);
          return {l:r.left,t:r.top,r:r.right,b:r.bottom,radius:Math.min(r.width/2,r.height/2,parseFloat(s.borderTopLeftRadius)*(e.clientWidth?r.width/e.clientWidth:1))};
        });
        const onBoundary=(x,y)=>boundaries.some(b=>{
          if(x<b.l-2||x>b.r+2||y<b.t-2||y>b.b+2)return false;
          const radius=b.radius||0;
          if((x>=b.l+radius&&x<=b.r-radius)&&(Math.abs(y-b.t)<=2||Math.abs(y-b.b)<=2))return true;
          if((y>=b.t+radius&&y<=b.b-radius)&&(Math.abs(x-b.l)<=2||Math.abs(x-b.r)<=2))return true;
          return [[b.l+radius,b.t+radius],[b.r-radius,b.t+radius],[b.l+radius,b.b-radius],[b.r-radius,b.b-radius]].some(([cx,cy])=>Math.abs(Math.hypot(x-cx,y-cy)-radius)<=2);
        });
        for(let i=0;i<p.length;i+=4){const diff=Math.max(Math.abs(p[i]-q[i]),Math.abs(p[i+1]-q[i+1]),Math.abs(p[i+2]-q[i+2]));if(diff){count++;max=Math.max(max,diff);const x=(i/4)%1920,y=Math.floor(i/4/1920);if(!onBoundary(x,y)&&!(diff===1&&y>992&&y<1025))offEdge++;}}
        return {count,max,offEdge};
      },{a:pixels.get(time),b:shot.toString('base64')});
      assert.ok(delta.count<=32&&delta.max<=16&&delta.offEdge===0,`Out-of-order pixel mismatch at ${time}s: ${JSON.stringify(delta)}`);
      findings.rasterEdgeVariance.push({time,...delta});
    }
  }
  findings.clicks=[];
  for(const[time,target]of[[.8,'#lecture-resource'],[9,'#citation-chip']]){
    const onTarget=await page.evaluate(({time,target})=>{
      window.__a2lSeek(time);const a=document.querySelector(target).getBoundingClientRect(),b=document.getElementById('cursor').getBoundingClientRect();
      return b.left>a.left&&b.left<a.right&&b.top>a.top&&b.top<a.bottom;
    },{time,target});
    assert.ok(onTarget,`Cursor must actually click ${target}`);findings.clicks.push({time,target,onTarget});
  }
  const audio=JSON.parse(await readFile('audio_meta.json','utf8'));
  const schedules=await page.evaluate(()=>window.__a2lTyping);
  for(const expected of audio.typing){
    const actual=schedules[expected.selector];assert.deepEqual(actual,expected,'Audio and visual cadence must use identical compiled cues');
    const events=audio.events.filter(e=>e.kind==='recorded_key'&&e.selector===expected.selector);
    assert.deepEqual(events.map(e=>e.time),actual.rows.map(r=>r.time),'Every character has its exact recorded-key event');
  }
  const typing=schedules['#question'];
  findings.typing=[];
  for(const time of[4.7,4.85,5.3,5.9,6.36,5.3]){
    const shown=await page.evaluate(time=>{window.__a2lSeek(time);return document.querySelector('#question .typed-text').textContent;},time);
    const count=typing.rows.filter(row=>row.time<=time+1e-5).length;
    assert.equal(shown,typing.text.slice(0,count),'Typing must be a deterministic prefix at every seek');
    findings.typing.push({time,shown});
  }
  // Check the active task, not every off-camera object in a deliberately wide
  // 2800px world. Whole windows fit on rest poses; the citation is a close crop.
  findings.focusFrames=[];
  for(const[time,selector]of[[.8,'#learn-window'],[5.9,'#agent-window'],[8.5,'#citation-chip'],[10.3,'#agent-window'],[10.3,'#source-window']]){
    const frame=await page.evaluate(({time,selector})=>{window.__a2lSeek(time);const r=document.querySelector(selector).getBoundingClientRect(),v=document.querySelector('#camera-viewport').getBoundingClientRect();return {time,selector,inside:r.left>=v.left&&r.right<=v.right&&r.top>=v.top&&r.bottom<=v.bottom,transform:getComputedStyle(document.querySelector('#demo-world')).transform};},{time,selector});
    assert.ok(frame.inside,`${selector} must fit its proof frame at ${time}`);findings.focusFrames.push(frame);
  }
  assert.equal(new Set(findings.focusFrames.map(f=>f.transform)).size,4,'Camera must have distinct authored poses');
  // Sweep the intended layout relationships at the actual 120fps master cadence.
  // Entrance masks can hide part of a box, but should never be needed to conceal
  // a collision between a headline and its primary product panel.
  const collisions=await page.evaluate(()=>{
    const found=[];
    const pairs=[['#demo-header','#camera-viewport'],['#launch-line','#codex-banner'],
      ['#codex-banner','#prompt-line'],['#prompt-line','#reading'],
      ['#reading','#answer'],['#answer','#citation-chip'],['#citation-chip','#terminal-footer'],
      ['#agent-window','#source-window'],
      ['.source-code','#source-proof'],
      ['#brand-mark','#wordmark'],['#wordmark','#end-tagline'],['#end-tagline','#end-url']];
    for(let frame=0;frame<1620;frame++){
      const time=frame/120;window.__a2lSeek(time);
      for(const selectors of pairs){
        const elements=selectors.map(s=>document.querySelector(s));
        if(elements.some(e=>getComputedStyle(e).visibility!=='visible'||Number(getComputedStyle(e).opacity)<.02))continue;
        const[a,b]=elements.map(e=>e.getBoundingClientRect());
        if(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top){
          found.push({time,selectors});
        }
      }
    }
    return found;
  });
  assert.equal(collisions.length,0,`Headline/panel/lockup collisions: ${JSON.stringify(collisions.slice(0,3))}`);
  await page.evaluate(()=>window.__a2lSeek(10.3));
  const excerpt=await readFile('assets/demo/content/Week 3/Lecture 06.md','utf8');
  const shown=await page.locator('.code-line').allTextContents();
  for(let i=0;i<shown.length;i++){
    const line=142+i;
    assert.equal(shown[i].trim().replace(new RegExp(`^${line}\\s*`),''),excerpt.split('\n')[line-1],`Source line ${line} must match the demo file`);
  }
  assert.deepEqual(findings.runtimeErrors,[]);
  assert.deepEqual(findings.failedAssets,[]);
  assert.deepEqual(findings.externalRequests,[]);
  findings.status='passed';findings.randomSeekVisualEquality=true;findings.exactPixelFrames=expected.length-findings.rasterEdgeVariance.length;findings.sourceLines=[142,147];findings.layoutFramesChecked=1620;findings.typingAudioEvents=audio.typing.reduce((n,s)=>n+s.rows.length,0);
  await mkdir('.checks',{recursive:true});
  await writeFile('.checks/codex-behavior.json',JSON.stringify(findings,null,2)+'\n');
  console.log(JSON.stringify(findings,null,2));
} finally {await browser.close();}
