import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdir,readFile} from 'node:fs/promises';
const revision=JSON.parse(await readFile('src/launchflow-cues.json','utf8')).exportPrefix;
const dir=`.checks/${revision}-encoded`;
const exec=promisify(execFile),file=`renders/agent2learn-${revision}-120fps.mp4`;
await mkdir(dir,{recursive:true});
const times=[1.7,2.85,5.4,6.3,8.05,10.2,14.5,17.2];
for(let i=0;i<times.length;i++){
  await exec('ffmpeg',['-v','error','-y','-ss',String(times[i]),'-i',file,'-frames:v','1','-vf','scale=480:270',`${dir}/hero-${String(i+1).padStart(2,'0')}.png`]);
}
await exec('ffmpeg',['-v','error','-y','-i',`${dir}/hero-%02d.png`,'-vf','tile=4x2:padding=8:margin=8:color=white','-frames:v','1',`renders/${revision}-storyboard.jpg`]);
await exec('ffmpeg',['-v','error','-y','-i',file,'-vf','fps=4,scale=320:180,tile=10x7:padding=6:margin=6:color=white','-frames:v','1',`renders/${revision}-dense-review.jpg`]);
await exec('ffmpeg',['-v','error','-y','-ss','5.5','-t','3','-i',file,'-vf','fps=12,scale=320:180,tile=6x6:padding=6:margin=6:color=white','-frames:v','1',`renders/${revision}-ingestion-review.jpg`]);
for(const[time,name]of[[5.4,'learn'],[5.65,'sync-exit'],[6.25,'clipped-browser'],[6.3,'handoff'],[8.05,'context'],[12.1,'answer'],[17.48,'final']]){
  await exec('ffmpeg',['-v','error','-y','-ss',String(time),'-i',file,'-frames:v','1',`${dir}/${name}.png`]);
}
for(let i=0;i<6;i++){
  await exec('ffmpeg',['-v','error','-y','-ss',String(12.92+i*.16),'-i',file,'-frames:v','1','-vf','scale=480:270',`${dir}/camera-${i+1}.png`]);
}
await exec('ffmpeg',['-v','error','-y','-i',`${dir}/camera-%d.png`,'-vf','tile=3x2:padding=8:margin=8:color=white','-frames:v','1',`.checks/${revision}-camera-encoded.jpg`]);
await exec('ffmpeg',['-v','error','-y','-ss','14.5','-i',file,'-frames:v','1',`renders/${revision}-poster.png`]);
console.log('Encoded 8-hero sheet, 70-frame dense review, 36-frame ingestion review and full-resolution evidence saved.');
