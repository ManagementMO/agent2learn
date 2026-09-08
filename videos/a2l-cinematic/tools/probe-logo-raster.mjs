// Read-only runtime experiment: isolate whether shared raster decode caching
// changes the small logo after the larger closing placement has been painted.
import {chromium} from 'playwright';
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
  for(const unique of [false,true]){
    const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
    await page.goto('http://localhost:3017/api/projects/a2l-cinematic/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player');
    await page.waitForFunction(()=>window.__a2lSeek&&document.fonts.status==='loaded'&&[...document.images].every(i=>i.complete));
    await page.evaluate(unique=>{
      for(const [i,selector]of ['.corner-monogram','.ingest-brand','.footer-mark'].entries()){
        const e=document.querySelector(selector),src=document.querySelector('#brand-mark').src;
        if(!unique)e.style.backgroundImage=`url("${src}")`;
      }
    },unique);
    // Allow actual paint before acquiring either comparison, not just DOM.
    await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
    await page.evaluate(()=>window.__a2lSeek(14.5));
    const a=(await page.screenshot()).toString('base64');
    await page.evaluate(()=>window.__a2lSeek(17.2));await page.screenshot();
    await page.evaluate(()=>window.__a2lSeek(14.5));
    const b=(await page.screenshot()).toString('base64');
    const delta=await page.evaluate(async({a,b})=>{
      const decode=async png=>{const image=new Image();image.src=`data:image/png;base64,${png}`;await image.decode();const c=document.createElement('canvas');c.width=1920;c.height=1080;const x=c.getContext('2d');x.drawImage(image,0,0);return x.getImageData(0,0,1920,1080).data;};
      const [p,q]=await Promise.all([decode(a),decode(b)]);let count=0,max=0;const regions={header:0,footer:0,other:0};
      for(let i=0;i<p.length;i+=4){const d=Math.max(...[0,1,2].map(k=>Math.abs(p[i+k]-q[i+k])));if(d){count++;max=Math.max(max,d);const y=Math.floor(i/4/1920);regions[y<100?'header':y>800&&y<850?'footer':'other']++;}}
      return {count,max,regions};
    },{a,b});
    const landing=await page.evaluate(()=>window.__a2lParticles.filter(p=>p.id.endsWith('-0')).map(p=>{
      window.__a2lSeek(p.end);
      const a=document.getElementById(p.id).getBoundingClientRect(),b=document.querySelector(`${p.receipt}>span:first-child`).getBoundingClientRect();
      return {id:p.id,deltaX:a.x+a.width/2-b.x-b.width/2,deltaY:a.y+a.height/2-b.y-b.height/2,opacity:getComputedStyle(document.querySelector(p.receipt)).opacity};
    }));
    console.log(JSON.stringify({unique,delta,landing}));await page.close();
  }
}finally{await browser.close();}
