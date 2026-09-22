import assert from 'node:assert/strict';
import { constants } from 'node:fs';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { parseHTML } from 'linkedom';

// Build a published-state candidate in a disposable copy. Never flip the actual
// worktree's release flag, and never let the preview server serve this candidate.
const source = resolve('.');
const candidate = await mkdtemp(join(tmpdir(), 'agent2learn-site-release-'));
const astroPackage = JSON.parse(
  await readFile(join(source, 'node_modules/astro/package.json'), 'utf8'),
);
const astroBin = join(candidate, 'node_modules/astro', astroPackage.bin.astro);

try {
  for (const path of [
    'src',
    'public',
    'astro.config.mjs',
    'ec.config.mjs',
    'tsconfig.json',
    'package.json',
  ]) {
    await cp(join(source, path), join(candidate, path), { recursive: true });
  }
  // Vite must resolve Astro components inside the candidate root. A symlink to
  // the real dependencies mixes compile-cache paths across the two projects.
  // Prefer filesystem clones where supported; ordinary copies are the fallback.
  await cp(join(source, 'node_modules'), join(candidate, 'node_modules'), {
    recursive: true,
    mode: constants.COPYFILE_FICLONE,
  });
  const configPath = join(candidate, 'src/lib/site.ts');
  const config = await readFile(configPath, 'utf8');
  assert.match(config, /published: (?:false|true)/, 'Expected the explicit release setting.');
  await writeFile(configPath, config.replace(/published: (?:false|true)/, 'published: true'));

  const build = spawnSync(process.execPath, [astroBin, 'build', '--force'], {
    cwd: candidate,
    env: {
      ...process.env,
      SITE_URL: 'https://release-preview.invalid',
    },
    encoding: 'utf8',
    maxBuffer: 8 * 1024 * 1024,
  });
  assert.equal(build.status, 0, build.stderr + build.stdout);
  const verify = spawnSync(process.execPath, [join(source, 'scripts/verify-build.mjs')], {
    cwd: candidate,
    encoding: 'utf8',
  });
  assert.equal(verify.status, 0, verify.stderr + verify.stdout);
  const out = join(candidate, 'dist');
  const { document: home } = parseHTML(await readFile(join(out, 'index.html'), 'utf8'));
  const { document: install } = parseHTML(
    await readFile(join(out, 'docs/installation/index.html'), 'utf8'),
  );
  const prompt = await readFile(join(out, 'agent-prompt.txt'), 'utf8');
  for (const document of [home, install]) {
    for (const selector of ['meta[property="og:image"]', 'meta[name="twitter:image"]']) {
      assert.equal(document.querySelectorAll(selector).length, 1);
      assert.equal(
        document.querySelector(selector).getAttribute('content'),
        'https://release-preview.invalid/brand/social-card.png',
      );
    }
    assert.equal(document.querySelector('meta[property="og:image:width"]').content, '1200');
    assert.equal(document.querySelector('meta[property="og:image:height"]').content, '630');
    assert.equal(
      document.querySelector('meta[name="twitter:card"]').content,
      'summary_large_image',
    );
  }
  assert.equal(home.querySelector('.release-pill'), null, 'The hero has no release badge.');
  assert.doesNotMatch(home.querySelector('.install-caption').textContent, /coming soon/);
  assert.equal(install.querySelector('.release-note'), null);
  assert.doesNotMatch(prompt, /RELEASE STATUS|not published yet/);
  assert.match(prompt, /Hand control back to me to run a2l init/);
  assert.match(prompt, /Never fetch excluded licensed resources, upload coursework/);
  assert.match(await readFile(join(out, 'llms.txt'), 'utf8'), /PyPI release: [\d.]+/);
  assert.match(await readFile(join(out, 'sitemap-index.xml'), 'utf8'), /release-preview.invalid/);
  assert.equal(
    home.querySelector('link[rel="canonical"]').getAttribute('href'),
    'https://release-preview.invalid/',
  );

  // Exercise the rendered command, not a separately maintained test command.
  // Stub only the download: no package installation or onboarding can run here.
  if (process.platform !== 'win32') {
    const posixCommand = [...install.querySelectorAll('[role="tabpanel"] pre')]
      .map((pre) => pre.textContent.trim())
      .find((command) => command.includes('/install.sh'));
    assert.ok(posixCommand, 'Expected the rendered macOS/Linux installation command.');
    const stubBin = join(candidate, 'installer-check-bin');
    await mkdir(stubBin);
    await writeFile(
      join(stubBin, 'curl'),
      `#!/bin/sh
if [ "$A2L_TEST_FETCH_FAIL" = "1" ]; then
  printf '%s\\n' 'echo partial-installer-executed'
  exit 22
fi
printf '%s\\n' 'IFS= read -r reply' 'printf "%s\\n" "$reply"'
`,
      { mode: 0o700 },
    );
    const commandEnv = { ...process.env, PATH: `${stubBin}:${process.env.PATH}` };
    const handoff = spawnSync('bash', ['-c', posixCommand], {
      cwd: candidate,
      env: { ...commandEnv, A2L_TEST_FETCH_FAIL: '0' },
      input: 'a2l-stdin-check\n',
      encoding: 'utf8',
      timeout: 5000,
    });
    assert.equal(handoff.status, 0, handoff.stderr);
    assert.equal(
      handoff.stdout.trim(),
      'a2l-stdin-check',
      'The installation command must preserve stdin for interactive setup.',
    );
    const refused = spawnSync('bash', ['-c', posixCommand], {
      cwd: candidate,
      env: { ...commandEnv, A2L_TEST_FETCH_FAIL: '1' },
      encoding: 'utf8',
      timeout: 5000,
    });
    assert.equal(refused.status, 22, 'A failed download must stop the installation command.');
    assert.doesNotMatch(refused.stdout, /partial-installer-executed/);
    console.log(
      'POSIX install command verified: stdin preserved; failed download is not executed.',
    );
  }
  console.log(
    'Published-state build verified: install copy, agent handoff, docs notice, llms index, social images, canonical URL, and sitemap. Actual release setting unchanged.',
  );
} finally {
  await rm(candidate, { recursive: true, force: true });
}
