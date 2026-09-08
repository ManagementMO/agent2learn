import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';

// Verify the exported bytes, independently of the browser/GSAP assertions.
const exec=promisify(execFile),report={checkedAt:new Date().toISOString(),files:[]};
const revision=JSON.parse(await readFile('src/launchflow-cues.json','utf8')).exportPrefix;
for(const[file,fps]of[[`renders/agent2learn-${revision}-120fps.mp4`,120],[`renders/agent2learn-${revision}.mp4`,60]]){
  const{stdout}=await exec('ffprobe',['-v','error','-count_frames','-show_streams','-show_format','-of','json',file]);
  const probe=JSON.parse(stdout),video=probe.streams.find(s=>s.codec_type==='video'),audio=probe.streams.find(s=>s.codec_type==='audio');
  assert.equal(video.width,1920);assert.equal(video.height,1080);
  assert.equal(video.codec_name,'h264');assert.equal(video.pix_fmt,'yuv420p');
  assert.equal(video.avg_frame_rate,`${fps}/1`);assert.equal(Number(video.nb_read_frames),fps*17.5);
  assert.equal(Number(probe.format.duration),17.5);assert.equal(Number(video.duration),17.5);
  assert.equal(audio.codec_name,'aac');assert.equal(audio.channels,2);assert.equal(audio.sample_rate,'48000');
  assert.ok(Math.abs(Number(audio.duration)-17.5)<.025);
  const decoded=await exec('ffmpeg',['-v','error','-i',file,'-f','null','-']);
  assert.equal(decoded.stderr,'','The entire video and audio must decode cleanly');
  const hashes=[];let tail;
  for(const at of[8.7,9.1,9.7,10.2,17.48]){
    const{stdout:frame}=await exec('ffmpeg',['-v','error','-ss',String(at),'-i',file,'-frames:v','1','-vf','scale=192:108','-f','rawvideo','-pix_fmt','rgb24','-'],{encoding:'buffer'});
    assert.equal(frame.length,192*108*3);
    hashes.push(createHash('sha256').update(frame).digest('hex'));
    if(at===17.48){
      const mean=frame.reduce((sum,x)=>sum+x,0)/frame.length;
      const deviation=Math.sqrt(frame.reduce((sum,x)=>sum+(x-mean)**2,0)/frame.length);
      assert.ok(mean>150&&deviation>20,'The last encoded frame must contain the light-background logo lockup, not blank or black');
      tail={mean,deviation};
    }
  }
  assert.equal(new Set(hashes.slice(0,4)).size,4,'Encoded typing frames must change');
  const bytes=await readFile(file);
  report.files.push({file,width:video.width,height:video.height,fps,frames:Number(video.nb_read_frames),duration:17.5,audio:{codec:audio.codec_name,sampleRate:Number(audio.sample_rate),channels:audio.channels},bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),fullDecode:'passed',typingFramesDistinct:true,tail});
}
report.status='passed';await writeFile(`.checks/${revision}-export.json`,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
