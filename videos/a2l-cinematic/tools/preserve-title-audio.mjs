import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {access,mkdir,readFile,rename} from 'node:fs/promises';
import {createHash} from 'node:crypto';

// Specific to the title-only follow-up, not a general mixing step. A renderer
// rerun can produce different AAC bytes. Copy the approved audio without any
// codec generation loss, while preserving both newly encoded video streams.
const source='renders/agent2learn-signalflow-polish-120fps.mp4';
const cues=JSON.parse(await readFile('src/launchflow-cues.json','utf8'));
assert.equal(cues.exportPrefix,'signalflow-agent');
assert.equal(cues.duration,17.5);
const {exportPrefix,...timing}=cues;
assert.deepEqual(timing,JSON.parse(await readFile('.archive/signalflow-polish17.5/src/launchflow-cues.json','utf8')),
  'This lossless reuse is valid only while the approved picture/audio timing remains unchanged');
assert.equal(createHash('sha256').update(await readFile(source)).digest('hex'),
  'a6d99c497c9e2d6766a106b9dce990b02c299525e187e40f551f5f44b33f302c'); // pragma: allowlist secret -- approved export SHA-256
const hash=(file,stream)=>execFileSync('ffmpeg',['-v','error','-nostdin','-i',file,
  '-map',`0:${stream}:0`,'-c','copy','-f','hash','-hash','sha256','-'],{encoding:'utf8'}).trim();
const approved=hash(source,'a');
await mkdir('.checks/title-audio',{recursive:true});
for(const suffix of ['-120fps','']){
  const file=`renders/agent2learn-signalflow-agent${suffix}.mp4`;
  if(hash(file,'a')===approved){console.log(`${file}: approved AAC already present`);continue;}
  const saved=`.checks/title-audio/fresh-render${suffix}.mp4`;
  try{await access(saved);throw new Error(`Preserved render already exists: ${saved}`);}
  catch(error){if(error.code!=='ENOENT')throw error;}
  const muxed=`.checks/title-audio/approved${suffix}.mp4`;
  execFileSync('ffmpeg',['-v','error','-nostdin','-n','-i',file,'-i',source,
    '-map','0:v:0','-map','1:a:0','-c','copy','-map_metadata','0',
    '-movflags','+faststart',muxed]);
  assert.equal(hash(muxed,'a'),approved,'Keep exactly the approved AAC packets');
  assert.equal(hash(muxed,'v'),hash(file,'v'),'Do not re-encode or change the new picture');
  await rename(file,saved);
  await rename(muxed,file);
  console.log(`${file}: original audio copied losslessly; new picture unchanged`);
}
