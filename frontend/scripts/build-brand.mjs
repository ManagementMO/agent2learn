import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import sharp from 'sharp';

// The approved film artwork is the master, not a font approximation or a new
// drawing. Only transparent padding and export resolution change here.
const source = await readFile('src/assets/brand/a2l-source.png');
const sourceHash = 'ddbd02a881678ea3e1abb9fc9476d6253a1ebfb06fed788cc59f9acaf1b63f0d'; // pragma: allowlist secret -- public artwork SHA-256
assert.equal(
  createHash('sha256').update(source).digest('hex'),
  sourceHash,
  'The approved A2L master changed; review a new identity before replacing it.',
);
const artwork = await sharp(source)
  .extract({ left: 149, top: 164, width: 1450, height: 561 })
  .resize({ width: 768 })
  .png({ compressionLevel: 9 })
  .toBuffer();
const image = `data:image/png;base64,${artwork.toString('base64')}`;
// Self-contained SVGs work as native images and browser favicons. They embed
// the approved raster artwork; these are not represented as vector drawings.
const mark = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1450 561" data-source-sha256="${sourceHash}"><image width="1450" height="561" href="${image}"/></svg>\n`;
const favicon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" data-source-sha256="${sourceHash}"><rect x=".5" y=".5" width="63" height="63" rx="14" fill="#fff" stroke="#e4e4e7"/><image x="4" y="21.167" width="56" height="21.666" href="${image}"/></svg>\n`;
const icon = await sharp(Buffer.from(favicon)).resize(512, 512).png().toBuffer();
const outputs = new Map([
  ['public/brand/mark.svg', Buffer.from(mark)],
  ['public/favicon.svg', Buffer.from(favicon)],
  ['public/brand/icon.png', icon],
]);
const check = process.argv.includes('--check');
for (const [path, bytes] of outputs) {
  if (check)
    assert.deepEqual(await readFile(path), bytes, `${path} is stale; run npm run brand:build`);
  else await writeFile(path, bytes);
}
console.log(
  `${check ? 'Verified' : 'Exported'} A2L wordmark, favicon and 512px icon from the pinned approved master.`,
);
