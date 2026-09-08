import { mkdir, cp, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

await mkdir('assets/fonts', {recursive:true});
await cp('node_modules/gsap/dist/gsap.min.js','assets/gsap.min.js');
await cp('node_modules/gsap/dist/MotionPathPlugin.min.js','assets/MotionPathPlugin.min.js');
await cp('node_modules/gsap/dist/CustomEase.min.js','assets/CustomEase.min.js');
await cp('node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2','assets/fonts/geist.woff2');
await cp('node_modules/@fontsource/geist-mono/files/geist-mono-latin-400-normal.woff2','assets/fonts/geist-mono.woff2');
await cp('node_modules/@fontsource/geist-mono/files/geist-mono-latin-500-normal.woff2','assets/fonts/geist-mono-medium.woff2');
const template=await readFile('src/launchflow.html.template','utf8');
const icons=await readFile('src/icons.svg','utf8');
const motion=await readFile('src/launchflow-motion.js','utf8');
// Keep the explanatory source module fully commented; the generated inline
// bundle omits standalone development comments, as a normal build artifact.
const compiledMotion=motion.replace(/^\s*\/\/[^\n]*\n/gm,'');
const cues=JSON.parse(await readFile('src/launchflow-cues.json','utf8'));
// A local film variant, never a mutation of the real frontend identity. One
// build flag restores the book mark while preserving all motion refinements.
const brands=JSON.parse(await readFile('src/brand-variant.json','utf8'));
const variant=process.argv.find(x=>x.startsWith('--brand='))?.slice(8)??brands.active;
const brand=brands.variants[variant];
if(!brand)throw new Error(`Unknown brand variant: ${variant}`);
if(createHash('sha256').update(await readFile(brand.src)).digest('hex')!==brand.sha256)throw new Error('Brand asset drift');
// Byte-identical placement copies isolate Chromium's resized-image cache.
// Sharing the closing raster with the tiny header changed 1,084 edge pixels
// after a backwards seek. Separate resources preserve the original PNG while
// keeping each placement's decode stable. No image resampling or redrawing.
const brandPlacements={};
for(const slot of ['header','context','footer']){
  brandPlacements[slot]=brand.src.replace(/(\.[^.]+)$/,`.${slot}$1`);
  await cp(brand.src,brandPlacements[slot]);
}
// A single baked schedule drives pixels AND Foley. Human input has word-level
// pauses, a pasted install command, and non-repeating key intervals; model
// output has separate token chunks and never makes fake keyboard noises.
for(const item of cues.typing){
  if(item.mode==='paste'){
    item.rows=[{time:item.start+item.duration,count:item.text.length,kind:'paste'}];
  }else{
    const delays=Array.from(item.text,(c,i)=>{
      const seed=Math.sin((i+1)*17.17+item.text.length*3.1)*19493.7;
      const natural=.028+(seed-Math.floor(seed))*.04;
      const prefix=item.text.slice(0,i).trimEnd();
      return natural+(c===' '?(item.pausesAfter?.[prefix]??.024):0);
    });
    const total=delays.reduce((a,b)=>a+b,0);let elapsed=0;
    item.rows=delays.map((w,i)=>({time:item.start+(elapsed+=w)/total*item.duration,count:i+1,kind:'key'}));
  }
  item.end=item.start+item.duration;
}
await writeFile('assets/cue-sheet.json',JSON.stringify(cues,null,2)+'\n');
const escapeAttribute=s=>s.replaceAll('&','&amp;').replaceAll('"','&quot;');
const automation={version:1,lanes:[{target:'volume',points:cues.musicEnvelope.map(([t,v])=>({t,v}))}]};
const iconViewBoxes={pdf:'0 0 64 80',lab:'0 0 64 80',csv:'0 0 64 80',outline:'0 0 64 80',markdown:'0 0 64 80',agent:'0 0 32 32',folder:'0 0 32 28',index:'0 0 32 32','arrow-up-right':'0 0 24 24','arrow-right':'0 0 24 24','arrow-up':'0 0 24 24'};
const monoIcons={};
for(const id of ['file-text','notebook-text','terminal']){
  const svg=await readFile(`assets/icons/${id}.svg`,'utf8');
  if(!svg.includes('viewBox="0 0 24 24"')||!svg.includes('stroke="currentColor"'))throw new Error('Unexpected Lucide icon geometry');
  monoIcons[id]=svg.replace(/\s*\n\s*/g,' ').replace('<svg','<svg class="a2l-icon mono-icon" aria-hidden="true"');
}
const html=template.replaceAll('{{brandVariant}}',variant).replaceAll('{{brandSrc}}',brand.src).replace(/\{\{brand:(header|context|footer)\}\}/g,(_,slot)=>brandPlacements[slot]).replaceAll('{{brandAlt}}',escapeAttribute(brand.alt)).replaceAll('{{audioPrefix}}',cues.audioPrefix).replace('<!-- A2L_ICON_SPRITE -->',icons).replace('<!-- A2L_CUES -->',`<script>window.__A2L_CUES=${JSON.stringify(cues)};</script>`).replace('{{musicAutomation}}',escapeAttribute(JSON.stringify(automation))).replace('<!-- A2L_MOTION -->',`<script>${compiledMotion}</script>`).replace(/\{\{icon:([a-z-]+)\}\}/g,(_,id)=>{
  if(monoIcons[id])return monoIcons[id];
  if(!iconViewBoxes[id])throw new Error(`Unknown icon: ${id}`);
  return `<svg class="a2l-icon a2l-icon--${id}" viewBox="${iconViewBoxes[id]}" aria-hidden="true"><use href="#icon-${id}"></use></svg>`;
});
await writeFile('index.html',html);
await writeFile('white.css',(await readFile('src/showcase.css','utf8'))+'\n'+(await readFile('src/codex.css','utf8'))+'\n'+(await readFile('src/launchflow.css','utf8')));
// This authored fixture is the exact file shown by the cinematic source reveal.
// Generating its structural padding keeps the human-written excerpt on line 145.
const body = ['# Lecture 06 — Feasibility','', '> Synthetic demo material, written for the Agent2Learn launch film.',''];
for(let section=1;section<=20;section++) {
  body.push(`## Example ${section}`, '', 'Define the decision variables before writing the model.',
    'Record each constraint and its units.', 'Separate feasibility from the objective.', '', '<!-- demo spacer -->');
}
if(body.length!==144) throw new Error('Synthetic citation padding changed');
body[141]='## Feasibility';body[142]='';body[143]='Define the decision variables first.';
body.push('A feasible solution satisfies every constraint.',
  'The objective ranks feasible solutions.',
  'Check each constraint against your values.',
  '', 'This material is fictional and is not part of any real course.');
await mkdir('assets/demo/content/Week 3',{recursive:true});
await writeFile('assets/demo/content/Week 3/Lecture 06.md',body.join('\n')+'\n');
const source=await readFile('assets/demo/content/Week 3/Lecture 06.md','utf8');
if(source.split('\n')[144]!=='A feasible solution satisfies every constraint.') throw new Error('Citation mismatch');
const lab=Array(44).fill('');
lab[0]='# Lab 4 — Querying real data';
lab[2]='> Synthetic demo material authored for the Agent2Learn launch film.';
lab[4]='Use the fictional practice tables to explore SQL queries.';
lab[6]='No real student, instructor, course, grades or assignment is represented.';
lab.splice(38,6,'## Before Lab 4','','Review Lecture 06 before the lab.','Focus on JOINs and GROUP BY.','Practice with the provided lab dataset.','Bring one query you want to discuss.');
await mkdir('assets/demo/content/Labs',{recursive:true});
await writeFile('assets/demo/content/Labs/Lab 4.md',lab.join('\n')+'\n');
if(lab[41]!=='Focus on JOINs and GROUP BY.')throw new Error('Lab 4 citation mismatch');
const week=Array(44).fill('');
week[0]='# Week 1 — CS135-inspired study notes';
week[2]='> Original synthetic demo content. Not official CS135 teaching material.';
week[4]='Public course references establish the subject only; this note is authored for the film.';
week[6]='No private LEARN session, student, instructor or assessment is represented.';
week.splice(38,6,'## Week 1 review','','Start with values and expressions.','Use prefix notation in Racket.','Then review function definitions.','Trace each expression one step at a time.');
await mkdir('assets/demo/content/Week 1',{recursive:true});
await writeFile('assets/demo/content/Week 1/Week 1.md',week.join('\n')+'\n');
if(week[41]!=='Use prefix notation in Racket.')throw new Error('Week 1 citation mismatch');
console.log(`Built 17.5s Signalflow Polish: smoother absorption, exact source emphasis, ${variant} brand variant.`);
