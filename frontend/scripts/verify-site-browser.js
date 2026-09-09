// Playwright CLI: run-code --filename scripts/verify-site-browser.js
// Run against the production preview so the real Pagefind index is available.
async function verifySiteBrowser(page) {
  const origin = await page.evaluate(() => location.origin);
  const errors = [];
  const onError = (error) => errors.push(error.message);
  page.on('pageerror', onError);
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const cases = [];
  const ready = async () => {
    await page.evaluate(async () => {
      await document.fonts.ready;
      await Promise.all([...document.images].map((image) => image.decode()));
    });
  };
  const audit = async (label) => {
    // Expressive Code installs keyboard scrolling during idle time.
    await page.waitForFunction(() =>
      [...document.querySelectorAll('.expressive-code pre')].every(
        (pre) => pre.scrollWidth <= pre.clientWidth || pre.tabIndex === 0,
      ),
    );
    await page.addScriptTag({ path: 'node_modules/axe-core/axe.min.js' });
    const violations = await page.evaluate(async () => {
      const result = await window.axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
      });
      return result.violations.map(({ id, nodes }) => ({
        id,
        elements: nodes.map(({ target }) => target),
      }));
    });
    assert(violations.length === 0, `${label}: accessibility ${JSON.stringify(violations)}`);
  };
  const setTheme = async (theme) => {
    await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' });
    await page.evaluate((theme) => localStorage.setItem('starlight-theme', theme), theme);
  };

  for (const width of [320, 390, 768, 1440, 1920]) {
    for (const theme of ['light', 'dark']) {
      const label = `home ${width}px ${theme}`;
      await page.setViewportSize({ width, height: 960 });
      await setTheme(theme);
      await page.goto(origin);
      await ready();
      assert(
        (await page.locator('.release-pill').count()) === 0,
        `${label}: release badge returned`,
      );
      assert(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        `${label}: horizontal overflow`,
      );
      assert(
        (await page.locator('.vault-explorer').evaluate((el) => el.open)) === width > 760,
        `${label}: incorrect initial vault disclosure`,
      );
      if (width <= 760) {
        assert(
          await page.locator('.mobile-source-excerpt').isVisible(),
          `${label}: collapsed answer lost its source excerpt`,
        );
      }
      await page.getByRole('button', { name: 'Linear models.md:4–5' }).click();
      assert(
        await page.locator('#choose-linear').isChecked(),
        `${label}: citation did not select its lecture`,
      );
      assert(
        await page
          .locator('#source-linear [data-line="4"]')
          .evaluate((el) => el === document.activeElement),
        `${label}: citation did not focus the source line`,
      );
      assert(
        await page.locator('#source-linear').isVisible(),
        `${label}: citation source is hidden`,
      );
      assert(
        await page.locator('.mobile-source-excerpt').isHidden(),
        `${label}: expanded source duplicates its compact excerpt`,
      );
      assert(
        (await page.locator('.citation-hint').textContent()) ===
          'Lines 4–5 highlighted in the source.',
        `${label}: citation status is missing`,
      );
      await page.locator('label[for="choose-index"]').click();
      assert(
        await page.locator('#source-index').isVisible(),
        `${label}: index could not be opened`,
      );
      assert(
        (await page.locator('a2l-vault').getAttribute('data-cited')) === null,
        `${label}: a different file kept a stale citation`,
      );
      await page.locator('#choose-index').focus();
      await page.keyboard.press('ArrowRight');
      assert(
        await page.locator('#choose-linear').isChecked(),
        `${label}: file navigation is not keyboard operable`,
      );
      if (width <= 760) {
        await page.getByRole('button', { name: 'Back to answer' }).click();
        assert(
          !(await page.locator('.vault-explorer').evaluate((el) => el.open)),
          `${label}: return left the explorer open`,
        );
        assert(
          await page
            .locator('[data-open-citation]')
            .evaluate((el) => el === document.activeElement),
          `${label}: return lost keyboard focus`,
        );
        assert(
          await page.locator('.mobile-source-excerpt').isVisible(),
          `${label}: return did not restore the source excerpt`,
        );
      }
      await audit(label);
      cases.push(label);
    }
  }

  // A mobile disclosure choice survives a trip through the desktop layout.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(origin);
  await page.getByText('Explore the full vault', { exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => document.querySelector('.vault-explorer').open);
  assert(
    await page.locator('.vault-explorer').evaluate((el) => el.open),
    'Resize lost the expanded mobile file view',
  );
  assert(
    await page.locator('.mobile-source-excerpt').isHidden(),
    'Resize duplicated the source excerpt in the open explorer',
  );
  await page.getByRole('button', { name: 'Back to answer' }).click();
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => !document.querySelector('.vault-explorer').open);
  assert(
    !(await page.locator('.vault-explorer').evaluate((el) => el.open)),
    'Resize reopened the collapsed mobile file view',
  );
  assert(
    await page.locator('.mobile-source-excerpt').isVisible(),
    'Resize hid the collapsed source excerpt',
  );
  cases.push('mobile disclosure survives resize');

  // Exercise the actual clipboard action while keeping browser permissions out
  // of the regression. Compare the copied prompt with its public text endpoint.
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto(origin);
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text) => {
          if (window.__rejectCopy) throw new Error('Test clipboard refusal');
          window.__copiedText = text;
        },
      },
    });
  });
  await page.locator('.quick-install button').click();
  assert(
    (await page.evaluate(() => window.__copiedText)) === 'uv tool install agent2learn',
    'Install command copy is incorrect',
  );
  await page.getByRole('button', { name: 'Copy agent prompt', exact: true }).click();
  assert(
    (await page.locator('.agent-prompt .copy-feedback').textContent()) ===
      'Prompt copied. Paste it into your coding agent to get started.',
    'Prompt copy did not explain the next step',
  );
  assert(
    await page.evaluate(
      async () =>
        window.__copiedText.trim() === (await (await fetch('/agent-prompt.txt')).text()).trim(),
    ),
    'Copied prompt differs from the shared prompt',
  );
  await page.getByText('Read the full prompt', { exact: true }).click();
  assert(await page.locator('.prompt-text').isVisible(), 'Full prompt expansion is unavailable');
  await page.evaluate(() => {
    window.__rejectCopy = true;
  });
  await page.getByRole('button', { name: 'Copy agent prompt', exact: true }).click();
  assert(
    await page.locator('.agent-prompt .copy-error').isVisible(),
    'Clipboard failure did not offer manual copying',
  );
  cases.push('installation and full agent prompt copy, expansion and recovery');

  for (const width of [320, 1440]) {
    for (const theme of ['light', 'dark']) {
      await page.setViewportSize({ width, height: 960 });
      await setTheme(theme);
      for (const slug of ['introduction', 'installation', 'for-agents', 'commands', 'study']) {
        const label = `docs/${slug} ${width}px ${theme}`;
        await page.goto(`${origin}/docs/${slug}/`);
        await ready();
        assert(
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          `${label}: horizontal overflow`,
        );
        assert(
          await page.getByRole('button', { name: 'Copy page', exact: true }).isVisible(),
          `${label}: Copy page is missing`,
        );
        await page.evaluate(() =>
          Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: {
              writeText: async (text) => {
                window.__copiedText = text;
              },
            },
          }),
        );
        await page.getByRole('button', { name: 'Copy page', exact: true }).click();
        assert(
          await page.evaluate(
            () =>
              window.__copiedText.startsWith('# ') &&
              window.__copiedText.length > 500 &&
              !/<(?:CopyButton|CitationExample)|import CitationExample/.test(window.__copiedText),
          ),
          `${label}: Copy page lost its complete readable content`,
        );
        if (slug === 'study') {
          const lines = await page.locator('.citation-guide-lines code').allTextContents();
          assert(
            lines.join(' ') === 'A feasible solution satisfies every constraint in the model.',
            `${label}: source excerpt differs from the homepage example`,
          );
          assert(
            await page.evaluate(
              () =>
                window.__copiedText.includes('content/Week 3/Linear models.md:4–5') &&
                window.__copiedText.includes('4  A feasible solution satisfies every') &&
                window.__copiedText.includes('5  constraint in the model.') &&
                window.__copiedText.includes('**Line range:**'),
            ),
            `${label}: Copy page lost the citation example or its explanation`,
          );
        }
        if (slug === 'installation') {
          for (const tab of ['macOS / Linux', 'Windows', 'Already have uv']) {
            await page.getByRole('tab', { name: tab, exact: true }).click();
            assert(
              (await page
                .getByRole('tab', { name: tab, exact: true })
                .getAttribute('aria-selected')) === 'true',
              `${label}: install method tab did not change`,
            );
            const panel = page.getByRole('tabpanel', { name: tab, exact: true });
            const command = await panel.locator('pre').innerText();
            await panel.getByRole('button', { name: 'Copy to clipboard', exact: true }).click();
            assert(
              (await page.evaluate(() => window.__copiedText)).trim() === command.trim(),
              `${label}: ${tab} copied a different installation command`,
            );
          }
        }
        await audit(label);
        cases.push(label);
      }
    }
  }

  for (const width of [320, 1440]) {
    for (const theme of ['light', 'dark']) {
      const label = `demo placeholder ${width}px ${theme}`;
      await page.setViewportSize({ width, height: 900 });
      await setTheme(theme);
      const mediaRequests = [];
      const onRequest = (request) => {
        if (request.url() === `${origin}/brand/demo-poster.png`) mediaRequests.push(request.url());
      };
      page.on('request', onRequest);
      await page.goto(origin);
      await ready();
      assert(mediaRequests.length === 0, `${label}: poster loaded before opening the dialog`);
      await page.getByRole('button', { name: 'Preview the demo', exact: true }).click();
      const dialog = page.getByRole('dialog');
      assert(await dialog.isVisible(), `${label}: dialog did not open`);
      await dialog.locator('img').evaluate((image) => image.decode());
      assert(
        await dialog.getByText('Demo placeholder', { exact: true }).isVisible(),
        `${label}: placeholder is not labeled`,
      );
      assert(
        (await dialog.locator('video').count()) === 0,
        `${label}: placeholder pretends to play a video`,
      );
      assert(mediaRequests.length === 1, `${label}: poster was not loaded on demand`);
      assert(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        `${label}: horizontal overflow`,
      );
      await audit(label);
      await page.keyboard.press('Escape');
      assert(await dialog.isHidden(), `${label}: Escape did not close the dialog`);
      assert(
        await page.locator('[data-open-demo]').evaluate((el) => el === document.activeElement),
        `${label}: closing lost keyboard focus`,
      );
      // Native dialog close events are queued after the open attribute clears.
      await page.waitForFunction(() => !document.querySelector('.video-placeholder-art img'));
      await page.getByRole('button', { name: 'Preview the demo', exact: true }).click();
      await page.getByRole('button', { name: 'Close demo', exact: true }).click();
      assert(await dialog.isHidden(), `${label}: close button did not work`);
      page.off('request', onRequest);
      cases.push(label);
    }
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto(origin);
  await page.evaluate(() => {
    window.__storyMotions = 0;
    document.addEventListener('animationstart', (event) => {
      if (event.target.closest('a2l-feature-story')) window.__storyMotions++;
    });
  });
  await page.locator('.principles').scrollIntoViewIfNeeded();
  await page.waitForFunction(() => window.__storyMotions === 2);
  await page.evaluate(() =>
    Promise.all(document.getAnimations().map((animation) => animation.finished)),
  );
  await page.locator('#hero-title').scrollIntoViewIfNeeded();
  await page.locator('.principles').scrollIntoViewIfNeeded();
  assert(
    (await page.evaluate(() => window.__storyMotions)) === 2,
    'Illustration motion repeated on reentry',
  );
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(origin);
  await page.locator('.principles').scrollIntoViewIfNeeded();
  assert(
    await page
      .locator('.story-document-accent, .story-revision-current')
      .evaluateAll((elements) =>
        elements.every(
          (el) =>
            getComputedStyle(el).animationName === 'none' && getComputedStyle(el).opacity === '1',
        ),
      ),
    'Reduced motion must show the final illustrations without animation',
  );
  cases.push('illustration motion plays once and respects reduced motion');

  await page.locator('.footer-links').getByRole('link', { name: 'Docs', exact: true }).click();
  assert(
    (await page.locator('h1').textContent()).trim() === 'A course vault your agent can read.',
    'Footer Docs did not open the actual guide',
  );
  await page.goto(origin);
  const llmsResponse = page.waitForResponse((response) => response.url() === `${origin}/llms.txt`);
  await page.locator('.footer-links').getByRole('link', { name: 'llms.txt', exact: true }).click();
  const response = await llmsResponse;
  assert(
    response.status() === 200 && response.headers()['content-type'].includes('text/plain'),
    'Footer llms.txt is not a text resource',
  );
  const index = await response.text();
  assert(
    index.startsWith('# Agent2Learn') && (index.match(/\]\(\/docs\//g) ?? []).length === 11,
    'Footer llms.txt is missing its project or guides',
  );
  cases.push('footer Docs and llms.txt open populated resources');

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto(`${origin}/docs/introduction/`);
  await page.getByRole('button', { name: 'Search', exact: false }).click();
  await page.getByRole('textbox', { name: 'Search docs', exact: true }).fill('authentication');
  await page.locator('.pagefind-ui__result-link').first().waitFor();
  assert(
    (await page.locator('.pagefind-ui__result-link').count()) > 0,
    'Production documentation search returned no results',
  );
  const firstResult = page.locator('.pagefind-ui__result').first();
  assert(
    (await firstResult.locator('.pagefind-ui__result-link').first().textContent()).trim() ===
      'Authentication',
    'Search did not find the authentication guide',
  );
  assert(
    !(await firstResult.textContent()).includes('Copy page'),
    'Search indexed the Copy page action as article content',
  );
  await page.keyboard.press('Escape');
  cases.push('production documentation search');
  page.off('pageerror', onError);
  assert(errors.length === 0, `Browser errors: ${errors.join('; ')}`);
  return { status: 'passed', cases: cases.length, checks: cases, browserErrors: errors };
}
