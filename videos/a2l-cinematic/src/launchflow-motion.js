/* global gsap, MotionPathPlugin, CustomEase */
window.__initA2LAnimation=()=>{
  gsap.registerPlugin(MotionPathPlugin,CustomEase);
  gsap.config({force3D:false});
  // One continuous velocity curve: brisk middle travel, then a long, soft
  // deceleration. No split motion-path tween or abrupt handoff at the landing.
  CustomEase.create('sourceFlow','0.32,0,0.32,1');
  const cues=window.__A2L_CUES,A=cues.actions;
  const tl=gsap.timeline({paused:true,defaults:{ease:'power3.out'}});
  const hidden='#chapter-learn,#chapter-agent,#chapter-source,#learn-window,.material-card,#sync-terminal,#sync-complete,#workspace-rig,#source-window,#codex-banner,#prompt-line,#reading,#answer,#citation-chip,#source-proof,#learn-cursor,#agent-cursor,#click-ring,#end,#end-tagline,#end-url,#wordmark,#install-progress,#install-success,#init-line,#setup-steps,#ingest-context,.ingest-file,#context-ready';
  gsap.set(hidden,{autoAlpha:0});gsap.set('#showcase,#chapter-install,#install-window',{autoAlpha:1});
  gsap.set('#workspace-rig',{x:1940,y:10,scale:1.12,rotationY:12,z:-140,transformOrigin:'0 0',force3D:false});
  function appear(target,at,duration=.2,from={y:8}){
    // Static terminal text only changes opacity. Even an identity transform can
    // create a separately rasterized layer after the shared camera pulls back.
    if(Object.entries(from).every(([key,value])=>value===(key==='scale'?1:0))){
      tl.fromTo(target,{autoAlpha:0},{autoAlpha:1,duration,immediateRender:false},at);return;
    }
    tl.fromTo(target,{autoAlpha:0,...from},{autoAlpha:1,x:0,y:0,scale:1,duration,immediateRender:false},at);
  }
  // Split once, synchronously. The masks and absolute-time letter tweens make
  // this a reversible typographic roll, not wall-clock DOM replacement.
  document.querySelectorAll('.chapter-step').forEach(label=>{
    const copy=label.textContent;label.setAttribute('aria-label',copy);label.textContent='';
    // Only these glyphs deliberately cross their 66px mask during a roll.
    // Overlap/occlusion checks remain enabled, including between old/new words.
    for(const character of copy){const span=document.createElement('span');span.className='chapter-glyph';span.textContent=character;span.setAttribute('aria-hidden','true');span.setAttribute('data-layout-allow-overflow','');label.append(span);}
  });
  gsap.set('.chapter:not(#chapter-install) .chapter-glyph',{y:68});
  function chapter(old,next,at){
    tl.fromTo(`${old} h1,${old} p`,{autoAlpha:1,y:0},{autoAlpha:0,y:-12,duration:.16,immediateRender:false},at);
    tl.fromTo(`${old} .chapter-glyph`,{y:0},{y:-68,duration:.18,stagger:.008,ease:'power3.in',immediateRender:false},at);
    tl.set(next,{autoAlpha:1},at+.18);
    tl.fromTo(`${next} h1,${next} p`,{autoAlpha:0,y:14},{autoAlpha:1,y:0,duration:.29,stagger:.035,ease:'power2.out',immediateRender:false},at+.18);
    tl.fromTo(`${next} .chapter-glyph`,{y:68},{y:0,duration:.35,stagger:.012,ease:'power4.out',immediateRender:false},at+.34);
    tl.set(old,{autoAlpha:0},at+.33);
  }
  tl.fromTo('#chapter-install .chapter-glyph',{y:68},{y:0,duration:.46,stagger:.018,ease:'power4.out',immediateRender:false},.12);
  const typeSchedules={};
  for(const schedule of cues.typing){
    const el=document.querySelector(schedule.selector),text=document.createElement('span'),caret=document.createElement('span');
    text.className='typed-text';caret.className='type-caret';caret.setAttribute('aria-hidden','true');el.append(text,caret);
    const driver={time:0};const render=()=>{
      let n=0,last=schedule.start;
      for(const row of schedule.rows){if(driver.time+1e-5>=row.time){n=row.count;last=row.time;}else break;}
      text.textContent=schedule.text.slice(0,n);
      // Steady while keys arrive; blink only during a real pause. A thin caret
      // stays attached to the glyph baseline instead of bobbing like a block.
      const active=driver.time>=schedule.start&&driver.time<schedule.hideCaret;
      const recent=driver.time-last<.23;
      caret.style.opacity=active&&(recent||((driver.time-last)% .8)<.49)?'1':'0';
    };
    tl.to(driver,{time:cues.duration,duration:cues.duration,ease:'none',onUpdate:render},0);render();typeSchedules[schedule.selector]=schedule;
  }
  window.__a2lTyping=typeSchedules;
  for(const response of cues.response){
    const element=document.querySelector(response.selector),driver={time:0};
    const render=()=>{let text='';for(const[offset,value]of response.chunks){if(driver.time>=response.start+offset-1e-5)text=value;else break;}element.textContent=text;};
    tl.to(driver,{time:cues.duration,duration:cues.duration,ease:'none',onUpdate:render},0);render();
  }
  // Installation is explicitly a time-compressed source install, not a claim
  // that an unpublished PyPI package or silent sign-in magically exists.
  tl.fromTo('#install-window',{y:20,scale:.985},{y:0,scale:1,duration:.48,force3D:false,immediateRender:false},0);
  appear('#install-progress',1.54,.1,{y:0});
  tl.fromTo('.install-progress-track i',{scaleX:0},{scaleX:1,duration:.41,ease:'power2.inOut',immediateRender:false},1.55);
  tl.fromTo('#install-progress',{autoAlpha:1},{autoAlpha:0,duration:.07,immediateRender:false},1.96);
  appear('#install-success',A.installDone,.14,{y:0});appear('#init-line',2.1,.1,{y:0});appear('#setup-steps',2.6,.2,{y:7});
  chapter('#chapter-install','#chapter-learn',3.08);
  tl.fromTo('#install-window',{y:0,scale:1,autoAlpha:1},{y:-34,scale:.97,autoAlpha:0,duration:.24,force3D:false,immediateRender:false},3.1);
  tl.fromTo('#learn-window',{y:44,autoAlpha:0},{y:0,autoAlpha:1,duration:.43,force3D:false,immediateRender:false},3.35);

  const particleSchedules=[];
  const materials=[['#lecture-resource',374],['#lab-resource',484],['#dataset-resource',594]];
  materials.forEach(([selector,y],i)=>{
    gsap.set(selector,{x:598,y,scale:1,rotationY:0,rotationZ:0});
    tl.fromTo(selector,{x:620,y:y+13,autoAlpha:0},{x:598,y,autoAlpha:1,duration:.31,immediateRender:false},3.52+i*.065);
    // Row -> information -> named receipt. The document's text region seeds
    // its own stream; no unbounded emitter or decorative confetti is involved.
    const at=5.65+i*.055;
    tl.fromTo(selector,{x:598,y,scale:1,rotationY:0,rotationZ:0,z:0,autoAlpha:1},
      {x:552,y:y-10,scale:.98,autoAlpha:0,duration:.4,ease:'power2.out',immediateRender:false},at);
    tl.fromTo(`${selector}>div,${selector}>.resource-icon`,{clipPath:'inset(0 0 0 0)'},{clipPath:'inset(0 0 0 100%)',duration:.32,ease:'sine.inOut',immediateRender:false},at+.025);
    tl.set(selector,{autoAlpha:0},at+.4);
    const arrival=A[`sourceArrival${i}`];
    tl.fromTo(`#receipt-${i}`,{autoAlpha:0,clipPath:'inset(0 0 0 8px)'},{autoAlpha:1,clipPath:'inset(0 0 0 0px)',duration:.34,ease:'power2.out',immediateRender:false},arrival-.24);
    // A small, finite response belongs to the receiving icon. It makes the
    // destination feel absorbent without adding another panel or a lightshow.
    const halo=document.createElement('span');halo.className='receipt-energy';halo.setAttribute('aria-hidden','true');
    document.getElementById('receipt-'+i).firstElementChild.append(halo);
    gsap.set(halo,{opacity:0,scale:.7});
    tl.fromTo(halo,{opacity:0,scale:.7},{opacity:.4,scale:1,duration:.16,ease:'sine.out',immediateRender:false},arrival-.16);
    tl.to(halo,{opacity:0,scale:1.22,duration:.32,ease:'sine.out'},arrival);
    for(let k=0;k<12;k++){
      const bit=document.createElement('span');bit.className='information-bit';bit.id=`bit-${i}-${k}`;bit.dataset.source=selector;bit.dataset.receipt=`#receipt-${i}`;
      document.querySelector('#information-flow').append(bit);
      const x=706+(k%6)*79,y0=y+32+Math.floor(k/6)*26;
      // Particle coordinates describe a 7px box; subtract its centre offset
      // so the shrinking point ends on the receiving SVG's actual centre.
      const start=at+.06+k*.014,end=arrival+.04*(k%3),targetX=458.66,targetY=382.26+i*60.48;
      const bend=(k%4-1.5)*24;
      const size=.62+(k%5)*.12;
      const settle=.26;
      particleSchedules.push({id:bit.id,receipt:`#receipt-${i}`,start,end,settle,targetX,targetY});
      gsap.set(bit,{x,y:y0,scale:size,opacity:0});
      tl.fromTo(bit,{x,y:y0},{motionPath:{path:[{x,y:y0},{x:x+82,y:y0-26-bend},{x:582,y:targetY-36+bend},{x:targetX,y:targetY}],type:'cubic',autoRotate:false},duration:end-start,ease:'sourceFlow',immediateRender:false},start);
      tl.fromTo(bit,{scale:size},{scale:.38,duration:end-start-settle,ease:'sine.inOut',immediateRender:false},start);
      tl.fromTo(bit,{scale:.38},{scale:.04,duration:settle,ease:'sine.inOut',immediateRender:false},end-settle);
      tl.fromTo(bit,{opacity:0},{opacity:.92,duration:.2,ease:'sine.out',immediateRender:false},start);
      tl.fromTo(bit,{backgroundColor:'#4c5148'},{backgroundColor:'#c9c3b3',duration:.32,ease:'sine.inOut',immediateRender:false},6.12+i*.04);
      tl.fromTo(bit,{opacity:.92},{opacity:0,duration:settle,ease:'sine.inOut',immediateRender:false},end-settle);
    }
  });
  window.__a2lParticles=particleSchedules;
  tl.fromTo('#learn-cursor',{x:1480,y:650,autoAlpha:0},{x:1230,y:527,autoAlpha:1,duration:.46,ease:'power2.inOut',immediateRender:false},4.4);
  tl.fromTo('#lab-resource',{backgroundColor:'#fff',borderColor:'#d9dbd5'},{backgroundColor:'#f0f2ee',borderColor:'#7c8674',duration:.16,immediateRender:false},A.selectCourse-.035);
  tl.fromTo('#learn-cursor',{scale:1},{scale:.85,duration:.065,repeat:1,yoyo:true,immediateRender:false},A.selectCourse);
  tl.to('#learn-cursor',{autoAlpha:0,duration:.12},5.12);
  appear('#sync-terminal',4.82,.15,{y:8});appear('#sync-complete',A.syncComplete,.13,{y:0});
  // Retract the status strip as an opaque surface; fading its background under
  // pale terminal glyphs briefly washes the text into the light stage.
  tl.fromTo('#sync-terminal',{clipPath:'inset(0% 0 0 0)'},{clipPath:'inset(100% 0 0 0)',duration:.13,ease:'power2.inOut',immediateRender:false},5.6);
  tl.set('#sync-terminal',{autoAlpha:0},5.73);
  chapter('#chapter-learn','#chapter-agent',6.42);
  // True perspective motion, adapted from the registry's tilt-card primitive.
  // A shared camera and a large lateral separation keep the two shells apart.
  tl.fromTo('#learn-window',{x:0,y:0,z:0,rotationY:0,rotationZ:0,autoAlpha:1},
    {x:-1950,y:-40,z:-190,rotationY:-23,rotationZ:-4,autoAlpha:1,duration:1.12,ease:'power3.inOut',immediateRender:false},5.62);
  tl.set('#learn-window',{autoAlpha:0},6.74);
  tl.fromTo('#workspace-rig',{x:1940,y:10,scale:1.12,rotationY:12,z:-140,autoAlpha:1},
    {x:377.6,y:10,scale:1.12,rotationY:0,z:0,autoAlpha:1,duration:1.12,ease:'power3.inOut',immediateRender:false},5.62);
  appear('#codex-banner',6.88,.18,{y:0});
  appear('#ingest-context',6.9,.24,{y:0});
  appear('#context-ready',A.contextReady,.2,{y:6});
  tl.fromTo('#ingest-context',{autoAlpha:1,clipPath:'inset(0% 0 0 0)'},{autoAlpha:0,clipPath:'inset(100% 0 0 0)',duration:.27,ease:'power2.in',immediateRender:false},8.16);
  appear('#prompt-line',8.49,.15,{y:0});
  tl.fromTo('#enter-key',{backgroundColor:'#30342d',scale:1},{backgroundColor:'#565d4e',scale:.87,duration:.065,yoyo:true,repeat:1,immediateRender:false},A.questionEnter);
  tl.to('#enter-key',{opacity:0,duration:.13},10.46);
  appear('#reading',A.read,.16,{y:0});tl.set('#answer',{autoAlpha:1},A.answerStart);
  appear('#citation-chip',A.citation,.18,{y:0});
  tl.fromTo('#agent-cursor',{x:595,y:566,autoAlpha:0,scale:1},{x:243,y:555,autoAlpha:1,scale:1,duration:.36,ease:'power2.inOut',immediateRender:false},12.3);
  tl.fromTo('#click-ring',{x:230,y:542,scale:.35,autoAlpha:.7},{x:230,y:542,scale:1.3,autoAlpha:0,duration:.25,immediateRender:false},A.openSource);
  tl.fromTo('#agent-cursor',{scale:1},{scale:.85,duration:.065,repeat:1,yoyo:true,immediateRender:false},A.openSource);
  tl.to('#agent-cursor',{autoAlpha:0,duration:.12},12.95);
  chapter('#chapter-agent','#chapter-source',12.85);
  // A spatial pull-back reveals a neighboring editor instead of swapping the
  // terminal for an unrelated shot. The answer and its proof remain together.
  tl.fromTo('#workspace-rig',{x:377.6,y:10,scale:1.12},{x:42.85,y:65,scale:.83,duration:.8,ease:'power3.inOut',force3D:false,immediateRender:false},12.92);
  tl.fromTo('#agent-window',{y:0,scale:1},{y:80,scale:.88,duration:.8,ease:'power3.inOut',force3D:false,immediateRender:false},12.92);
  tl.fromTo('#source-window',{x:80,autoAlpha:0,clipPath:'inset(0 100% 0 0 round 26px)'},{x:0,autoAlpha:1,clipPath:'inset(0 0% 0 0 round 26px)',duration:.58,ease:'power2.inOut',immediateRender:false},13.14);
  tl.fromTo('#source-highlight',{backgroundColor:'#fffefb'},{backgroundColor:'#f8e9c9',duration:.33,immediateRender:false},A.highlight);
  tl.fromTo('#source-keywords',{'--source-emphasis':0},{'--source-emphasis':1,duration:.36,ease:'power2.out',immediateRender:false},A.highlight+.17);
  appear('#source-proof',A.proof,.2,{y:5});
  tl.fromTo('#showcase',{autoAlpha:1},{autoAlpha:0,duration:.24,immediateRender:false},A.outro);
  tl.set('#end',{autoAlpha:1},15.91);
  gsap.set('#brand-mark',{opacity:0});
  tl.fromTo('#brand-mark',{scale:.9,y:12,opacity:0},{scale:1,y:0,opacity:1,duration:.32,immediateRender:false},15.95);
  gsap.set('#wordmark',{clipPath:'inset(100% 0 0 0)'});
  tl.set('#wordmark',{autoAlpha:1},16.1);
  tl.fromTo('#wordmark',{clipPath:'inset(100% 0 0 0)'},{clipPath:'inset(0% 0 0 0)',duration:.32,immediateRender:false},16.1);
  appear('#end-tagline',16.32,.26,{y:9});appear('#end-url',16.54,.23,{y:7});
  window.__timelines=window.__timelines||{};window.__timelines['main']=tl;
  window.__a2lTimeline=tl;window.__a2lSeek=t=>{tl.seek(t,false);};tl.seek(0);return tl;
};
