import assert from 'node:assert/strict';
import {chromium} from 'playwright';

// Real browser behavior: the proof surface reveals without shifting its text,
// and the bounded warm flow resolves into legible, neutral document outlines.
const browser = await chromium.launch({channel:'chrome',headless:true});
try {
  const page = await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
  await page.goto('http://localhost:3017/api/projects/a2l-cinematic/preview?__hf_shader_capture_scale=1&__hf_shader_loading=player');
  await page.waitForFunction(() => window.__a2lSeek && document.fonts.status === 'loaded');
  const flow = await page.evaluate(() => {
    window.__a2lSeek(6.3);
    return [...document.querySelectorAll('.information-bit')].map(e => {
      const s = getComputedStyle(e);
      return {opacity:Number(s.opacity),color:s.backgroundColor,size:parseFloat(s.width),radius:s.borderRadius};
    }).filter(e => e.opacity > .5);
  });
  assert.ok(flow.length >= 24, 'A visible but bounded information stream');
  for (const bit of flow) {
    const [r,g,b] = bit.color.match(/[\d.]+/g).map(Number);
    assert.ok(r >= 200 && g >= 150 && r > g && g > b + 55, 'Visible particles are warm yellow, not the old gray pool');
    assert.ok(bit.size <= 7 && bit.radius === '50%', 'Tiny circles, not oversized decorative beads');
  }
  const proof = await page.evaluate(() => {
    const sample = time => {
      window.__a2lSeek(time);
      const row = document.querySelector('#source-highlight');
      const range = document.createRange();range.selectNodeContents(row.lastElementChild);
      const r = range.getBoundingClientRect(), skin = getComputedStyle(row,'::after');
      return {box:[r.x,r.y,r.width,r.height],opacity:Number(skin.opacity),fill:skin.backgroundImage,radius:parseFloat(skin.borderRadius),shadow:skin.boxShadow};
    };
    const settling = sample(13.73), held = sample(14.5), reverse = sample(13.73);
    window.__a2lSeek(13.519);
    const before = Number(getComputedStyle(document.querySelector('#source-highlight'),'::after').opacity);
    window.__a2lSeek(14.5);
    const target = document.querySelector('.citation-target');
    const style = target && getComputedStyle(target);
    return {settling,held,reverse,before,chip:style && {fill:style.backgroundImage,radius:parseFloat(style.borderRadius),shadow:style.boxShadow},text:document.querySelector('#source-highlight').textContent};
  });
  assert.equal(proof.before, 0, 'No tactile source highlight before its cue');
  assert.ok(proof.settling.opacity > .7 && proof.settling.opacity < 1, 'The emphasis settles instead of appearing as a hard flash');
  assert.equal(proof.held.opacity, 1, 'The source emphasis is fully held for reading');
  assert.deepEqual(proof.settling.box, proof.held.box, 'The sentence and gutter do not jump while the surface settles');
  assert.deepEqual(proof.settling, proof.reverse, 'The glass reveal is reversible at the same sub-second pose');
  assert.match(proof.held.fill, /linear-gradient/, 'A shallow illuminated source surface');
  assert.ok(proof.held.radius >= 8 && proof.held.radius <= 16 && proof.held.shadow !== 'none');
  assert.ok(proof.chip && proof.chip.radius >= 6 && proof.chip.radius <= 14 && proof.chip.shadow !== 'none', 'The citation link is one coherent tactile target');
  assert.equal(proof.text, '42Use prefix notation in Racket.');
  assert.equal(await page.locator('.citation-target').evaluate(e => getComputedStyle(e,'::after').content), 'none', 'The citation target has no decorative corner dot');
  await page.evaluate(() => window.__a2lSeek(17.2));
  assert.equal((await page.locator('#end-url').textContent()).trim(), 'uv tool install agent2learn', 'Closing CTA is the requested package-install placeholder');
  assert.equal(await page.locator('#end-url svg').count(), 0, 'A terminal command is not presented as an external-link control');
  const receipts = await page.evaluate(() => {
    window.__a2lSeek(8.05);
    return [...document.querySelectorAll('.ingest-file>span:first-child')].map(e => ({color:getComputedStyle(e).color,halo:Number(getComputedStyle(e.querySelector('.receipt-energy')).opacity)}));
  });
  assert.deepEqual(receipts, Array.from({length:3}, () => ({color:'rgb(237, 237, 235)',halo:0})), 'Absorbed energy settles back to clean monochrome document icons');
  console.log(JSON.stringify({status:'passed',visibleFireflies:flow.length,sourceReveal:'stable text, reversible glass',receipts:'neutral after absorption'},null,2));
} finally { await browser.close(); }
