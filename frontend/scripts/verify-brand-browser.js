// Playwright CLI: run-code --filename scripts/verify-brand-browser.js
// Exercises the real built site. Catches square squeezing, missing dark-mode
// treatment, broken image loads and mobile header collisions after a rebrand.
async function verifyBrandBrowser(page) {
  const origin = await page.evaluate(() => location.origin);
  const rows = [];
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  for (const route of ['/', '/docs/introduction/']) {
    for (const width of [320, 375, 768, 1440]) {
      for (const theme of ['light', 'dark']) {
        await page.setViewportSize({ width, height: 960 });
        await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: theme });
        // Set the preference before navigation so the actual theme initializer
        // and docs selector agree, instead of merely repainting the DOM.
        await page.evaluate((theme) => localStorage.setItem('starlight-theme', theme), theme);
        await page.goto(`${origin}${route}`);
        await page.evaluate(async () => {
          await document.fonts.ready;
          await Promise.all([...document.images].map((image) => image.decode()));
        });
        const result = await page.evaluate(() => {
          const marks = [...document.querySelectorAll('img.brand-mark')];
          const brand = document.querySelector('.site-header .brand, .docs-brand');
          const b = brand.getBoundingClientRect();
          const nav = document.querySelector('.site-header nav');
          return {
            marks: marks.map((mark) => {
              const box = mark.getBoundingClientRect();
              return {
                ratio: box.width / box.height,
                width: box.width,
                loaded: mark.complete && mark.naturalWidth > 0,
                filter: getComputedStyle(mark).filter,
                onCharcoal: Boolean(mark.closest('.setup-section')),
              };
            }),
            overflow: document.documentElement.scrollWidth > innerWidth,
            brandInFrame: b.left >= 0 && b.right <= innerWidth,
            navigationGap: nav ? nav.getBoundingClientRect().left - b.right : null,
          };
        });
        const label = `${route} ${width}px ${theme}`;
        if (result.marks.length !== (route === '/' ? 4 : 1))
          throw new Error(`${label}: missing mark`);
        for (const mark of result.marks) {
          if (!mark.loaded || !Number.isFinite(mark.ratio) || mark.ratio < 2.45 || mark.ratio > 2.8)
            throw new Error(`${label}: missing or squeezed artwork ${JSON.stringify(mark)}`);
          if (mark.filter !== (theme === 'dark' || mark.onCharcoal ? 'invert(1)' : 'none'))
            throw new Error(`${label}: invisible/wrong-theme mark`);
        }
        if (
          result.overflow ||
          !result.brandInFrame ||
          (result.navigationGap !== null && result.navigationGap < 8)
        )
          throw new Error(`${label}: layout collision ${JSON.stringify(result)}`);
        if (width === 320 || width === 1440) {
          await page.screenshot({
            path: `output/playwright/brand-${route === '/' ? 'home' : 'docs'}-${width}-${theme}.png`,
          });
        }
        rows.push({ route, width, theme, ...result });
      }
    }
  }
  if (errors.length) throw new Error(errors.join('\n'));
  return { status: 'passed', cases: rows.length, errors, rows };
}
