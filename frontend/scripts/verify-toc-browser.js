// Playwright CLI: run-code --filename scripts/verify-toc-browser.js
// Run in Chromium and WebKit against the built production preview.
async function verifyTocBrowser(page) {
  const origin = await page.evaluate(() => location.origin);
  const engine = page.context().browser().browserType().name();
  const errors = [];
  const onError = (error) => errors.push(error.message);
  page.on('pageerror', onError);
  const cases = [];
  const guides = [
    'vault',
    'introduction',
    'installation',
    'for-agents',
    'sync',
    'study',
    'evidence-scan',
    'commands',
    'authentication',
    'privacy',
    'troubleshooting',
  ];
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const expectCurrent = async (hash, label, includeHidden = false) => {
    try {
      await page.waitForFunction(
        ({ hash, includeHidden }) => {
          const tocs = [...document.querySelectorAll('starlight-toc, mobile-starlight-toc')].filter(
            (toc) => includeHidden || toc.querySelector('nav').getBoundingClientRect().height > 0,
          );
          return (
            tocs.length > 0 &&
            tocs.every((toc) => {
              const current = toc.querySelectorAll('a[aria-current="true"]');
              const display = toc.querySelector('.display-current');
              return (
                current.length === 1 &&
                current[0].hash === hash &&
                (!display || display.textContent === current[0].textContent)
              );
            })
          );
        },
        { hash, includeHidden },
        { timeout: 3000 },
      );
    } catch {
      const state = await page.evaluate(() => ({
        scrollY,
        viewport: innerHeight,
        pageHeight: document.documentElement.scrollHeight,
        current: [...document.querySelectorAll('starlight-toc a[aria-current="true"]')].map(
          (link) => link.hash,
        ),
      }));
      throw new Error(`${label}: expected ${hash}; ${JSON.stringify(state)}`);
    }
  };
  const scrollTop = async () => {
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    await expectCurrent('#_top', 'Return to overview');
  };

  try {
    for (const width of [1440, 390]) {
      for (const theme of ['dark', 'light']) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
        await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' });
        await page.evaluate((theme) => localStorage.setItem('starlight-theme', theme), theme);
        for (const slug of guides) {
          const label = `${slug} ${width}px ${theme}`;
          const url = `${origin}/docs/${slug}/`;
          await page.goto(url);
          await page.evaluate(() => document.fonts.ready);
          await expectCurrent('#_top', `${label} initial`);
          const links = await page
            .locator('starlight-toc a')
            .evaluateAll((links) =>
              links.map((link) => ({ hash: link.hash, text: link.textContent })),
            );
          const last = links.at(-1);
          assert(last && links.length > 1, `${label}: missing section links`);

          // A short final section cannot reach Starlight's top reading band.
          await page.evaluate(() =>
            window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }),
          );
          await expectCurrent(last.hash, `${label} page bottom`, true);
          await scrollTop();

          const toc = page.locator(width === 390 ? 'mobile-starlight-toc' : 'starlight-toc');
          if (width === 390) await toc.locator('summary').click();
          await toc.getByRole('link', { name: last.text, exact: true }).click();
          await expectCurrent(last.hash, `${label} final link click`);
          if (width === 390) {
            assert(
              !(await toc.locator('details').evaluate((details) => details.open)),
              `${label}: anchor click left the mobile menu open`,
            );
          }

          await page.goto(`${url}${last.hash}`);
          await page.evaluate(() => document.fonts.ready);
          await expectCurrent(last.hash, `${label} direct fragment`);
          await scrollTop();

          // Scrolling back into a normal section must release the final selection.
          await page.evaluate((hash) => {
            document.getElementById(decodeURIComponent(hash.slice(1))).scrollIntoView();
          }, links[1].hash);
          await expectCurrent(links[1].hash, `${label} earlier section`);
          cases.push(label);
        }
      }
    }

    await page.setViewportSize({ width: 1440, height: 960 });
    await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'no-preference' });
    await page.evaluate(() => localStorage.setItem('starlight-theme', 'dark'));
    await page.goto(`${origin}/docs/vault/`);
    await page.evaluate(() => document.fonts.ready);
    await page.locator('starlight-toc a').last().click();
    await expectCurrent('#revisions-and-your-own-work', 'Final link with normal motion');
    await page.evaluate(() => window.scrollBy({ top: -64, behavior: 'instant' }));
    await page.waitForFunction(() => {
      const current = document.querySelector('starlight-toc a[aria-current="true"]');
      return current && current.hash !== '#revisions-and-your-own-work';
    });
    await page.evaluate(() =>
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }),
    );
    await expectCurrent('#revisions-and-your-own-work', 'Return across the bottom boundary');
    await page.waitForTimeout(350);
    await expectCurrent('#revisions-and-your-own-work', 'Settled end-of-page selection', true);
    await page.screenshot({ path: `output/playwright/toc-${engine}-after-dark.png` });
    cases.push('normal motion and a small upward scroll across the bottom boundary');

    await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' });
    await page.evaluate(() => localStorage.setItem('starlight-theme', 'light'));
    await page.goto(`${origin}/docs/vault/#revisions-and-your-own-work`);
    await page.evaluate(() => document.fonts.ready);
    // Resize from the real bottom. WebKit's scroll clamping can leave the new,
    // taller viewport within main's responsive trailing whitespace.
    await page.locator('starlight-toc a').last().click();
    await expectCurrent('#revisions-and-your-own-work', 'Before resizing');
    await page.setViewportSize({ width: 1440, height: 1200 });
    await expectCurrent('#revisions-and-your-own-work', 'Resize while at the end');
    await page.waitForTimeout(350); // Starlight recreates its observer after resizing.
    await expectCurrent('#revisions-and-your-own-work', 'Settled resize observer');
    await page.screenshot({ path: `output/playwright/toc-${engine}-after-light.png` });
    cases.push('resize at the end');

    // A page that fits entirely in the viewport should still open at Overview.
    await page.setViewportSize({ width: 1440, height: 12000 });
    await page.goto(`${origin}/docs/introduction/`);
    await expectCurrent('#_top', 'Non-scrollable page');
    cases.push('non-scrollable page starts at Overview');
    assert(errors.length === 0, `Browser errors: ${errors.join('; ')}`);
    return { status: 'passed', cases: cases.length, checked: cases, errors };
  } finally {
    page.off('pageerror', onError);
  }
}
