import {mkdir} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {chromium} from 'playwright';

// Capture the CURRENT composition, never an older MP4. Public stills contain
// only the authored synthetic picture; no audio or private course material.
const dir='.checks/brand-review';
await mkdir(dir,{recursive:true});
await mkdir('renders',{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
  const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
  await page.goto('http://localhost:3017/api/projects/a2l-cinematic/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player');
  await page.waitForFunction(()=>window.__a2lSeek&&document.fonts.status==='loaded'&&[...document.images].every(i=>i.complete&&i.naturalWidth));
  const capture=async(time,path)=>{
    await page.evaluate(t=>window.__a2lSeek(t),time);
    await page.screenshot({path});
  };
  await capture(14.5,'renders/signalflow-agent-poster.png');
  const heroes=[1.0,1.7,2.85,5.4,6.3,7.5,8.05,10.2,12.1,14.5,16.5,17.2];
  for(const [i,time]of heroes.entries())await capture(time,`${dir}/story-${String(i).padStart(2,'0')}.png`);
  for(let i=0;i<36;i++)await capture(5.68+i*(8.05-5.68)/35,`${dir}/ingest-${String(i).padStart(2,'0')}.png`);
}finally{await browser.close();}
for(const [kind,scale,grid,output]of[
  ['story',480,'3x4','signalflow-agent-storyboard.jpg'],
  ['ingest',320,'6x6','signalflow-agent-ingestion-review.jpg'],
]){
  execFileSync('ffmpeg',['-hide_banner','-loglevel','error','-y','-i',`${dir}/${kind}-%02d.png`,'-vf',`scale=${scale}:-1,tile=${grid}`,'-frames:v','1','-q:v','2',`renders/${output}`]);
}
console.log('Refreshed current-composition poster, 12-frame storyboard and 36-frame ingestion sheet. MP4s untouched.');
