import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdir} from 'node:fs/promises';
const exec=promisify(execFile),file='renders/agent2learn-codex-demo-120fps.mp4';
await mkdir('.checks/codex-encoded',{recursive:true});
// All QA stills come from the final encoded bytes, not a different preview run.
const times=[.8,2.95,4.55,5.9,8.5,9.4,10.3,13.2];
for(let i=0;i<times.length;i++){
  await exec('ffmpeg',['-v','error','-y','-ss',String(times[i]),'-i',file,'-frames:v','1',
    '-vf','scale=480:270',
    `.checks/codex-encoded/hero-${String(i+1).padStart(2,'0')}.png`]);
}
await exec('ffmpeg',['-v','error','-y','-i','.checks/codex-encoded/hero-%02d.png',
  '-vf','tile=4x2:padding=8:margin=8:color=white','-frames:v','1','renders/codex-storyboard.jpg']);
await exec('ffmpeg',['-v','error','-y','-i',file,'-vf',
  'fps=4,scale=320:180,tile=9x6:padding=6:margin=6:color=white',
  '-frames:v','1','renders/codex-dense-review.jpg']);
await exec('ffmpeg',['-v','error','-y','-ss','10.3','-i',file,'-frames:v','1','renders/codex-poster.png']);
await exec('ffmpeg',['-v','error','-y','-ss','8.5','-i',file,'-frames:v','1','.checks/codex-encoded/answer.png']);
await exec('ffmpeg',['-v','error','-y','-ss','13.48','-i',file,'-frames:v','1','.checks/codex-encoded/final.png']);
console.log('Encoded hero sheet, 4fps dense review, full-size answer, proof and final frame saved.');
