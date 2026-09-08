/* global gsap */
window.__initA2LAnimation=()=>{
  const cues=window.__A2L_CUES, A=cues.actions;
  const tl=gsap.timeline({paused:true,defaults:{ease:'power3.out'}});
  const pose=(cx,cy,scale)=>({x:960-cx*scale,y:400-cy*scale,scale});
  const poses={start:pose(600,400,1.13),learn:pose(600,400,1.29),wide:pose(1410,435,.68),
    agent:pose(2180,410,1.11),typing:pose(2180,410,1.18),answer:pose(2170,463,1.25),pair:pose(2745,410,.84)};
  // A single reversible exit owns visibility. HyperFrames seeks the end before
  // rendering frame zero; no state here may depend on prior playback history.
  gsap.set('#showcase',{autoAlpha:1});tl.set('#showcase',{autoAlpha:1},0);
  gsap.set('#demo-world',{...poses.start,transformOrigin:'0 0'});
  function camera(at,duration,from,to){tl.fromTo('#demo-world',from,{...to,duration,force3D:false,ease:'power3.inOut',immediateRender:false},at);}
  function appear(target,at,duration=.22,from={y:7}){gsap.set(target,{autoAlpha:0});tl.fromTo(target,{autoAlpha:0,...from},{autoAlpha:1,x:0,y:0,scale:1,duration,immediateRender:false},at);}
  function draw(target,at,duration){const n=document.querySelector(target).getTotalLength();gsap.set(target,{autoAlpha:0,strokeDasharray:n,strokeDashoffset:n});tl.set(target,{autoAlpha:1},at);tl.fromTo(target,{strokeDashoffset:n},{strokeDashoffset:0,duration,ease:'power2.inOut',immediateRender:false},at);}
  function click(at,x,y){tl.fromTo('#click-ring',{x:x-13,y:y-13,scale:.35,autoAlpha:.7},{x:x-13,y:y-13,scale:1.25,autoAlpha:0,duration:.25,immediateRender:false},at);tl.fromTo('#cursor',{scale:1},{scale:.86,duration:.065,yoyo:true,repeat:1,immediateRender:false},at);}

  // Compiled character rows are also used to place recorded keyboard samples.
  // No timers, CSS animation, random typing or duplicate audio timing formula.
  const typeSchedules={};
  for(const schedule of cues.typing){
    const el=document.querySelector(schedule.selector),text=document.createElement('span'),caret=document.createElement('span');
    text.className='typed-text';caret.className='type-caret';caret.setAttribute('aria-hidden','true');el.append(text,caret);
    const driver={time:0};const render=()=>{let n=0;for(const row of schedule.rows){if(driver.time+1e-5>=row.time)n=row.count;else break;}text.textContent=schedule.text.slice(0,n);};
    gsap.set(caret,{opacity:0});tl.set(caret,{opacity:1},schedule.start);tl.set(caret,{opacity:0},schedule.hideCaret);
    tl.to(driver,{time:cues.duration,duration:cues.duration,ease:'none',onUpdate:render},0);render();typeSchedules[schedule.selector]=schedule;
  }
  window.__a2lTyping=typeSchedules;
  gsap.set('#end,#source-window,#local-vault,#sync-terminal,#original-packet,#markdown-packet,#codex-banner,#prompt-line,#reading,#answer,#citation-chip,#source-proof,#click-ring',{autoAlpha:0});
  gsap.set('#step-labels>span',{autoAlpha:0});
  for(const[id,start,end]of [['step-learn',0,1.6],['step-vault',1.6,3.15],['step-agent',3.15,9],['step-source',9,11.65]]){tl.set('#'+id,{autoAlpha:1},start);tl.set('#'+id,{autoAlpha:0},end);}
  camera(0,.72,poses.start,poses.learn);
  camera(1.5,.82,poses.learn,poses.wide);
  camera(3,.72,poses.wide,poses.agent);
  camera(4.65,.9,poses.agent,poses.typing);
  camera(7.7,.56,poses.typing,poses.answer);
  camera(9.08,.76,poses.answer,poses.pair);

  gsap.set('#cursor',{x:898,y:566,opacity:0});
  tl.fromTo('#cursor',{x:898,y:566,opacity:0},{x:931,y:416,opacity:1,duration:.43,ease:'power2.inOut',immediateRender:false},.23);
  tl.fromTo('#lecture-resource',{backgroundColor:'#fff',borderColor:'#fff'},{backgroundColor:'#eaf0ff',borderColor:'#bcd0fc',duration:.18,immediateRender:false},A.selectCourse-.03);
  click(A.selectCourse,931,416);tl.to('#cursor',{opacity:0,duration:.12},1.46);
  appear('#sync-terminal',2.03,.18,{y:12});appear('#sync-complete',A.syncComplete,.18,{y:4});
  appear('#local-vault',2.5,.23,{scale:.92});draw('#route-original',2.6,.28);draw('#route-context',2.8,.36);
  tl.fromTo('#original-packet',{x:1066,y:407,autoAlpha:1,scale:.8},{x:1279,y:368,scale:1,autoAlpha:0,duration:.29,ease:'power2.inOut',immediateRender:false},2.63);
  tl.fromTo('#markdown-packet',{x:1460,y:373,autoAlpha:1,scale:1},{x:1715,y:251,scale:.48,autoAlpha:0,duration:.37,ease:'power2.inOut',immediateRender:false},2.83);
  tl.fromTo('#learn-window,#sync-terminal,#local-vault,#connections',{opacity:1},{opacity:0,duration:.3,immediateRender:false},3.2);

  appear('#codex-banner',4.29,.2,{y:0});appear('#prompt-line',4.5,.15,{y:0});
  tl.fromTo('#enter-key',{backgroundColor:'#24262d',scale:1},{backgroundColor:'#626b80',scale:.87,duration:.065,yoyo:true,repeat:1,immediateRender:false},A.questionEnter);
  tl.to('#enter-key',{opacity:0,duration:.13},6.6);
  appear('#reading',A.read,.18,{y:0});
  // Terminal output streams on baselines rather than floating in as chat bubbles.
  tl.set('#answer',{autoAlpha:1},A.answerStart);
  document.querySelectorAll('.answer-copy>span').forEach((el,i)=>{gsap.set(el,{clipPath:'inset(0 100% 0 0)'});tl.fromTo(el,{clipPath:'inset(0 100% 0 0)'},{clipPath:'inset(0 0% 0 0)',duration:.28,ease:'steps(18)',immediateRender:false},A.answerStart+i*.33);});
  appear('#citation-chip',A.citation,.22,{y:0});
  // Keep chrome out of the fixed headline while pushing toward the answer.
  tl.fromTo('.terminal-chrome',{autoAlpha:1},{autoAlpha:0,duration:.1,immediateRender:false},7.71);
  tl.fromTo('.terminal-chrome',{autoAlpha:0},{autoAlpha:1,duration:.2,immediateRender:false},9.42);
  tl.fromTo('#cursor',{x:2260,y:660,opacity:0,scale:1},{x:1995,y:623,opacity:1,scale:1,duration:.32,ease:'power2.inOut',immediateRender:false},8.48);
  click(A.openSource,1995,623);tl.to('#cursor',{opacity:0,duration:.12},9.13);
  // A linked local file opens in a neighboring editor. Answer and proof stay
  // visible together, making the citation inspectable instead of a magic flash.
  tl.set('#source-window',{autoAlpha:1},9.09);
  tl.fromTo('#source-window',{clipPath:'inset(0 100% 0 0 round 26px)',x:-36},{clipPath:'inset(0 0% 0 0 round 26px)',x:0,duration:.49,ease:'power3.inOut',immediateRender:false},9.09);
  tl.fromTo('#source-highlight',{backgroundColor:'#fff'},{backgroundColor:'#e6edff',duration:.28,immediateRender:false},A.highlight);
  appear('#source-proof',A.proof,.22,{y:5});

  // Retire the product before revealing the opaque end card. No text is ever
  // left under an incoming plate; one reversible fade owns the old scene.
  tl.fromTo('#showcase',{autoAlpha:1},{autoAlpha:0,duration:.24,immediateRender:false},A.outro);
  tl.set('#end',{autoAlpha:1},11.9);
  tl.fromTo('#brand-mark',{scale:.9,y:12,opacity:0},{scale:1,y:0,opacity:1,duration:.32,immediateRender:false},11.9);
  gsap.set('#wordmark',{clipPath:'inset(100% 0 0 0)'});tl.fromTo('#wordmark',{clipPath:'inset(100% 0 0 0)'},{clipPath:'inset(0% 0 0 0)',duration:.32,immediateRender:false},12.02);
  appear('#end-tagline',12.25,.26,{y:9});appear('#end-url',12.48,.23,{y:7});
  window.__timelines=window.__timelines||{};window.__timelines['main']=tl;
  window.__a2lTimeline=tl;window.__a2lSeek=t=>{tl.seek(t,false);};tl.seek(0);return tl;
};
