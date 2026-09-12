import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';

// The pre-Disclosure edit remains available as a historical picture audit.
// Approved visual revisions must not turn the current soundtrack gate into a
// permanent failure: default checks sound, timing, provenance and shared brand.
// --original-picture additionally enforces the original audio-only edit scope.
const baseline = 'dc83d51369cca5b2bc65c6b8e576a45f3049f0bc';
const approvedAudio = '1bd497f85d85424550e8fdd4ebf442aaa1f588b9'; // pragma: allowlist secret -- public approved soundtrack commit SHA
const originalPicture = process.argv.includes('--original-picture');
const previous = path => execFileSync('git', ['show', `${baseline}:videos/a2l-cinematic/${path}`]);
const json = async path => JSON.parse(await readFile(path, 'utf8'));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const cues = await json('src/launchflow-cues.json');
const oldCues = JSON.parse(previous('src/launchflow-cues.json'));
const approvedCues = JSON.parse(execFileSync('git', ['show', `${approvedAudio}:videos/a2l-cinematic/src/launchflow-cues.json`]));
assert.deepEqual(cues.music, approvedCues.music, 'Preserve the exact approved Disclosure edit');
assert.deepEqual(cues.musicEnvelope, approvedCues.musicEnvelope, 'Preserve the approved listening level and ducking');
assert.equal(cues.music.label, 'Disclosure — Expressing What Matters');
assert.equal(cues.music.sourceStart, 0, 'Use the opening the user selected');
assert.equal(cues.music.playbackRate, 1, 'Keep the original pitch and speed');
assert.equal(cues.music.rightsStatus, 'local-audition-only; public-release clearance not established');
assert.equal(cues.music.sourceUrl, 'https://www.youtube.com/watch?v=nXOSgekiAJc');
assert.notEqual(cues.audioPrefix, oldCues.audioPrefix, 'Preserve the old audio files');
assert.notEqual(cues.exportPrefix, oldCues.exportPrefix, 'Do not target an older export');
const audioOnlyKeys = new Set(['music', 'musicEnvelope', 'audioPrefix', 'exportPrefix']);
const pictureAndFoley = value => Object.fromEntries(Object.entries(value).filter(([key]) => !audioOnlyKeys.has(key)));
assert.deepEqual(pictureAndFoley(cues), pictureAndFoley(oldCues), 'All picture and Foley timing/parameters stay unchanged');
for (const path of ['src/icons.svg', 'src/brand-variant.json']) {
  assert.deepEqual(await readFile(path), previous(path), `Approved icon/brand unchanged: ${path}`);
}
const pictureOnly = html => html
  .replace(/<audio\b[^>]*>[\s\S]*?<\/audio>/g, '')
  .replace(/<script>window\.__A2L_CUES=[\s\S]*?<\/script>/g, '');
