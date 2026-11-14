"""CPU-only motion-drama editing pilot from existing approved/reference media."""
from __future__ import annotations
import hashlib,json,subprocess,time,wave
from pathlib import Path
import numpy as np
from PIL import Image
from . import store

FFMPEG=Path('C:/src/ai drama/models/voicestudio-data/media_tools/shims/ffmpeg.exe')
W,H,FPS=576,1024,30

def run(args,folder,label):
 result=subprocess.run([str(FFMPEG),'-y','-hide_banner','-loglevel','warning','-threads','2',*args],cwd=folder,capture_output=True,text=True)
 (folder/(label+'.log')).write_text(result.stderr,encoding='utf-8')
 if result.returncode:raise RuntimeError(label+': '+result.stderr[-3500:])

def make_foley(path,duration):
 sr=48000;rng=np.random.default_rng(8831);count=int(sr*duration);white=rng.standard_normal(count)
 # Quiet air/room tone; no music or invented speech.
 room=np.convolve(white,np.ones(60)/60,mode='same')*.007
 audio=room.astype(np.float64)
 for when in [12.8,14.05,15.3,16.55]:
  t=np.arange(int(.42*sr))/sr
  click=(.065*rng.standard_normal(len(t))*np.exp(-t*100)+.045*np.sin(2*np.pi*720*t)*np.exp(-t*48)+.035*np.sin(2*np.pi*155*t)*np.exp(-t*24))
  for delay,gain in [(0,1),(.07,.22),(.14,.1)]:
   start=int((when+delay)*sr);end=min(count,start+len(click));audio[start:end]+=gain*click[:end-start]
 audio[:sr]*=np.linspace(0,1,sr);audio[-sr:]*=np.linspace(1,0,sr)
 stereo=np.stack([audio,audio*.97],axis=1);pcm=(np.clip(stereo,-.95,.95)*32767).astype('<i2')
 with wave.open(str(path),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(sr);f.writeframes(pcm.tobytes())

def build(pid):
 state=store.load(pid);episode=next(n for n in state['nodes'].values() if n['kind']=='episode');folder=store.project_dir(pid)/'.previews'/('motion-drama-'+time.strftime('%Y%m%d-%H%M%S'));folder.mkdir(parents=True)
 def source(nid):
  n=state['nodes'][nid]
  if not n.get('output'):raise ValueError('Missing source: '+n['title'])
  return store.contained(pid,n['output'])
 child=source('06adec33e4e1');motion=source('328b9512a79c');portrait=source('8acf649d616c');front=source('a01081f71426')
 endpoint=state['nodes']['18770047fdb2'];reaction=store.contained(pid,endpoint['output']) if endpoint.get('output') else child
 # Crops are editorial reframings, not claims that new AI poses were generated.
 shots=[
  {'name':'Moonlit room','source':child,'seconds':4,'crop':[30,100,650,800],'zoom':1.035,'push':.055},
  {'name':'Child alone','source':child,'seconds':5,'crop':None,'zoom':1.02,'push':.045},
  {'name':'Quiet breathing — animated insert','source':motion,'seconds':3.5,'video':True,'trim':1.5},
  {'name':'Claire approaches — close-up','source':portrait,'seconds':4.5,'crop':None,'zoom':1.015,'push':.055},
  {'name':'The child freezes — reaction','source':reaction,'seconds':3.5,'crop':[320,600,500,820] if reaction==child else None,'zoom':1.035,'push':.035},
  {'name':'The unreadable face','source':front,'seconds':4.5,'crop':None,'zoom':1.015,'push':.06},
 ]
 segments=[]
 for index,shot in enumerate(shots):
  out=folder/('shot-'+str(index+1)+'.mp4');frames=round(shot['seconds']*FPS)
  if shot.get('video'):
   vf=f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1,eq=brightness=-0.008:contrast=1.025:saturation=0.88,vignette=PI/5,format=yuv420p'
   args=['-ss',str(shot['trim']),'-i',str(shot['source']),'-an','-t',str(shot['seconds']),'-vf',vf]
  else:
   with Image.open(shot['source']) as im:iw,ih=im.size
   crop=shot.get('crop') or [0,0,iw,ih];x,y,cw,ch=crop;cw=min(cw,iw-x);ch=min(ch,ih-y)
   # Fit the source to vertical framing without stretching faces.
   target=W/H
   if cw/ch>target:
    width=int(ch*target);x+=int((cw-width)*.5);cw=width
   else:
    height=int(cw/target);y+=int((ch-height)*.5);ch=height
   z=shot['zoom'];push=shot['push'];grade='eq=brightness=-0.008:contrast=1.025:saturation=0.88'
   if index in (3,5):grade='eq=brightness=-0.025:contrast=1.07:saturation=0.72,colorbalance=rs=-0.025:bs=0.025'
   vf=f"crop={cw}:{ch}:{x}:{y},scale=1152:2048:flags=lanczos,zoompan=z='{z}+{push}*on/{frames-1}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s={W}x{H}:fps={FPS},setsar=1,{grade},vignette=PI/5,format=yuv420p"
   if index==5:vf+=',fade=t=out:st=3.7:d=0.8'
   args=['-loop','1','-i',str(shot['source']),'-an','-frames:v',str(frames),'-vf',vf]
  args[-1]+= ',scale=in_range=auto:out_range=tv:out_color_matrix=bt709,format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709'
  run([*args,'-filter_threads','1','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-color_range','tv','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709',str(out)],folder,'shot-'+str(index+1));segments.append(out)
  print('Edited shot',index+1,'of',len(shots),flush=True)
 black=folder/'black.mp4';run(['-f','lavfi','-i',f'color=c=black:s={W}x{H}:r={FPS}:d=1','-an','-c:v','libx264','-preset','fast','-pix_fmt','yuv420p',str(black)],folder,'black');segments.append(black)
 (folder/'cut-list.txt').write_text(''.join("file '"+p.name+"'\n" for p in segments),encoding='utf-8')
 silent=folder/'picture.mp4';run(['-f','concat','-safe','0','-i','cut-list.txt','-c','copy',str(silent)],folder,'assemble')
 make_foley(folder/'room-and-footsteps.wav',26)
 audio_filter='[1:a]atrim=start=0:end=8,asetpts=PTS-STARTPTS,volume=0.85,adelay=7500|7500[native];[2:a]volume=0.9[room];[native][room]amix=inputs=2:duration=longest:normalize=0,afade=t=out:st=24.7:d=1.3,alimiter=limit=0.9[a]'
 output=folder/'The Devil Enters - Motion Drama Pilot.mp4'
 run(['-i',str(silent),'-i',str(motion),'-i','room-and-footsteps.wav','-filter_complex_threads','1','-filter_complex',audio_filter,'-map','0:v:0','-map','[a]','-t','26','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',str(output)],folder,'sound-mix')
 for shot in shots:shot['source']=str(shot['source'])
 manifest={'title':'The Devil Enters — Motion Drama Pilot','duration_seconds':26,'resolution':[W,H],'fps':FPS,'shots':shots,'style':'Photo-based limited-motion editing pilot; original character look retained. No illustrated/anime redraw.','audio':'Native audio from the existing generated clip, quiet synthesized room tone and four heel-click cues. No new speech or music.','new_ai_video_jobs':0,'new_ai_image_jobs':0,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
 store.atomic(folder/'edit-manifest.json',manifest)
 def register(s):
  s['motion_comic_preview']={'episode':episode['id'],'path':str(output.relative_to(store.project_dir(pid))).replace('\\','/'),'title':manifest['title'],'duration':26,'created':time.time()}
  store.log(s,'Motion-drama pilot ready: 26 seconds, six edited shots, one existing animated insert. Preview only; original scene renders preserved.','success')
 store.mutate(pid,register,False);print('OUTPUT',str(output),flush=True);return output

if __name__=='__main__':
 import sys
 build(sys.argv[1])
