// Run with Playwright CLI's `run-code --filename` against the local production
// preview. The image reuses the actual synthetic vault HTML and bundled fonts.
async function renderSocialCard(page) {
  const origin = await page.evaluate(() => location.origin);
  await page.setViewportSize({ width: 1200, height: 630 });
  await page.goto(origin);
  const { styles, vault } = await page.evaluate(() => ({
    styles: [...document.querySelectorAll('link[rel="stylesheet"]')].map((link) => link.href),
    vault: document.querySelector('.vault-window').outerHTML,
  }));
  await page.setContent(`<!doctype html>
    <html lang="en" data-theme="light">
      <head>
        <meta charset="utf-8">
        <link rel="icon" href="${origin}/favicon.svg" type="image/svg+xml">
        ${styles.map((href) => `<link rel="stylesheet" href="${href}">`).join('')}
        <style>
          body { margin: 0; background: #f7f8fa; }
          .social-card {
            width: 1200px; height: 630px; position: relative; overflow: hidden;
            background: var(--canvas); color: var(--ink);
          }
          .social-brand {
            position: absolute; left: 52px; top: 44px;
            display: flex; align-items: center; gap: 12px;
            font: 650 25px/1.2 var(--font-sans);
          }
          .social-copy { position: absolute; left: 52px; top: 174px; width: 422px; }
          .social-title { font: 650 54px/1.08 var(--font-sans); letter-spacing: -0.04em; text-wrap: initial; }
          .social-title span { display: block; color: var(--hero-secondary); }
          .social-description {
            margin-top: 27px; max-width: 370px;
            font: 18px/1.65 var(--font-sans); color: var(--muted);
          }
          .social-footer {
            position: absolute; left: 52px; bottom: 48px;
            font: 11px/1.5 var(--font-mono); color: var(--muted);
          }
          .social-preview { position: absolute; left: 520px; top: 126px; width: 628px; }
          .social-preview .vault-body { grid-template-columns: minmax(0, 1fr); min-height: 374px; }
          .social-preview .explorer-content { grid-template-columns: 174px minmax(0, 1fr); }
          .social-preview .citation-example { display: none; }
          .social-preview .file-tree { padding: 17px 8px; }
          .social-preview .file-option label { padding-left: 8px; font-size: 10px; }
          .social-preview .tree-course { padding-left: 8px; font-size: 11px; }
          .social-preview .original-file { padding-left: 8px; flex-wrap: wrap; font-size: 9px; }
          .social-preview .tree-note { margin: 22px 0 0 8px; font-size: 10px; }
          .social-preview .source-toolbar { padding-inline: 14px; font-size: 10px; }
          .social-preview .source-line { gap: 10px; }
          .social-preview .source-line::before { animation: none; }
          .social-preview .line-number { flex-basis: 28px; }
          .social-caption {
            margin-top: 13px; text-align: right;
            font: 11px/1.5 var(--font-sans); color: var(--muted);
          }
        </style>
      </head>
      <body>
        <main class="social-card">
          <div class="social-brand"><img src="${origin}/brand/mark.svg" width="88" height="34" alt="">Agent2Learn</div>
          <div class="social-copy">
            <h1 class="social-title">Your courses.<span>Ready for<br>your agent.</span></h1>
            <p class="social-description">Local course files your coding agent can read and cite.</p>
          </div>
          <div class="social-preview"><a2l-vault data-cited>${vault}</a2l-vault><p class="social-caption">Synthetic course example · Sources you can open.</p></div>
          <div class="social-footer">OPEN SOURCE · BUILT FOR WATERLOO</div>
        </main>
      </body>
    </html>`);
  await page.evaluate(async () => {
    document.querySelector('#choose-linear').checked = true;
    document.querySelector('.vault-explorer').open = true;
    document.querySelector('#source-linear').classList.add('citation-active');
    await document.fonts.ready;
    await Promise.all([...document.images].map((img) => img.decode()));
  });
  await page.screenshot({ path: 'public/brand/social-card.png', scale: 'css' });
  await page.goto(origin);
}
