import { readdir, readFile, stat } from 'node:fs/promises';
import { resolve, relative, join } from 'node:path';
import { parseHTML } from 'linkedom';

// Check the generated artifact, including Starlight navigation and MDX output.
// This catches broken links that neither TypeScript nor a successful render can find.
const root = resolve('dist');
const origin = 'https://build.invalid';
const documents = new Map();
const failures = [];

// Check the exported image itself, not only the dimensions written in meta tags.
const socialImage = await readFile(join(root, 'brand/social-card.png'));
const pngSignature = '89504e470d0a1a0a'; // pragma: allowlist secret (public PNG signature)
if (
  socialImage.subarray(0, 8).toString('hex') !== pngSignature ||
  socialImage.readUInt32BE(16) !== 1200 ||
  socialImage.readUInt32BE(20) !== 630
)
  failures.push('brand/social-card.png: expected a 1200 by 630 PNG');

async function walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const file = join(dir, entry.name);
    if (entry.isDirectory()) await walk(file);
    else if (file.endsWith('.html')) {
      const { document } = parseHTML(await readFile(file, 'utf8'));
      documents.set(file, document);
    }
  }
}

async function existingTarget(pathname) {
  const location = resolve(root, '.' + decodeURIComponent(pathname));
  if (location !== root && !location.startsWith(root + '/')) return undefined;
  for (const candidate of [location, join(location, 'index.html')]) {
    if (
      await stat(candidate)
        .then((s) => s.isFile())
        .catch(() => false)
    )
      return candidate;
  }
  return undefined;
}

await walk(root);
let checked = 0;
for (const [file, document] of documents) {
  const path = '/' + relative(root, file).replace(/index\.html$/, '');
  if (!document.querySelector('title')?.textContent?.trim())
    failures.push(`${path}: missing title`);
  if (document.querySelectorAll('h1').length !== 1)
    failures.push(`${path}: expected one main heading`);
  const codeLabels = new Set();
  // A wide wordmark in the old square slot is visibly compressed. Check the
  // emitted component on every route, not just its source or the home page.
  const marks = document.querySelectorAll('img.brand-mark');
  if (!marks.length) failures.push(`${path}: missing shared brand mark`);
  for (const mark of marks) {
    const ratio = Number(mark.getAttribute('width')) / Number(mark.getAttribute('height'));
    if (!Number.isFinite(ratio) || ratio < 2.45 || ratio > 2.8)
      failures.push(`${path}: A2L wordmark must retain its wide optical proportions`);
    if (mark.getAttribute('alt') !== '' || mark.getAttribute('aria-hidden') !== 'true')
      failures.push(`${path}: adjacent brand name already labels this decorative mark`);
  }
  for (const block of document.querySelectorAll('.expressive-code pre')) {
    const label = block.getAttribute('aria-label');
    if (!label || codeLabels.has(label))
      failures.push(`${path}: code examples need distinct accessible names`);
    codeLabels.add(label);
  }
  for (const el of document.querySelectorAll('[href], [src]')) {
    const value = el.getAttribute('href') ?? el.getAttribute('src');
    if (!value || value.startsWith('data:')) continue;
    const url = new URL(value, origin + path);
    if (url.origin !== origin) continue;
    checked++;
    const target = await existingTarget(url.pathname);
    if (!target) {
      failures.push(`${path}: missing ${value}`);
      continue;
    }
    if (url.hash && documents.has(target)) {
      const id = decodeURIComponent(url.hash.slice(1));
      if (id && !documents.get(target).getElementById(id))
        failures.push(`${path}: missing anchor ${value}`);
    }
  }
}

for (const file of ['llms.txt', 'agent-prompt.txt']) {
  const content = await readFile(join(root, file), 'utf8');
  if (!content.trim()) failures.push(`${file}: empty agent resource`);
}

const home = documents.get(join(root, 'index.html'));
const footerLinks = [...home.querySelectorAll('.footer-links a')].map((link) => [
  link.textContent.trim(),
  link.getAttribute('href'),
]);
const expectedFooter = [
  ['Docs', '/docs/introduction/'],
  ['llms.txt', '/llms.txt'],
  ['GitHub', 'https://github.com/ManagementMO/agent2learn'],
  ['Apache-2.0', 'https://github.com/ManagementMO/agent2learn/blob/main/LICENSE'],
];
if (JSON.stringify(footerLinks) !== JSON.stringify(expectedFooter))
  failures.push(
    'Homepage footer: expected the documentation, agent index, repository, and license destinations',
  );

// Every guide must be discoverable through the agent index, and every local
// index link must resolve to real generated content, not a fallback page.
const llms = await readFile(join(root, 'llms.txt'), 'utf8');
const indexedGuides = new Set();
for (const [, href] of llms.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)) {
  const url = new URL(href, origin);
  if (url.origin !== origin) continue;
  const target = await existingTarget(url.pathname);
  if (!target) failures.push(`llms.txt: missing ${href}`);
  else if (url.pathname.startsWith('/docs/')) indexedGuides.add(target);
}
for (const file of documents.keys()) {
  if (file.startsWith(join(root, 'docs') + '/') && !indexedGuides.has(file))
    failures.push(`llms.txt: guide absent from index: ${relative(root, file)}`);
}
if (!llms.startsWith('# Agent2Learn\n') || !indexedGuides.size)
  failures.push('llms.txt: expected a project description and a populated documentation index');

if (failures.length) {
  console.error(failures.join('\n'));
  process.exitCode = 1;
} else {
  console.log(
    `Verified ${documents.size} HTML pages, ${checked} internal links/assets, all four footer destinations, ${indexedGuides.size} indexed guides, and the setup prompt.`,
  );
}
