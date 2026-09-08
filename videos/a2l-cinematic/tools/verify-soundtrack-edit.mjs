import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';

// Compare to the actual approved source, not a fixture invented for this edit.
const previous = path => execFileSync('git', ['show', `bd77b17402c18e3b671598e893517035c1578cbe:videos/a2l-cinematic/${path}`], {encoding:'utf8'});
// Approved picture changes after the soundtrack pass: this exact footer deletion
// and a bottom-only Content underline instead of an inset shadow.
// Normalize the old baseline only: a footer reintroduced in the current film still fails.
const withoutRemovedFooter = html => html.replace(/^    <div(?: data-hf-id="hf-kjsx")? class="demo-note">CS135-INSPIRED SYNTHETIC DEMO · STYLIZED CODEX · SETUP &amp; RESPONSES TIME-COMPRESSED<\/div>\r?\n/m,'');
const withCleanContentUnderline = css => css.replace('.learn-navbar .current{color:#076bab;box-shadow:inset 0 -3px #0074af}', '.learn-navbar .current{color:#076bab;background:linear-gradient(#0074af,#0074af) left bottom/100% 3px no-repeat}');
const cues = JSON.parse(await readFile('src/launchflow-cues.json','utf8'));
const oldCues = JSON.parse(previous('src/launchflow-cues.json'));
for(const key of ['duration','typing','response','actions'])
  assert.deepEqual(cues[key],oldCues[key],`Soundtrack edits must not change ${key}`);
for(const path of ['src/launchflow-motion.js','src/launchflow.css','src/launchflow.html.template','white.css','src/brand-variant.json'])
  assert.equal(await readFile(path,'utf8'),path==='src/launchflow.html.template'?withoutRemovedFooter(previous(path)):path.endsWith('.css')?withCleanContentUnderline(previous(path)):previous(path),`Picture/brand source unchanged except requested footer/underline cleanup: ${path}`);
const pictureOnly = html => html
  .replace(/<audio\b[^>]*>[\s\S]*?<\/audio>/g,'')
  .replace(/<script>window\.__A2L_CUES=[\s\S]*?<\/script>/g,'');
assert.equal(pictureOnly(await readFile('index.html','utf8')),pictureOnly(withoutRemovedFooter(previous('index.html'))),'All compiled picture HTML and motion remain identical except requested footer removal');
assert.notEqual(cues.audioPrefix,oldCues.audioPrefix,'Use new files, preserve the old stems');
assert.deepEqual(await readFile(`assets/audio/${cues.audioPrefix}-typing.wav`),await readFile(`assets/audio/${oldCues.audioPrefix}-typing.wav`),'Recorded input Foley remains byte-identical');
assert.equal(cues.music.id,'bgm_012');
assert.ok(cues.music.sourceStart+cues.duration*cues.music.playbackRate<26,'Selected source spans the full film without looping or a silent pad');
const envelope = cues.musicEnvelope;
assert.equal(envelope[0][0],0); assert.equal(envelope[0][1],0);
assert.equal(envelope.at(-1)[0],cues.duration); assert.equal(envelope.at(-1)[1],0);
for(let i=1;i<envelope.length;i++) assert.ok(envelope[i][0]>envelope[i-1][0]);
assert.ok(envelope.every(([,v])=>v>=0&&v<=1),'Bounded, editable music automation');
const meta = JSON.parse(await readFile('audio_meta.json','utf8'));
assert.equal(meta.music.id,cues.music.id);
assert.equal(meta.music.playback_rate,cues.music.playbackRate);
assert.deepEqual(meta.automation,envelope);
const served=[];
for(const stem of ['bed','typing','interface']){
  const path=`assets/audio/${cues.audioPrefix}-${stem}.wav`;
  const url=`http://localhost:3017/api/projects/a2l-cinematic/preview/${path}`;
  const response=await fetch(url);
  assert.equal(response.status,200,`Studio serves ${stem}`);
  const actual=Buffer.from(await response.arrayBuffer()),local=await readFile(path);
  assert.deepEqual(actual,local,`No stale cached ${stem}`);
  served.push({stem,bytes:actual.length,sha256:createHash('sha256').update(actual).digest('hex')});
}
console.log(JSON.stringify({status:'passed',pictureSource:'unchanged from approved bd77b174 except requested footer/underline cleanup',typing:'byte-identical',sourceId:meta.music.id,served},null,2));
