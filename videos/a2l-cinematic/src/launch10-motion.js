/* global gsap */
window.__initA2LAnimation=()=>{
  const flight=document.querySelector('#pdf-card').cloneNode(true);
  flight.id='handoff-document';document.querySelector('#document-handoff').appendChild(flight);
  const tl=gsap.timeline({paused:true,defaults:{ease:'power3.out'}});
  const scenes=[['learn',0,2.3],['document-handoff',2.0,2.52],['twins',2.3,3.5],['ask',3.42,6.20],['source',5.88,7.85],['end',7.85,10]];
  gsap.set('.scene',{autoAlpha:0});
  for(const[id,start,end]of scenes){tl.set(`#${id}`,{autoAlpha:1},start);if(end<10)tl.set(`#${id}`,{autoAlpha:0},end);}
  const pose={x:0,y:0,scale:1,rotationX:0,rotationY:0,rotationZ:0};
  // Scene labels cut once; overlapping transition panels must not duplicate copy.
  gsap.set('#ask .demo-note,#source .demo-note',{opacity:0});
  tl.set('#twins .demo-note',{opacity:0},3.42);
  tl.set('#ask .demo-note',{opacity:1},3.42);
  tl.set('#ask .demo-note',{opacity:0},5.88);
  tl.set('#source .demo-note',{opacity:1},5.88);
  function move(id,start,duration,from={},to={}){
    if(from.opacity!==1)gsap.set(id,{opacity:0});
    tl.fromTo(id,{...pose,opacity:0,...from},{...pose,opacity:1,...to,duration,immediateRender:false},start);
  }
  function mask(id,start,duration,from,to='inset(0% 0% 0% 0%)',ease='expo.inOut'){
    gsap.set(id,{clipPath:from});tl.fromTo(id,{clipPath:from},{clipPath:to,duration,ease,immediateRender:false},start);
  }
  function close(id,start,duration,to='inset(0% 0% 100% 0%)'){
    tl.fromTo(id,{clipPath:'inset(0% 0% 0% 0%)'},{clipPath:to,duration,ease:'power3.inOut',immediateRender:false},start);
  }
  move('#corner-brand',0,.25,{y:-10});move('#corner-brand',7.6,.25,{opacity:1},{opacity:0});
  mask('#learn-headline',.03,.40,'inset(0% 100% 0% 0%)');
  // The opening is the course website itself, with a controlled camera settle.
  move('#learn-browser',0,.55,{opacity:1,x:50,y:35,scale:1.04,rotationY:-7},{rotationY:0});
  tl.fromTo('#lecture-resource',{backgroundColor:'#ffffff'},
    {backgroundColor:'#edf2ff',duration:.3,repeat:1,yoyo:true,immediateRender:false},1.2);
  close('#learn-headline',1.89,.25,'inset(0% 100% 0% 0%)');
  close('#learn-browser',2.0,.29,'inset(0% 100% 0% 0% round 32px)');

  // One document flies out of LEARN, then its readable twin fans into place.
  move('#handoff-document',2.0,.52,{opacity:1,x:-308,y:360,scale:.16,rotationZ:1},
    {rotationY:-10,rotationZ:-3,ease:'power3.inOut'});
  gsap.set('#pdf-card',{rotationY:-10,rotationZ:-3,opacity:0});tl.set('#pdf-card',{opacity:1},2.52);
  mask('#twins-title',2.42,.30,'inset(0% 100% 0% 0%)');
  move('#md-card',2.44,.44,{opacity:1,rotationY:-88,x:-20},{rotationY:8,rotationZ:2});
  move('#twin-link',2.7,.2,{scale:.7});
  move('#pdf-card',3.27,.23,{opacity:1,rotationY:-10,rotationZ:-3},{opacity:1,rotationY:88,rotationZ:-3,ease:'power3.in'});
  move('#md-card',3.27,.23,{opacity:1,rotationY:8,rotationZ:2},{opacity:1,rotationY:-88,rotationZ:2,ease:'power3.in'});
  close('#twins-title',3.28,.22);close('#twin-link',3.28,.22);

  // Opposing paper folds -> a clean horizontal iris into the agent workspace.
  mask('#agent-window',3.42,.35,'inset(49.5% 0% 49.5% 0% round 24px)','inset(0% 0% 0% 0% round 24px)','power3.out');
  mask('#ask-title',3.5,.30,'inset(0% 100% 0% 0%)');
  move('#context-chip',3.74,.2,{y:8});
  mask('#question',3.9,.25,'inset(0% 100% 0% 0% round 17px)','inset(0% 0% 0% 0% round 17px)');
  move('#answer',4.18,.28,{y:12});move('#citation-chip',4.66,.27,{y:13});
  move('#cursor',5.32,.34,{x:195,y:135},{x:0,y:0,ease:'power2.inOut'});
  tl.fromTo('#citation-chip',{scale:1},{scale:.975,duration:.07,yoyo:true,repeat:1,immediateRender:false},5.69);
  close('#ask-title',5.76,.20);move('#cursor',5.88,.08,{opacity:1},{opacity:0});

  // The citation becomes the source editor, expanding from its own on-screen box.
  mask('#source-window',5.88,.34,'inset(398px 1000px 130px 164px round 13px)','inset(0px 0px 0px 0px round 32px)','power3.out');
  tl.fromTo('#source-window .window-content',{backgroundColor:'#e8edff'},{backgroundColor:'#ffffff',duration:.42,immediateRender:false},5.88);
  mask('#source-title',5.98,.32,'inset(0% 100% 0% 0%)');
  move('.source-bar',6.06,.22,{y:8});move('.source-code',6.10,.23,{y:8});
  mask('#source-highlight',6.25,.24,'inset(0% 100% 0% 0%)');
  move('#line-locator',6.28,.18,{scale:1.1});move('#source-proof',6.45,.2,{y:8});
  close('#source-title',7.60,.23);
  close('#source-window',7.59,.25,'inset(48% 0% 38% 0% round 12px)');

  // The evidence strip closes; the new original mark and wordmark lock up cleanly.
  move('#brand-mark',7.85,.42,{opacity:1,scale:.45,rotationY:-75},{rotationY:0,ease:'power3.out'});
  mask('#wordmark',8.03,.39,'inset(100% 0% 0% 0%)');
  move('#end-tagline',8.35,.3,{y:14});move('#end-url',8.58,.3,{y:10});
  tl.to({},{duration:.01},9.99);
  window.__a2lTimeline=tl;
  // GSAP timelines are thenables. A seek setter must return void, otherwise
  // browser automation awaits this paused timeline forever after seeking it.
  window.__a2lSeek=t=>{tl.seek(t,false);};
  tl.seek(0);return tl;
};
