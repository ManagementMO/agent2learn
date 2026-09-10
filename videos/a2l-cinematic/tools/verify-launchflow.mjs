import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {chromium} from 'playwright';

const browser=await chromium.launch({channel:'chrome',headless:true});
const report={runtimeErrors:[],failedAssets:[],externalRequests:[],heroes:[],rasterDifferences:[]};
const revision=JSON.parse(await readFile('src/launchflow-cues.json','utf8')).exportPrefix;
try{
  const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
  page.on('pageerror',e=>report.runtimeErrors.push(e.message));
  page.on('response',r=>{if(r.status()>=400)report.failedAssets.push({url:r.url(),status:r.status()});});
  await page.route('**/*',route=>{
    const u=new URL(route.request().url());
    if(!['localhost','127.0.0.1'].includes(u.hostname)&&u.protocol!=='data:'){
      report.externalRequests.push(u.origin);return route.abort();
    }return route.continue();
  });
  await page.goto('http://localhost:3017/api/projects/a2l-cinematic/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player');
  await page.waitForFunction(()=>window.__a2lSeek&&document.fonts.status==='loaded');
  await page.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth>0));
  assert.equal(await page.evaluate(()=>typeof window.__a2lSeek(0)),'undefined');
  assert.equal(await page.evaluate(()=>window.__a2lTimeline.duration()),17.5);
  assert.equal(await page.locator('#local-vault,#connections,#composer,canvas').count(),0);
  assert.equal(await page.locator('audio').count(),3);
  assert.equal(await page.locator('.demo-note').count(),0,'The removed footer must not return to the film');
  assert.ok(!(await page.locator('#film').textContent()).includes('SETUP & RESPONSES TIME-COMPRESSED'),'The removed disclaimer cannot be moved elsewhere');
  // This is the preserved pre-rebrand option, not a live frontend dependency.
  // The website and active film share outlined A2L / Waterloo-gold artwork.
  const logo=await readFile('assets/brand/frontend-mark.svg');
  assert.equal(createHash('sha256').update(logo).digest('hex'),'ea3b7fdb9152b63cfadc7f0bd163ced1519d5562316b95c239f6955db9461483'); // pragma: allowlist secret -- preserved book-mark SHA-256
  const brands=JSON.parse(await readFile('src/brand-variant.json','utf8'));
  const variant=await page.locator('html').getAttribute('data-brand-variant');
  assert.ok(brands.variants[variant],'An explicit reversible local brand variant');
  for(const asset of Object.values(brands.variants))assert.equal(createHash('sha256').update(await readFile(asset.src)).digest('hex'),asset.sha256,'Neither preserved nor experimental artwork may drift');
  const active=brands.variants[variant],bytes=await readFile(active.src);
  const src=await page.locator('#brand-mark').getAttribute('src');
  assert.ok(src===active.src||src===`data:image/${active.src.endsWith('.png')?'png':'svg+xml'};base64,${bytes.toString('base64')}`);
  for(const [slot,selector]of [['header','.corner-monogram'],['context','.ingest-brand'],['footer','.footer-mark']]){
    const source=slot==='header'?active.src:(active.darkSrc??active.src);
    const path=source.replace(/(\.[^.]+)$/,`.${slot}$1`);
    assert.deepEqual(await readFile(path),await readFile(source),'Placement copies contain exactly the selected light/dark artwork bytes');
    const background=await page.locator(selector).evaluate(el=>getComputedStyle(el).backgroundImage);
    const inline=background.match(/data:image\/svg\+xml;base64,([^"]+)/);
    if(inline)assert.deepEqual(Buffer.from(inline[1],'base64'),await readFile(source),'Compiled SVG placements retain the exact selected artwork');
    else assert.ok(background.includes(path.split('/').at(-1)),'Every brand placement uses the selected variant');
  }
  if(variant==='waterloo-gold'){
    assert.equal(createHash('sha256').update(await readFile(active.darkSrc)).digest('hex'),active.darkSha256);
    for(const path of [active.src,active.darkSrc])assert.match(await readFile(path,'utf8'),/data-brand-accent="waterloo-gold" fill="#FFD54F"/);
    for(const selector of ['.corner-monogram','.ingest-brand','.footer-mark','#brand-mark'])assert.equal(await page.locator(selector).evaluate(el=>getComputedStyle(el).filter),'none','Keep the gold accent unchanged in every placement');
  }
  report.brandVariant=variant;
  assert.equal(await page.locator('#codex-banner strong').textContent(),'›_ Codex');
  assert.ok(!/Claude|feasible|guaranteed|LEARN deleted|available now/i.test(await page.locator('#film').textContent()));
  const cues=JSON.parse(await readFile('assets/cue-sheet.json','utf8'));
  const audio=JSON.parse(await readFile('audio_meta.json','utf8'));
  assert.equal(audio.duration,17.5);
  assert.equal(await page.locator('.chapter-step b').count(),0,'No numbered chapter labels');
  assert.equal(await page.locator('.chrome-tab,.omnibox,.learn-navbar,.editor-explorer,.editor-tabs').count(),5);
  const contentTab=await page.locator('.learn-navbar .current').evaluate(el=>{const s=getComputedStyle(el);return {color:s.color,left:s.borderLeftWidth,right:s.borderRightWidth,shadow:s.boxShadow,underline:s.backgroundImage,size:s.backgroundSize,position:s.backgroundPosition,repeat:s.backgroundRepeat};});
  assert.deepEqual(contentTab,{color:'rgb(7, 107, 171)',left:'0px',right:'0px',shadow:'none',underline:'linear-gradient(rgb(0, 116, 175), rgb(0, 116, 175))',size:'100% 3px',position:'0% 100%',repeat:'no-repeat'},'Content retains its blue text and bottom-only underline without a surrounding box');
  for(const label of await page.locator('.chapter-step').all()){
    const style=await label.evaluate(e=>{const s=getComputedStyle(e);return {size:parseFloat(s.fontSize),weight:Number(s.fontWeight),left:parseFloat(s.left)};});
    assert.ok(style.size>=32&&style.weight>=600&&style.left<1400,'Prominent dark chapter text closer to the centre');
    assert.ok(await label.locator('.chapter-glyph').count()>10,'Each label animates individual letters');
  }
  assert.equal(await page.locator('.demo-user').textContent(),'Demo student');
  assert.equal(await page.locator('.learn-course-title').textContent(),'CS 135 · Fall 2026');
  assert.match(await page.locator('.browser-demo').textContent(),/CS135-INSPIRED DEMO/);
  assert.equal(await page.locator('.information-bit').count(),36,'Fixed bounded information pool');
  const icons=await page.locator('.material-card .resource-icon svg').evaluateAll(es=>es.map(e=>({stroke:e.getAttribute('stroke'),fill:e.getAttribute('fill'),color:getComputedStyle(e).color,viewBox:e.getAttribute('viewBox')})));
  for(const icon of icons)assert.deepEqual(icon,{stroke:'currentColor',fill:'none',color:'rgb(37, 37, 37)',viewBox:'0 0 24 24'});
  assert.equal(await page.locator('.waterloo-wordmark').textContent(),'WATERLOOLEARN');
  for(const [time,id] of [[1,'chapter-install'],[5.4,'chapter-learn'],[8.05,'chapter-agent'],[14.5,'chapter-source']]){
    const fits=await page.evaluate(({time,id})=>{window.__a2lSeek(time);const mask=document.querySelector(`#${id} .chapter-step`).getBoundingClientRect();return [...document.querySelectorAll(`#${id} .chapter-glyph`)].every(e=>{const r=e.getBoundingClientRect();return r.left>=mask.left&&r.right<=mask.right&&r.top>=mask.top&&r.bottom<=mask.bottom;});},{time,id});
    assert.ok(fits,`${id} glyphs must fully fit the label mask at rest`);
    const titleFits=await page.evaluate(id=>{
      const title=document.querySelector(`#${id} h1`),label=document.querySelector(`#${id} .chapter-step`);
      const range=document.createRange();range.selectNodeContents(title);
      return range.getBoundingClientRect().right+24<=label.getBoundingClientRect().left;
    },id);
    assert.ok(titleFits,`${id} headline leaves a readable gap before its chapter label`);
  }
  for(const [time,id] of [[3.28,'chapter-learn'],[6.62,'chapter-agent'],[13.07,'chapter-source']]){
    const masked=await page.evaluate(({time,id})=>{window.__a2lSeek(time);const mask=document.querySelector(`#${id} .chapter-step`).getBoundingClientRect();return [...document.querySelectorAll(`#${id} .chapter-glyph`)].every(e=>e.getBoundingClientRect().top>=mask.bottom);},{time,id});
    assert.ok(masked,`${id} cannot flash its next phrase before the rolling entrance`);
  }
  for(const [i,id] of ['lecture-resource','lab-resource','dataset-resource'].entries()){
    assert.equal(await page.locator(`#receipt-${i} strong`).textContent(),await page.locator(`#${id} strong`).textContent(),'Every arriving document resolves to its own named source');
  }
  assert.equal(cues.typing[0].text,'uv tool install git+https://github.com/ManagementMO/agent2learn');
  assert.equal(await page.locator('#source-proof strong').textContent(),'Source opened at line 42.');
  assert.equal(await page.locator('.source-badge').textContent(),'Cited line 42');
  assert.equal(await page.locator('#source-keywords').textContent(),'prefix notation');
  for(const[time,selector]of[[15.93,'#brand-mark'],[15.93,'#wordmark'],[16.2,'#end-tagline'],[16.4,'#end-url']]){
    const hidden=await page.evaluate(({time,selector})=>{window.__a2lSeek(time);const s=getComputedStyle(document.querySelector(selector));return s.visibility==='hidden'||Number(s.opacity)===0;},{time,selector});
    assert.ok(hidden,`${selector} cannot flash before its intended entrance`);
  }
  const schedules=await page.evaluate(()=>window.__a2lTyping);
  for(const schedule of cues.typing){
    assert.deepEqual(schedules[schedule.selector],schedule);
    assert.deepEqual(audio.events.filter(e=>['recorded_key','clipboard_paste'].includes(e.kind)&&e.selector===schedule.selector).map(e=>e.time),schedule.rows.map(r=>r.time));
    for(const time of [schedule.start,schedule.start+schedule.duration/2,schedule.end+.01,schedule.start+.03]){
      const actual=await page.evaluate(({time,selector})=>{window.__a2lSeek(time);return document.querySelector(`${selector} .typed-text`).textContent;},{time,selector:schedule.selector});
      assert.equal(actual,schedule.text.slice(0,schedule.rows.filter(r=>r.time<=time+1e-5).at(-1)?.count??0));
    }
  }
  const state=()=>[...document.querySelectorAll('#film *')].map(e=>{
    const s=getComputedStyle(e),r=e.getBoundingClientRect();
    return {id:e.id,tag:e.tagName,text:e.children.length?null:e.textContent,box:[r.x,r.y,r.width,r.height],opacity:s.opacity,visibility:s.visibility,transform:s.transform,clip:s.clipPath,filter:s.filter,color:s.color,background:s.background,border:s.border,radius:s.borderRadius};
  });
  assert.equal(cues.typing[0].rows.length,1,'Installation is one clipboard paste');
  const question=cues.typing.find(x=>x.selector==='#question');
  const gaps=question.rows.slice(1).map((x,i)=>x.time-question.rows[i].time);
  assert.ok(Math.max(...gaps)/Math.min(...gaps)>2.5,'Question has non-robotic phrase pauses');
  assert.ok(new Set(gaps.map(x=>x.toFixed(4))).size>=gaps.length*.9,'Non-periodic cadence with varied intervals');
  for(const response of cues.response){
    for(const[offset,value]of response.chunks){
      await page.evaluate(t=>window.__a2lSeek(t),response.start+offset+.001);
      assert.equal(await page.locator(response.selector).textContent(),value,'Response streams whole token groups');
    }
  }
  const heroes=[[0,'install-window'],[1.7,'install-progress'],[2.85,'install-success'],[5.4,'lab-resource'],[6.3,'information-flow'],[7.5,'codex-banner'],[8.05,'context-ready'],[10.2,'question'],[12.1,'citation-chip'],[14.5,'source-proof'],[17.2,'end'],[17.491,'end']];
  const stored=new Map();await mkdir('.checks',{recursive:true});
  for(const[time,id]of heroes){
    await page.evaluate(t=>window.__a2lSeek(t),time);
    const visible=await page.evaluate(id=>{let e=document.getElementById(id),alpha=1;for(let p=e;p;p=p.parentElement)alpha*=Number(getComputedStyle(p).opacity);return getComputedStyle(e).visibility==='visible'&&alpha>.95;},id);
    assert.ok(visible,`${id} must be visible at ${time}`);
    const png=await page.screenshot({path:`.checks/${revision}-hero-${time}.png`});
    stored.set(time,{state:await page.evaluate(state),png:png.toString('base64'),hash:createHash('sha256').update(png).digest('hex')});
    report.heroes.push({time,id,visible});
  }
  for(const[time]of [...heroes].reverse()){
    await page.evaluate(t=>window.__a2lSeek(t),time);
    assert.deepEqual(await page.evaluate(state),stored.get(time).state,`Exact reverse-seek DOM state at ${time}`);
    const png=await page.screenshot();
    if(createHash('sha256').update(png).digest('hex')!==stored.get(time).hash){
      const delta=await page.evaluate(async({a,b})=>{
        async function decode(src){const i=new Image();i.src=`data:image/png;base64,${src}`;await i.decode();const c=document.createElement('canvas');c.width=1920;c.height=1080;const x=c.getContext('2d');x.drawImage(i,0,0);return x.getImageData(0,0,1920,1080).data;}
        const[p,q]=await Promise.all([decode(a),decode(b)]);let count=0,max=0;const coords=[];
        for(let i=0;i<p.length;i+=4){const d=Math.max(Math.abs(p[i]-q[i]),Math.abs(p[i+1]-q[i+1]),Math.abs(p[i+2]-q[i+2]));if(d){count++;max=Math.max(max,d);if(coords.length<40)coords.push([(i/4)%1920,Math.floor(i/4/1920),d]);}}
        return {count,max,coords};
      },{a:stored.get(time).png,b:png.toString('base64')});
      // Exact scene state is mandatory above. Only tiny rasterization variance
      // is allowed here; report coordinates for manual boundary inspection.
      const tinyPerspectiveRounding=time===6.3&&delta.count<=64&&delta.max===1;
      assert.ok((delta.count<=32&&delta.max<=16)||tinyPerspectiveRounding,`Raster mismatch ${time}: ${JSON.stringify(delta)}`);
      report.rasterDifferences.push({time,...delta});
    }
  }
  const excerpt=(await readFile('assets/demo/content/Week 1/Week 1.md','utf8')).split('\n');
  for(const[row,i]of(await page.locator('.code-line').allTextContents()).map((r,i)=>[r,i])){
    assert.equal(row.replace(new RegExp(`^${39+i}\\s*`),''),excerpt[38+i]);
  }
  report.clicks=[];
  for(const[time,target,cursor]of[[4.87,'#lab-resource','#learn-cursor'],[12.8,'#citation-chip','#agent-cursor']]){
    const hit=await page.evaluate(({time,target,cursor})=>{window.__a2lSeek(time);const a=document.querySelector(target).getBoundingClientRect(),b=document.querySelector(cursor).getBoundingClientRect();return b.left>=a.left&&b.left<a.right&&b.top>=a.top&&b.top<a.bottom;},{time,target,cursor});
    assert.ok(hit,`${cursor} must hit ${target}`);report.clicks.push({time,target,hit});
  }
  const layout=await page.evaluate(()=>{
    const collisions=[],overflow=[],handoff=[];
    const visible=e=>{for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.visibility==='hidden'||Number(s.opacity)<.02)return false;}return true;};
    const pairs=[['#demo-header','#scene-stage'],['.corner-monogram','#corner-brand>span:last-child'],['.ingest-brand','.ingest-heading strong'],['.ingest-heading strong','.ingest-heading>span:last-child'],['.source-path>span:first-child','.source-badge'],['#source-proof strong','#source-proof>.mono'],['#launch-line','#codex-banner'],['#codex-banner','#prompt-line'],['#codex-banner','#ingest-context'],['#ingest-context','#prompt-line'],['#prompt-line','#reading'],['#reading','#answer'],['#answer','#citation-chip'],['#citation-chip','#terminal-footer'],['#agent-window','#source-window'],['.source-code','#source-proof'],['#brand-mark','#wordmark'],['#wordmark','#end-tagline'],['#end-tagline','#end-url'],['.install-line','#install-success'],['#install-success','#init-line'],['#init-line','#setup-steps'],['#lecture-resource','#lab-resource'],['#lab-resource','#dataset-resource'],['.editor-explorer','#source-view']];
    const inside=(a,b)=>a.left>=b.left-.01&&a.right<=b.right+.01&&a.top>=b.top-.01&&a.bottom<=b.bottom+.01;
    for(let frame=0;frame<2100;frame++){
      const time=frame/120;window.__a2lSeek(time);
      for(const selectors of pairs){
        const es=selectors.map(s=>document.querySelector(s));if(es.some(e=>!visible(e)))continue;
        const[a,b]=es.map(e=>e.getBoundingClientRect());
        if(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top)collisions.push({time,selectors});
      }
      const stage=document.querySelector('#scene-stage').getBoundingClientRect();
      const targets=time<3.08?['#install-window']:time>=3.8&&time<5.62?['#learn-window','#sync-terminal']:time>=6.8&&time<12.92?['#agent-window']:time>=13.8&&time<15.65?['#agent-window','#source-window']:[];
      for(const selector of targets){const e=document.querySelector(selector);if(visible(e)&&!inside(e.getBoundingClientRect(),stage))overflow.push({time,selector});}
      if(time>=5.62&&time<6.75){
        const a=document.querySelector('#learn-window'),b=document.querySelector('#agent-window');
        if(visible(a)&&visible(b)){const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();if(ar.right>br.left)handoff.push({time,gap:br.left-ar.right});}
      }
    }
    window.__a2lSeek(5.4);const learnWidth=document.querySelector('#learn-window').getBoundingClientRect().width;
    window.__a2lSeek(6.3);const perspective=getComputedStyle(document.querySelector('#learn-window')).transform;
    window.__a2lSeek(6.8);const settled=getComputedStyle(document.querySelector('#workspace-rig')).transform;
    return {collisions,overflow,handoff,learnWidth,perspective,settled};
  });
  await writeFile(`.checks/${revision}-layout.json`,JSON.stringify(layout,null,2));
  assert.deepEqual(layout.collisions,[],'No unintended text/panel/card collision at 120 fps');
  assert.deepEqual(layout.overflow,[],'Resting product panels remain within stage');
  assert.deepEqual(layout.handoff,[],'LEARN and terminal shells never collide during handoff');
  assert.ok(layout.learnWidth>=1300);
  assert.match(layout.perspective,/matrix3d/,'Handoff must use true perspective');
  assert.equal(await page.locator('#lecture-resource').count(),1,'Same lecture object, never cloned');
  assert.deepEqual(report.runtimeErrors,[]);assert.deepEqual(report.failedAssets,[]);assert.deepEqual(report.externalRequests,[]);
  // Check the actual dot trajectories frame by frame, including disappearance
  // after absorption and exact reverse seeks. Not merely a visible parent box.
  const particles=await page.evaluate(()=>{
    const nodes=[...document.querySelectorAll('.information-bit')],samples=[];
    for(let frame=660;frame<=948;frame++){
      window.__a2lSeek(frame/120);
      samples.push(nodes.map(e=>{const r=e.getBoundingClientRect();return [r.x,r.y,Number(getComputedStyle(e).opacity)];}));
    }
    return samples;
  });
  assert.ok(particles.some(row=>row.filter(p=>p[2]>.5).length>=24),'At least 24 information points in the visible flow');
  assert.ok(particles[0].every(p=>p[2]===0)&&particles.at(-1).every(p=>p[2]===0),'No particles before or after ingestion');
  let moving=0,maxStep=0;
  for(let f=1;f<particles.length;f++)for(let i=0;i<36;i++){
    const a=particles[f-1][i],b=particles[f][i];
    if(a[2]>.05&&b[2]>.05){const d=Math.hypot(a[0]-b[0],a[1]-b[1]);maxStep=Math.max(maxStep,d);if(d>.1)moving++;}
  }
  assert.ok(moving>3500&&maxStep<18,'Continuous trajectories at 120 fps, no positional jumps');
  const absorption=await page.evaluate(()=>window.__a2lParticles.map(p=>{
    const node=document.getElementById(p.id),tail=[];
    for(let f=0;f<=31;f++){
      window.__a2lSeek(p.end-p.settle+f*p.settle/31);
      tail.push({opacity:Number(getComputedStyle(node).opacity),scale:Number(gsap.getProperty(node,'scaleX'))});
    }
    const end=node.getBoundingClientRect(),icon=document.querySelector(`${p.receipt}>span:first-child`).getBoundingClientRect();
    return {...p,tail,distance:Math.hypot(end.x+end.width/2-icon.x-icon.width/2,end.y+end.height/2-icon.y-icon.height/2),receiptOpacity:Number(getComputedStyle(document.querySelector(p.receipt)).opacity)};
  }));
  for(const p of absorption){
    assert.ok(p.settle*120>=31,'Absorption has at least 31 native frames, previously about 17');
    assert.ok(p.end<=7.60001&&p.start>=5.65,'Slightly faster flow within the approved handoff');
    assert.ok(p.distance<.25&&p.receiptOpacity>.95,`Each point lands at its visible source icon centre: ${p.id} distance ${p.distance}`);
    assert.ok(p.tail[0].opacity>.9&&p.tail.at(-1).opacity===0&&p.tail.at(-1).scale<=.04);
    for(let i=1;i<p.tail.length;i++)assert.ok(p.tail[i].opacity<=p.tail[i-1].opacity&&p.tail[i].scale<=p.tail[i-1].scale,'Absorption tapers monotonically without a flash or size pop');
  }
  report.particles={count:36,movingSamples:moving,maxStep,absorptionFrames:31,maxLandingError:Math.max(...absorption.map(p=>p.distance)),lastArrival:Math.max(...absorption.map(p=>p.end))};
  report.status='passed';report.layoutFrames=2100;report.sourceLines=[39,44];report.typingAudioEvents=cues.typing.reduce((n,x)=>n+x.rows.length,0);report.exactDomSeeks=heroes.length;report.exactPixelSeeks=heroes.length-report.rasterDifferences.length;report.learnWidth=layout.learnWidth;
  await writeFile(`.checks/${revision}-behavior.json`,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
}finally{await browser.close();}