const html = await readFile('index.html', 'utf8');
if (originalPicture) {
  for (const path of ['src/launchflow-motion.js', 'src/launchflow.css', 'src/launchflow.html.template', 'white.css']) {
    assert.deepEqual(await readFile(path), previous(path), `Original audio-only edit picture unchanged: ${path}`);
  }
  assert.equal(pictureOnly(html), pictureOnly(previous('index.html').toString()), 'Original compiled picture is unchanged');
}
const audioTags = [...html.matchAll(/<audio\b[^>]*>/g)].map(match => match[0]);
assert.equal(audioTags.length, 3, 'One bed and two Foley stems, no doubled music');
const bedTag = audioTags.find(tag => tag.includes('id="music-bed"'));
const automation = JSON.parse(bedTag.match(/data-automation="([^"]+)"/)[1].replaceAll('&quot;', '"').replaceAll('&amp;', '&'));
assert.deepEqual(automation, {version: 1, lanes: [{target: 'volume', points: cues.musicEnvelope.map(([t, v]) => ({t, v}))}]});
assert.deepEqual(cues.musicEnvelope[0], [0, 0]);
assert.deepEqual(cues.musicEnvelope.at(-1), [cues.duration, 0]);
for (let i = 0; i < cues.musicEnvelope.length; i++) {
  const [time, volume] = cues.musicEnvelope[i];
  assert.ok(Number.isFinite(time) && Number.isFinite(volume) && volume >= 0 && volume <= 1);
  if (i) assert.ok(time > cues.musicEnvelope[i - 1][0], 'Ordered native volume automation');
}
const meta = await json('audio_meta.json');
const oldMeta = await json('.archive/signalflow-launchbeat-audio/audio_meta.json');
assert.deepEqual(meta.events, oldMeta.events, 'All existing input and interface cues unchanged');
assert.deepEqual(meta.automation, cues.musicEnvelope);
assert.equal(meta.music.id, cues.music.id);
assert.equal(meta.music.source_url, cues.music.sourceUrl);
assert.equal(meta.music.rights_status, cues.music.rightsStatus);
assert.match(meta.music.authorship, /Disclosure/);
const source = meta.sources.find(item => item.id === cues.music.id);
assert.ok(source, 'Source provenance is recorded');
assert.equal(source.path, cues.music.path);
assert.equal(source.sha256, hash(await readFile(source.path)), 'Source bytes match provenance');
const probe = path => JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration:stream=sample_rate,channels', '-of', 'json', path], {encoding: 'utf8'}));
const sourceDuration = Number(probe(source.path).format.duration);
assert.ok(sourceDuration >= cues.music.sourceStart + cues.duration * cues.music.playbackRate, 'No source looping or silent padding');
const stems = [];
const approvedStemHashes = {
  bed: '680c849551b2e421d01dfc62ba5275630a9dcf7b9f53dbc1a4b29e0bef333bb0', // pragma: allowlist secret -- approved audio SHA-256
  typing: 'f85327b175b53762e26698d04de17c86c2f1bc1ce2b875127cdc21818c7a57fe', // pragma: allowlist secret -- approved audio SHA-256
  interface: '4092f5591e688a9e8d9d86261d7c491b01234a9593fc9654d6617af5eeae0d35', // pragma: allowlist secret -- approved audio SHA-256
};
for (const stem of ['bed', 'typing', 'interface']) {
  const path = `assets/audio/${cues.audioPrefix}-${stem}.wav`;
  assert.ok(audioTags.some(tag => tag.includes(`src="${path}"`)), `Active ${stem} path`);
  const local = await readFile(path);
  assert.equal(hash(local), approvedStemHashes[stem], `Approved ${stem} audio is byte-identical`);
  const info = probe(path);
  assert.equal(Number(info.format.duration), 17.5);
  assert.equal(Number(info.streams[0].sample_rate), 48000);
  assert.equal(info.streams[0].channels, 2);
  if (stem !== 'bed') assert.deepEqual(local, await readFile(`assets/audio/${oldCues.audioPrefix}-${stem}.wav`), `${stem} Foley byte-identical`);
  assert.ok(execFileSync('git', ['check-ignore', path], {encoding: 'utf8'}).trim(), 'Music and derived audio remain outside public Git');
  const response = await fetch(`http://localhost:3017/api/projects/a2l-cinematic/preview/${path}`);
  assert.equal(response.status, 200, `Studio serves ${stem}`);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), local, `Studio serves fresh ${stem} bytes`);
  stems.push({stem, bytes: local.length, sha256: hash(local)});
}
assert.ok(execFileSync('git', ['check-ignore', source.path], {encoding: 'utf8'}).trim());
assert.ok(meta.reference_peak_dbfs < -1, 'Mix retains sample-peak headroom');
console.log(JSON.stringify({status: 'passed', baseline, approvedAudio, picture: originalPicture ? 'original audio-only picture unchanged' : 'separately covered by npm test and npm run test:polish', approvedStems: 'byte-identical', sourceDuration, music: cues.music.label, stems, scope: 'Local source, timing, automation and served-byte checks; not human listening or a new MP4 render'}, null, 2));
