import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import sharp from 'sharp';

// One editable, font-independent vector master serves both the site and film.
// Explicit dark artwork keeps the gold gold: CSS inversion would turn it blue.
const source = await readFile('src/assets/brand/a2l-waterloo-gold.svg', 'utf8');
assert.match(source, /viewBox="0 0 360 144"/);
assert.match(source, /data-brand-accent="waterloo-gold" fill="#FFD54F"/);
assert.ok(
  !/<(?:image|text|script|foreignObject)\b/.test(source),
  'Use only outlined vector artwork.',
);
const sourceHash = createHash('sha256').update(source).digest('hex');
const geometry = source.slice(source.indexOf('>') + 1, source.lastIndexOf('</svg>')).trim();
const variant = (ink) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 144" data-source-sha256="${sourceHash}">${geometry.replace('fill="currentColor"', `fill="${ink}"`)}</svg>\n`;
const mark = variant('#161616');
const dark = variant('#FFFFFF');
const favicon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" data-source-sha256="${sourceHash}"><rect x=".5" y=".5" width="63" height="63" rx="14" fill="#fff" stroke="#e4e4e7"/><g transform="translate(4 20.8) scale(.155555556)">${geometry.replace('fill="currentColor"', 'fill="#161616"')}</g></svg>\n`;
const icon = await sharp(Buffer.from(favicon)).resize(512, 512).png().toBuffer();
const outputs = new Map([
  ['public/brand/mark.svg', Buffer.from(mark)],
  ['public/brand/mark-dark.svg', Buffer.from(dark)],
  ['public/brand/mark.png', await sharp(Buffer.from(mark)).resize(1440).png().toBuffer()],
  ['public/brand/mark-dark.png', await sharp(Buffer.from(dark)).resize(1440).png().toBuffer()],
  ['public/favicon.svg', Buffer.from(favicon)],
  ['public/brand/icon.png', icon],
  ['../videos/a2l-cinematic/assets/brand/a2l-waterloo-gold.svg', Buffer.from(mark)],
  ['../videos/a2l-cinematic/assets/brand/a2l-waterloo-gold-dark.svg', Buffer.from(dark)],
]);
const check = process.argv.includes('--check');
for (const [path, bytes] of outputs) {
  if (check)
    assert.deepEqual(await readFile(path), bytes, `${path} is stale; run npm run brand:build`);
  else await writeFile(path, bytes);
}
console.log(
  `${check ? 'Verified' : 'Exported'} A2L vector marks, gold-preserving dark variant, favicon, icon and identical film artwork.`,
);
