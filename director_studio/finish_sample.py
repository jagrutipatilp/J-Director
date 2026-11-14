"""Finish the user-requested sample after real generation jobs complete."""
from pathlib import Path
import json,time,subprocess,os
import requests,av
R=Path(__file__).resolve().parents[1];sample=json.loads((R/'logs/director-sample-jobs.json').read_text());pid=sample['project'];base='http://127.0.0.1:8790/api/projects/'+pid
report=R/'logs/director-sample-result.json';root=R/'projects'/pid

def main():
 while True:
  response=requests.get(base,timeout=15);response.raise_for_status();state=response.json()['project'];nodes=state['nodes']
  selected=[next(n for n in nodes.values() if n['title']==name) for name in ('Clip 01','Keyframe 02','Clip 02')]
  if any(n['status']=='failed' for n in selected):raise RuntimeError('; '.join(n.get('error','failed') for n in selected if n['status']=='failed'))
  if all(n['status'] in ('succeeded','saved') for n in selected):break
  report.write_text(json.dumps({'state':'generating','items':[{'title':n['title'],'status':n['status'],'progress':n.get('progress'),'stage':n.get('stage')} for n in selected]},indent=2))
  time.sleep(10)
 ff=R/'tools/ffmpeg/ffmpeg.exe'
 if not ff.is_file():
  import imageio_ffmpeg
  ff=Path(imageio_ffmpeg.get_ffmpeg_exe())
 output=root/'.engine/sample-preview';output.mkdir(exist_ok=True)
 parts=[];checks=[]
 for i,name in enumerate(('Clip 01','Clip 02'),1):
  n=next(n for n in nodes.values() if n['title']==name);source=root/n['output'];audio=root/'.engine/sample-audio'/('shot-'+str(i).zfill(2)+'.wav');part=output/('shot-'+str(i).zfill(2)+'.mp4')
  subprocess.run([str(ff),'-y','-loglevel','error','-i',str(source),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-vf','scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,fps=24','-t','4','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-af','apad','-movflags','+faststart',str(part)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
  container=av.open(str(part));hashes=set();frames=0
  for frame in container.decode(video=0):hashes.add(hash(frame.to_ndarray().tobytes()));frames+=1
  container.close()
  if frames<80 or len(hashes)<10:raise RuntimeError('Sample '+name+' did not contain sufficient changing video frames')
  parts.append(part);checks.append({'clip':name,'frames':frames,'distinct_frames':len(hashes),'audio':'Original supplied soundtrack, English line on clip 2'})
 listing=output/'concat.txt';listing.write_text("file 'shot-01.mp4'\nfile 'shot-02.mp4'\n")
 final=output/'the-last-signal-sample.mp4'
 subprocess.run([str(ff),'-y','-loglevel','error','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(final)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
 c=av.open(str(final));duration=c.duration/av.time_base;audio_tracks=len(c.streams.audio);c.close();assert duration>=7.9 and audio_tracks
 report.write_text(json.dumps({'state':'complete','output':str(final),'duration':duration,'checks':checks,'note':'Review preview; pipeline boxes have not been auto-approved or locked.'},indent=2));print(str(final),flush=True)
if __name__=='__main__':
 try:main()
 except Exception as error:report.write_text(json.dumps({'state':'failed','error':str(error)},indent=2));raise
