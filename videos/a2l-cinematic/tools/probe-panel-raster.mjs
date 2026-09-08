import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
const browser=await chromium.launch({channel:'chrome',headless:true}),results=[];
try{
  for(const [name,css]of Object.entries({noPromotion:'.information-bit{will-change:auto}'})){
    const page=await browser.newPage({viewport:{width:1920,height:1080}});
    await page.goto('http://localhost:3017/api/projects/a2l-cinematic/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player');
    await page.waitForFunction(()=>window.__a2lSeek&&document.fonts.status==='loaded');
    if(css)await page.addStyleTag({content:css});
    const images=[];
    for(const t of [0,1.7,2.85,5.4,6.3,7.5,8.05,10.2,12.1,14.5,17.2,17.491,17.491,17.2,14.5,12.1,10.2,8.05,7.5,6.3]){
      await page.evaluate(t=>window.__a2lSeek(t),t);
      const shot=await page.screenshot();
      if(t===6.3)images.push(shot.toString('base64'));
    }
    const diff=await page.evaluate(async([a,b])=>{
      async function decode(src){const i=new Image();i.src=`data:image/png;base64,${src}`;await i.decode();const c=document.createElement('canvas');c.width=1920;c.height=1080;const x=c.getContext('2d');x.drawImage(i,0,0);return x.getImageData(0,0,1920,1080).data;}
      const[p,q]=await Promise.all([decode(a),decode(b)]);let count=0,max=0;const regions={},histogram={};
      for(let i=0;i<p.length;i+=4){const d=Math.max(Math.abs(p[i]-q[i]),Math.abs(p[i+1]-q[i+1]),Math.abs(p[i+2]-q[i+2]));if(d){count++;histogram[d]=(histogram[d]||0)+1;max=Math.max(max,d);const x=(i/4)%1920,y=Math.floor(i/4/1920),key=`${Math.floor(x/100)*100},${Math.floor(y/100)*100}`;regions[key]=(regions[key]||0)+1;}}
      return {count,max,regions,histogram};
    },images);
    results.push({name,...diff});console.log(JSON.stringify(results.at(-1)));await page.close();
  }
}finally{await browser.close();}
await writeFile('.checks/signalflow-particle-layer-probe.json',JSON.stringify(results,null,2));
