/* global gsap */
window.__initA2LAnimation = () => {
  // One travelling document bridges two scenes. Its destination geometry is the
  // exact PDF card, so the handoff changes context without changing the object.
  const documentFlight = document.querySelector('#pdf-card').cloneNode(true);
  documentFlight.id = 'handoff-document';
  document.querySelector('#document-handoff').appendChild(documentFlight);

  const tl = gsap.timeline({paused: true, defaults: {ease: 'power3.out'},
    onUpdate: () => window.__renderA2L3D?.(tl.time())});
  const scenes = [
    ['intro', 0, 1.8], ['learn', 1.8, 4.8], ['document-handoff', 4.37, 4.8],
    ['twins', 4.8, 6.5], ['ask', 6.5, 9], ['source', 8.86, 12.5],
    ['vault', 12.5, 15], ['end', 15, 18]
  ];
  gsap.set('.scene', {autoAlpha: 0});
  for (const [id, start, end] of scenes) {
    tl.set(`#${id}`, {autoAlpha: 1}, start);
    if (end < 18) tl.set(`#${id}`, {autoAlpha: 0}, end);
  }
  const pose = {x: 0, y: 0, scale: 1, rotationX: 0, rotationY: 0, rotationZ: 0};
  function move(id, start, duration, from = {}, to = {}) {
    if (from.opacity !== 1) gsap.set(id, {opacity: 0});
    tl.fromTo(id, {...pose, opacity: 0, ...from},
      {...pose, opacity: 1, ...to, duration, immediateRender: false}, start);
  }
  function mask(id, start, duration, from, to = 'inset(0% 0% 0% 0%)') {
    gsap.set(id, {clipPath: from});
    tl.fromTo(id, {clipPath: from}, {clipPath: to, duration,
      ease: 'expo.inOut', immediateRender: false}, start);
  }
  function wipeOut(id, start, duration, to = 'inset(0% 0% 100% 0%)') {
    tl.fromTo(id, {clipPath: 'inset(0% 0% 0% 0%)'},
      {clipPath: to, duration, ease: 'power3.inOut', immediateRender: false}, start);
  }

  move('#corner-brand', 0, .35, {y: -10});
  move('#corner-brand', 14.75, .25, {opacity: 1}, {opacity: 0});
  move('#intro-title', .08, .55, {x: -50});
  mask('#in-context', .35, .48, 'inset(100% 0% 0% 0%)');
  move('#intro-label', .76, .4, {y: 14});

  // 1. Shared-object match cut: type is shuttered away while the same 3D vault
  // pulls back. A portal drawer opens in the space the type just vacated.
  wipeOut('#intro-title', 1.53, .27);
  wipeOut('#intro-label', 1.56, .24);
  mask('#learn-title', 1.85, .43, 'inset(0% 100% 0% 0%)');
  mask('#learn-window', 1.8, .62, 'inset(0% 100% 0% 0% round 32px)',
    'inset(0% 0% 0% 0% round 32px)');
  move('#learn-window', 1.8, .62, {opacity: 1, x: -45, rotationY: 22},
    {rotationY: 4, rotationX: 2});
  move('.course-row', 2.03, .40, {x: -24}, {stagger: .085});
  mask('#transfer-path', 2.4, .40, 'inset(0% 100% 0% 0%)');
  move('#vault-caption', 2.68, .36, {y: 12});
  ['#copy-pdf', '#copy-lab', '#copy-outline'].forEach((id, i) => {
    const start = 2.62 + i*.43;
    move(id, start, .19, {x: -26, y: 0, scale: .66, rotationY: -30},
      {x: 23, y: -47, scale: 1, rotationY: 0});
    move(id, start+.19, .23, {opacity: 1, x: 23, y: -47, scale: 1},
      {opacity: 0, x: 174, y: -12, scale: .52, rotationY: 40, ease: 'power2.in'});
  });

  // 2. A physical document handoff, not another panel fade. The list retracts,
  // its document flies to the next shot, and the Markdown twin fans out beside it.
  wipeOut('#learn-title', 4.31, .22, 'inset(0% 100% 0% 0%)');
  wipeOut('#learn-window', 4.34, .20, 'inset(0% 100% 0% 0% round 32px)');
  wipeOut('#transfer-path', 4.30, .2);
  wipeOut('#vault-caption', 4.3, .2);
  move('#handoff-document', 4.37, .43,
    {opacity: 1, x: -750, y: 218, scale: .18, rotationZ: 4},
    {rotationY: -10, rotationZ: -3, ease: 'power3.inOut'});
  gsap.set('#pdf-card', {rotationY: -10, rotationZ: -3});
  mask('#twins-title', 4.87, .35, 'inset(0% 100% 0% 0%)');
  move('#md-card', 4.84, .52, {opacity: 1, x: -30, rotationY: -88},
    {rotationY: 8, rotationZ: 2, ease: 'power3.out'});
  move('#twin-link', 5.15, .3, {scale: .7});

  // 3. Opposing paper folds lead into a horizontal iris: a closed line opens
  // into the agent's working surface, with no full-screen white wash.
  move('#pdf-card', 6.18, .32, {opacity: 1, rotationY: -10, rotationZ: -3},
    {opacity: 1, rotationY: 88, rotationZ: -3, x: 30, ease: 'power3.in'});
  move('#md-card', 6.18, .32, {opacity: 1, rotationY: 8, rotationZ: 2},
    {opacity: 1, rotationY: -88, rotationZ: 2, x: -30, ease: 'power3.in'});
  wipeOut('#twins-title', 6.25, .25);
  wipeOut('#twin-link', 6.25, .25);
  mask('#agent-window', 6.5, .48, 'inset(49.5% 0% 49.5% 0% round 24px)',
    'inset(0% 0% 0% 0% round 24px)');
  mask('#ask-title', 6.52, .42, 'inset(0% 100% 0% 0%)');
  move('#context-chip', 6.83, .26, {y: 9});
  mask('#question', 6.98, .28, 'inset(0% 100% 0% 0% round 17px)',
    'inset(0% 0% 0% 0% round 17px)');
  move('#answer', 7.29, .35, {y: 14});
  move('#citation-chip', 7.76, .32, {y: 14});
  move('#cursor', 8.26, .42, {x: 240, y: 125}, {x: 0, y: -65, ease: 'power2.inOut'});
  tl.fromTo('#citation-chip', {scale: 1}, {scale: .975, duration: .085,
    yoyo: true, repeat: 1, immediateRender: false}, 8.76);

  // 4. The citation is a portal. Its geometry expands to the source editor;
  // content waits until the portal opens so text never smears across the cut.
  wipeOut('#ask-title', 8.78, .2);
  move('#cursor', 8.87, .10, {opacity: 1, x: 0, y: -65}, {opacity: 0, x: 0, y: -65});
  mask('#source-window', 8.86, .54, 'inset(407px 1000px 113px 164px round 13px)',
    'inset(0px 0px 0px 0px round 32px)');
  tl.fromTo('#source-window .window-content', {backgroundColor: '#e8edff'},
    {backgroundColor: '#ffffff', duration: .54, immediateRender: false}, 8.86);
  mask('#source-title', 9.08, .40, 'inset(0% 100% 0% 0%)');
  move('.source-bar', 9.12, .26, {y: 9});
  move('.source-code', 9.18, .28, {y: 9});
  mask('#source-highlight', 9.35, .33, 'inset(0% 100% 0% 0%)');
  move('#line-locator', 9.38, .25, {scale: 1.15});
  move('#source-proof', 9.66, .28, {y: 10});

  // 5. Collapse the editor back to its source line. The next shot unfolds the
  // actual local-file hierarchy instead of presenting the same abstract stack.
  wipeOut('#source-title', 12.18, .25);
  wipeOut('#source-window', 12.19, .30, 'inset(48% 0% 38% 0% round 12px)');
  mask('#vault-title', 12.52, .42, 'inset(0% 100% 0% 0%)');
  mask('#tree-root', 12.5, .35, 'inset(0% 100% 0% 0% round 22px)',
    'inset(0% 0% 0% 0% round 22px)');
  gsap.set('#tree-connectors path', {strokeDasharray: 1000, strokeDashoffset: 1000});
  tl.fromTo('#tree-connectors path', {strokeDashoffset: 1000},
    {strokeDashoffset: 0, duration: .7, stagger: .06, ease: 'power2.out', immediateRender: false}, 12.68);
  ['#tree-content', '#tree-pdf', '#tree-markdown', '#tree-index'].forEach((id, i) => {
    mask(id, 12.75+i*.13, .4, 'inset(0% 100% 0% 0% round 18px)',
      'inset(0% 0% 0% 0% round 18px)');
  });
  move('#local-tags', 13, .32, {y: 12});

  // 6. The hierarchy closes like a precision shutter into the brand mark.
  wipeOut('#vault-tree', 14.65, .35, 'inset(49.8% 45% 49.8% 45% round 20px)');
  wipeOut('#vault-title', 14.72, .28);
  wipeOut('#local-tags', 14.72, .28);
  mask('#wordmark', 15.55, .52, 'inset(100% 0% 0% 0%)');
  move('#end-tagline', 15.94, .40, {y: 18});
  move('#end-url', 16.16, .38, {y: 12});
  tl.to({}, {duration: .01}, 17.99);
  window.__a2lTimeline = tl;
  window.__a2lSeek = t => {tl.seek(t, false); window.__renderA2L3D?.(t);};
  tl.seek(0);
  return tl;
};
