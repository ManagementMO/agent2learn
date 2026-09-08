/* global gsap */
window.__initA2LAnimation=()=>{
 const tl=gsap.timeline({paused:true,defaults:{ease:'power3.out'},onUpdate:()=>window.__renderA2L3D?.(tl.time())});
 const scenes=[['intro',0,1.8],['learn',1.8,4.8],['twins',4.8,6.5],['ask',6.5,9],['source',9,12.5],['vault',12.5,15],['end',15,18]];
 gsap.set('.scene',{autoAlpha:0});
 for(const[id,start,end]of scenes){tl.set(`#${id}`,{autoAlpha:1},start);if(end<18)tl.set(`#${id}`,{autoAlpha:0},end);}
 function move(id,start,dur,from={},to={}){if(from.opacity!==1)gsap.set(id,{opacity:0});tl.fromTo(id,{x:0,y:0,scale:1,rotationX:0,rotationY:0,rotationZ:0,opacity:0,...from},{x:0,y:0,scale:1,rotationX:0,rotationY:0,rotationZ:0,opacity:1,...to,duration:dur,immediateRender:false},start);}
 function exit(id,start,dur,from={},to={}){move(id,start,dur,{opacity:1,...from},{opacity:0,...to,ease:'power3.in'});}
 function wash(start){tl.fromTo('#transition-wash',{opacity:.55},{opacity:0,duration:.24,immediateRender:false},start);}
 move('#corner-brand',0,.5,{y:-10});exit('#corner-brand',14.8,.2);
 move('#intro-title',.08,.65,{x:-75});move('#in-context',.47,.50,{y:50});move('#intro-label',.80,.55,{y:20});
 exit('#intro-title',1.58,.22,{}, {y:-55});exit('#intro-label',1.62,.18);
 move('#learn-title',1.85,.47,{y:25});
 move('#learn-window',1.85,.65,{x:-170,y:65,scale:.92,rotationY:18,rotationX:7},{rotationY:4,rotationX:2});
 move('.course-row',2.10,.50,{x:-35},{stagger:.08});move('#transfer-path',2.45,.5,{scale:.70});move('#vault-caption',2.75,.45,{y:20});
 ['#copy-pdf','#copy-lab','#copy-outline'].forEach((id,i)=>{
  const start=2.7+i*.43;
  move(id,start,.17,{x:-26,y:0,scale:.5,rotationY:-25},{x:0,y:-24,scale:1,rotationY:0});
  exit(id,start+.17,.25,{x:0,y:-24,scale:1,rotationY:0},{x:165,y:-16,scale:.55,rotationY:25});
 });
 exit('#learn-window',4.38,.42,{rotationY:4,rotationX:2},{x:130,y:30,scale:.87,rotationY:-12});exit('#learn-title',4.56,.24,{}, {y:-35});exit('#transfer-path',4.46,.22);exit('#vault-caption',4.5,.25);
 wash(4.8);move('#twins-title',4.8,.48,{x:-60});
 move('#pdf-card',4.8,.67,{x:120,y:90,rotationY:-22,rotationZ:-5,scale:.8},{rotationY:-10,rotationZ:-3});
 move('#md-card',4.95,.60,{x:140,y:70,rotationY:25,rotationZ:8,scale:.8},{rotationY:8,rotationZ:2});move('#twin-link',5.35,.35,{scale:.75});
 exit('#pdf-card',6.26,.24,{rotationY:-10,rotationZ:-3},{x:-50,y:-75,rotationY:-17,scale:1.06});exit('#md-card',6.26,.24,{rotationY:8,rotationZ:2},{x:60,y:-75,rotationY:18,scale:1.06});exit('#twins-title',6.29,.21);exit('#twin-link',6.29,.21);
 move('#ask-title',6.5,.48,{y:45});move('#agent-window',6.5,.60,{y:140,scale:.92,rotationX:10});
 move('#context-chip',6.72,.35,{x:-20});move('#question',6.85,.40,{y:25});move('#answer',7.28,.45,{y:25});move('#citation-chip',7.76,.36,{y:20});
 move('#cursor',8.26,.42,{x:240,y:125},{x:0,y:-65,ease:'power2.inOut'});
 tl.fromTo('#citation-chip',{scale:1},{scale:.975,duration:.09,yoyo:true,repeat:1,ease:'power2.inOut',immediateRender:false},8.76);
 exit('#agent-window',8.84,.16,{}, {scale:1.10,y:-30});exit('#ask-title',8.84,.16);exit('#cursor',8.86,.14,{x:0,y:-65});
 wash(9);move('#source-title',9,.50,{x:-60});move('#source-window',9,.52,{scale:.91,y:80,rotationX:5});
 move('#source-highlight',9.35,.42,{x:24,opacity:.1});move('#line-locator',9.38,.35,{scale:1.2});move('#source-proof',9.7,.45,{y:20});
 exit('#source-window',12.25,.25,{}, {y:-65,scale:1.06});exit('#source-title',12.29,.21,{}, {y:-40});
 wash(12.5);move('#vault-title',12.5,.60,{x:-75});move('#label-course',12.62,.48,{y:35,scale:.9});move('#label-index',12.8,.48,{y:35,scale:.9});move('#local-tags',13.0,.45,{y:20});
 exit('#vault-title',14.75,.25,{}, {y:-60});exit('#label-course',14.67,.23,{}, {y:-40,scale:.95});exit('#label-index',14.7,.23,{}, {y:40,scale:.95});exit('#local-tags',14.8,.2);
 // Finish the glass object's travel before admitting the wordmark into its lane.
 move('#wordmark',15.66,.48,{y:45,scale:.98});move('#end-tagline',15.95,.40,{y:24});move('#end-url',16.17,.38,{y:18});
 tl.to({},{duration:.01},17.99);
 window.__a2lTimeline=tl;
 window.__a2lSeek=t=>{tl.seek(t,false);window.__renderA2L3D?.(t);};
 tl.seek(0);return tl;
};
