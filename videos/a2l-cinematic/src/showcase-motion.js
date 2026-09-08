/* global gsap */
window.__initA2LAnimation=()=>{
  const tl=gsap.timeline({paused:true,defaults:{ease:'power3.out'}});
  // HyperFrames preflights the end of a timeline before seeking to a frame.
  // Set visible baselines explicitly: an opacity-only rewind cannot undo the
  // visibility:hidden written by the later autoAlpha exit.
  gsap.set('#showcase,#agent-view',{autoAlpha:1});
  tl.set('#showcase,#agent-view',{autoAlpha:1},0);
  // Adapted from installed ui-focus-zoom: ONE world transform, with authored
  // focal anchors. The frame is fixed; the LEARN and agent objects never swap.
  const pose=(cx,cy,scale)=>({x:960-cx*scale,y:400-cy*scale,scale});
  const poses={learn:pose(600,400,1.29),wide:pose(1410,435,.68),agent:pose(2180,410,1.11),
    typing:pose(2180,410,1.18),citation:pose(2105,470,1.48),source:pose(2180,410,1.12)};
  gsap.set('#demo-world',{...pose(600,400,1.13),transformOrigin:'0 0'});
  function camera(at,duration,from,to){tl.fromTo('#demo-world',from,{...to,duration,force3D:false,ease:'power3.inOut',immediateRender:false},at);}
  function appear(target,at,duration=.22,from={y:9}){gsap.set(target,{opacity:0});tl.fromTo(target,{opacity:0,...from},{opacity:1,x:0,y:0,scale:1,duration,immediateRender:false},at);}
  function vanish(target,at,duration=.16){tl.fromTo(target,{opacity:1},{opacity:0,duration,immediateRender:false},at);}
  function draw(target,at,duration){const length=document.querySelector(target).getTotalLength();gsap.set(target,{autoAlpha:0,strokeDasharray:length,strokeDashoffset:length});tl.set(target,{autoAlpha:1},at);tl.fromTo(target,{strokeDashoffset:length},{strokeDashoffset:0,duration,ease:'power2.inOut',immediateRender:false},at);}

  // Adapted from code-terminal-run's complete chars-at-time table. Text, caret
  // and sound use one deterministic cadence; no timers, async typing or RNG.
  const typeSchedules={};
  function type(selector,start,duration,hideCaret){
    const element=document.querySelector(selector),full=element.dataset.fullText;
    const text=document.createElement('span');text.className='typed-text';
    const caret=document.createElement('span');caret.className='type-caret';caret.setAttribute('aria-hidden','true');
    element.append(text,caret);
    const weights=Array.from(full,(c,i)=>(c===' '?1.6:1)+(i%4===0?.34:0));
    const total=weights.reduce((a,b)=>a+b,0);let elapsed=0;
    const rows=weights.map((weight,i)=>({time:start+(elapsed+=weight)/total*duration,count:i+1}));
    typeSchedules[selector]={start,end:start+duration,text:full,rows};
    const driver={time:0};
    const render=()=>{let count=0;for(const row of rows){if(driver.time+1e-5>=row.time)count=row.count;else break;}text.textContent=full.slice(0,count);};
    gsap.set(caret,{opacity:0});tl.set(caret,{opacity:1},start);
    tl.to(driver,{time:10,duration:10,ease:'none',onUpdate:render},0);
    tl.set(caret,{opacity:0},hideCaret);render();
  }
  type('#sync-command',1.65,.28,2.0);
  type('#ground-command',2.6,.48,3.12);
  type('#question',3.12,.99,4.15);
  window.__a2lTyping=typeSchedules;

  gsap.set('#end,#source-view,#source-tab,#local-vault,#sync-terminal,#original-packet,#markdown-packet,#agent-context,#reading,#answer>span,#citation-chip,#source-proof,#click-ring',{autoAlpha:0});
  gsap.set('#step-labels>span',{autoAlpha:0});
  for(const[id,start,end]of [['step-learn',0,1.45],['step-vault',1.45,2.76],['step-agent',2.76,6.12],['step-source',6.12,8.46]]){tl.set('#'+id,{autoAlpha:1},start);tl.set('#'+id,{autoAlpha:0},end);}
  camera(0,.65,pose(600,400,1.13),poses.learn);
  camera(1.22,.78,poses.learn,poses.wide);
  camera(2.4,.62,poses.wide,poses.agent);
  camera(3.05,.8,poses.agent,poses.typing);
  camera(5.25,.54,poses.typing,poses.citation);
  camera(6.13,.55,poses.citation,poses.source);
  camera(7.68,.72,poses.source,poses.wide);
  camera(8.4,.26,poses.wide,pose(1410,435,.54));

  gsap.set('#cursor',{x:898,y:566,opacity:0});
  tl.fromTo('#cursor',{x:898,y:566,opacity:0},{x:931,y:416,opacity:1,duration:.38,ease:'power2.inOut',immediateRender:false},.17);
  tl.fromTo('#lecture-resource',{backgroundColor:'#ffffff',borderColor:'#ffffff'},
    {backgroundColor:'#eaf0ff',borderColor:'#bcd0fc',duration:.18,immediateRender:false},.66);
  function click(at,x,y){tl.fromTo('#click-ring',{x:x-13,y:y-13,scale:.35,autoAlpha:.7},{x:x-13,y:y-13,scale:1.25,autoAlpha:0,duration:.25,immediateRender:false},at);tl.fromTo('#cursor',{scale:1},{scale:.86,duration:.065,yoyo:true,repeat:1,immediateRender:false},at);}
  click(.69,931,416);vanish('#cursor',1.2,.12);
  tl.fromTo('#sync-terminal',{autoAlpha:0,y:15},{autoAlpha:1,y:0,duration:.18,immediateRender:false},1.6);
  appear('#sync-complete',2.16,.2,{y:4});
  tl.fromTo('#local-vault',{autoAlpha:0,scale:.9},{autoAlpha:1,scale:1,duration:.22,immediateRender:false},1.92);
  draw('#route-original',1.93,.3);draw('#route-context',2.18,.38);
  tl.fromTo('#original-packet',{x:1066,y:407,autoAlpha:1,scale:.8},{x:1279,y:368,scale:1,autoAlpha:0,duration:.32,ease:'power2.inOut',immediateRender:false},1.96);
  tl.fromTo('#markdown-packet',{x:1460,y:373,autoAlpha:1,scale:1},{x:1715,y:184,scale:.48,autoAlpha:0,duration:.38,ease:'power2.inOut',immediateRender:false},2.20);
  tl.fromTo('#agent-context',{autoAlpha:0,y:9},{autoAlpha:1,y:0,duration:.26,immediateRender:false},2.55);
  // The wider topology establishes context; remove cropped peripheral labels
  // during close-ups, then restore those SAME objects on the final pullback.
  tl.fromTo('#learn-window,#sync-terminal,#local-vault,#connections',{opacity:1},{opacity:0,duration:.4,immediateRender:false},2.6);
  tl.fromTo('#learn-window,#sync-terminal,#local-vault,#connections',{opacity:0},{opacity:1,duration:.4,immediateRender:false},7.75);

  // User typing, submit, retrieval, answer, citation: the actual causal order.
  tl.fromTo('#composer',{boxShadow:'0 0 0 4px #eaf0ff66'},{boxShadow:'0 0 0 4px #cbd9ffbb',duration:.26,immediateRender:false},3.1);
  tl.fromTo('#cursor',{x:2510,y:400,opacity:0,scale:1},{x:2609,y:337,opacity:1,scale:1,duration:.24,ease:'power2.inOut',immediateRender:false},3.88);
  click(4.15,2609,337);
  tl.fromTo('#send-button',{scale:1},{scale:.9,duration:.06,yoyo:true,repeat:1,immediateRender:false},4.15);
  vanish('#cursor',4.34,.12);
  tl.fromTo('#reading',{autoAlpha:0,y:5},{autoAlpha:1,y:0,duration:.18,immediateRender:false},4.3);
  tl.fromTo('.reading-dots i',{opacity:.3},{opacity:1,duration:.16,stagger:.08,yoyo:true,repeat:1,immediateRender:false},4.32);
  document.querySelectorAll('#answer>span').forEach((el,i)=>tl.fromTo(el,{autoAlpha:0,y:8},{autoAlpha:1,y:0,duration:.14,immediateRender:false},4.68+i*.09));
  tl.fromTo('#citation-chip',{autoAlpha:0,y:10},{autoAlpha:1,y:0,duration:.23,immediateRender:false},5.30);
  // Peripheral chrome recedes before leaving the cropped close-up, then
  // returns with the full source window. The fixed header stays unobscured.
  tl.fromTo('.agent-chrome,.agent-tabs',{autoAlpha:1},{autoAlpha:0,duration:.12,immediateRender:false},5.30);
  tl.fromTo('.agent-chrome,.agent-tabs',{autoAlpha:0},{autoAlpha:1,duration:.17,immediateRender:false},6.58);
  tl.fromTo('#cursor',{x:2260,y:646,opacity:0,scale:1},{x:2073,y:605,opacity:1,scale:1,duration:.28,ease:'power2.inOut',immediateRender:false},5.62);
  click(6.06,2073,605);
  tl.fromTo('#citation-chip',{scale:1},{scale:.977,duration:.06,yoyo:true,repeat:1,immediateRender:false},6.06);

  // Same physical window. Clicking the citation opens its local source tab.
  tl.fromTo('#agent-view',{autoAlpha:1},{autoAlpha:0,duration:.08,immediateRender:false},6.08);
  tl.set('#source-view,#source-tab',{autoAlpha:1},6.16);
  tl.fromTo('#source-view',{clipPath:'inset(77% 48% 11% 3% round 12px)'},{clipPath:'inset(0% 0% 0% 0% round 0px)',duration:.31,ease:'power3.inOut',immediateRender:false},6.16);
  tl.fromTo('#source-tab',{backgroundColor:'#f8faff',color:'#536b90'},{backgroundColor:'#ffffff',color:'#365fa8',duration:.2,immediateRender:false},6.12);
  tl.fromTo('#agent-tab',{backgroundColor:'#ffffff',borderBottomColor:'#6383cd',color:'#3d609c'},{backgroundColor:'#f8faff',borderBottomColor:'#f8faff',color:'#697b99',duration:.2,immediateRender:false},6.12);
  vanish('#cursor',6.22,.1);
  tl.fromTo('#source-highlight',{backgroundColor:'#ffffff'},{backgroundColor:'#e6edff',duration:.3,immediateRender:false},6.39);
  tl.fromTo('#source-proof',{autoAlpha:0,y:6},{autoAlpha:1,y:0,duration:.22,immediateRender:false},6.6);

  // One reversible exit owns BOTH opacity and visibility. A later redundant
  // autoAlpha set would capture an already-faded state and hide reverse seeks.
  tl.fromTo('#showcase',{autoAlpha:1},{autoAlpha:0,duration:.25,immediateRender:false},8.4);
  tl.set('#end',{autoAlpha:1},8.45);
  tl.fromTo('#brand-mark',{scale:.68,rotationY:-60,opacity:0},{scale:1,rotationY:0,opacity:1,duration:.35,immediateRender:false},8.45);
  gsap.set('#wordmark',{clipPath:'inset(100% 0% 0% 0%)'});
  tl.fromTo('#wordmark',{clipPath:'inset(100% 0% 0% 0%)'},{clipPath:'inset(0% 0% 0% 0%)',duration:.30,ease:'power3.out',immediateRender:false},8.64);
  appear('#end-tagline',8.9,.23,{y:9});appear('#end-url',9.08,.25,{y:7});
  window.__timelines=window.__timelines||{};window.__timelines['main']=tl;
  window.__a2lTimeline=tl;window.__a2lSeek=t=>{tl.seek(t,false);};tl.seek(0);return tl;
};
