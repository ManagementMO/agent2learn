// Playwright CLI: run-code --filename scripts/verify-marker-browser.js
// Exercise the opening stroke itself, rather than only its final screenshot.
async function verifyMarkerBrowser(page) {
  const origin = await page.evaluate(() => location.origin);
  const cases = [];
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
  };

  await page.setViewportSize({ width: 1440, height: 960 });
  for (const theme of ['light', 'dark']) {
    await page.emulateMedia({ reducedMotion: 'no-preference', colorScheme: theme });
    await page.evaluate((theme) => localStorage.setItem('starlight-theme', theme), theme);
    await page.goto(origin, { waitUntil: 'domcontentloaded' });
    const timing = await page.evaluate(async () => {
      await document.fonts.ready;
      const marker = document.querySelector('.hero-marker');
      const draw = marker.getAnimations()[0];
      if (!draw) throw new Error('The opening marker did not draw');
      draw.pause();
      window.__markerDraw = draw;
      return draw.effect.getTiming();
    });
    assert(timing.iterations === 1 && timing.duration < 1000, 'Marker must be short and once only');

    const frames = [];
    for (const progress of [0, 0.35, 0.6, 0.95]) {
      const frame = await page.evaluate(
        async ({ progress, timing }) => {
          window.__markerDraw.currentTime = timing.delay + timing.duration * progress;
          await new Promise((resolve) => requestAnimationFrame(resolve));
          const marker = document.querySelector('.hero-marker');
          const style = getComputedStyle(marker);
          const rect = (selector) => {
            const { x, y, width, height } = document
              .querySelector(selector)
              .getBoundingClientRect();
            return { x, y, width, height };
          };
          return {
            clip: style.clipPath,
            ink: style.color,
            logoInk: getComputedStyle(document.querySelector('[data-brand-accent]')).fill,
            transform: style.transform,
            marker: rect('.hero-marker'),
            heading: rect('#hero-title'),
          };
        },
        { progress, timing },
      );
      await page.locator('.hero').screenshot({
        path: `output/playwright/marker-${theme}-${Math.round(progress * 100)}.png`,
        animations: 'allow',
      });
      frames.push(frame);
    }
    const leadingEdges = frames.map((frame) => Number(frame.clip.match(/-?[\d.]+/g)[2]));
    assert(
      leadingEdges.every((edge, i) => i === 0 || edge > leadingEdges[i - 1]),
      `${theme}: ink did not advance from left to right`,
    );
    assert(
      frames.every(
        (frame) =>
          JSON.stringify(frame.marker) === JSON.stringify(frames[0].marker) &&
          JSON.stringify(frame.heading) === JSON.stringify(frames[0].heading) &&
          frame.transform === 'none',
      ),
      `${theme}: the draw stretched the artwork or moved the headline`,
    );
    assert(
      frames.every((frame) => frame.ink === frame.logoInk && frame.ink === 'rgb(255, 213, 79)'),
      `${theme}: marker no longer matches the logo's gold`,
    );

    // Exercise a hidden-tab notification while the draw is in progress.
    const paused = await page.evaluate(async () => {
      const draw = window.__markerDraw;
      draw.currentTime = 0;
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      document.dispatchEvent(new Event('visibilitychange'));
      const before = draw.currentTime;
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const held = draw.playState === 'paused' && draw.currentTime === before;
      delete document.hidden;
      document.dispatchEvent(new Event('visibilitychange'));
      return held;
    });
    assert(paused, `${theme}: marker advanced while the document was hidden`);
    await page.locator('.hero-marker[data-drawn]').waitFor();
    await page.locator('.hero-marked-word').hover();
    await page.evaluate(() => scrollTo(0, document.body.scrollHeight));
    await page.evaluate(() => scrollTo(0, 0));
    assert(
      await page.evaluate(
        () =>
          document.querySelector('.hero-marker').getAnimations().length === 0 &&
          getComputedStyle(document.querySelector('.hero-marker')).clipPath === 'none' &&
          document.querySelector('.principles').getAnimations({ subtree: true }).length === 0,
      ),
      `${theme}: marker replayed or the static feature illustrations started animating`,
    );
    cases.push(`${theme}: left-to-right ink, stable layout, hidden-tab pause, one draw`);

    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(origin);
    assert(
      await page
        .locator('.hero-marker')
        .evaluate(
          (marker) =>
            marker.getAnimations().length === 0 && getComputedStyle(marker).clipPath === 'none',
        ),
      `${theme}: reduced motion hid or animated the underline`,
    );
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    assert(
      await page.locator('.hero-marker').evaluate((marker) => marker.getAnimations().length === 0),
      `${theme}: changing motion preference replayed the underline`,
    );
    cases.push(`${theme}: reduced motion is complete and stays still`);
  }

  const noScript = await page
    .context()
    .browser()
    .newContext({
      javaScriptEnabled: false,
      colorScheme: 'dark',
      viewport: { width: 390, height: 844 },
    });
  try {
    const fallback = await noScript.newPage();
    await fallback.goto(origin);
    assert(
      await fallback
        .locator('.hero-marker')
        .evaluate(
          (marker) =>
            marker.getAnimations().length === 0 && getComputedStyle(marker).clipPath === 'none',
        ),
      'Without JavaScript the marker must remain completely visible',
    );
    assert(
      await fallback.locator('.vault-explorer').evaluate((el) => el.open),
      'Without JavaScript the native vault must stay available',
    );
    cases.push('no JavaScript: complete marker and native vault');
  } finally {
    await noScript.close();
  }
  return { status: 'passed', cases: cases.length, checks: cases };
}
