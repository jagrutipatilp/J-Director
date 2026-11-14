"""Immutable approved episode frames; never learn from unapproved previews."""
import copy, json, shutil, subprocess, time
from pathlib import Path
from . import store, production
ROOT=store.ROOT/'library'/'continuity'

def timeline(s):
 return [ep for root in store.children(s,None) for ep in ([root] if root['kind']=='episode' else store.children(s,root['id']) if root['kind']=='arc' else []) if ep['kind']=='episode']

def signature(s,n,rendered=False):
 if rendered and 'render_references' in n:
  return sorted((row.get('library_asset') or row.get('owner') or row['id'],row.get('library_variant') or row['id'],row.get('library_version',row.get('version',0))) for row in n['render_references'])
 return sorted((s['nodes'][rid].get('library_asset') or s['nodes'][rid].get('parent') or rid, s['nodes'][rid].get('library_variant') or rid, s['nodes'][rid].get('library_version',s['nodes'][rid].get('version',0))) for rid in production.ids(s,n) if rid in s['nodes'])

def records(pid):
 path=ROOT/pid/'catalog.json'
 return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

def approve(pid,eid):
 s=store.load(pid)
 if s['nodes'].get(eid,{}).get('kind')!='episode':raise ValueError('Select an episode')
 clips=[n for n in s['nodes'].values() if n['kind']=='clip' and store.episode_of(s,n['id'])==eid]
 if not clips or any(n['status']!='saved' or not n.get('output') for n in clips):raise ValueError('Review, Save and lock every video clip before approving episode continuity')
 if s.get('quality')!='final':raise ValueError('Use Final quality before approving episode continuity')
 if any(n.get('render_quality')!='final' for n in clips):raise ValueError('These clips were not rendered at Final quality; render and review final takes first')
 ffmpeg=shutil.which('ffmpeg') or str(store.ROOT/'tools/ffmpeg/ffmpeg.exe')
 revision=store.uid();folder=ROOT/pid/eid/revision;folder.mkdir(parents=True,exist_ok=True);frames=[]
 try:
  for clip in clips:
   frame=s['nodes'].get(clip.get('depends_on'),{})
   if not production.ids(s,frame):continue
   target=folder/(clip['id']+'.jpg')
   subprocess.run([ffmpeg,'-y','-loglevel','error','-ss','0.5','-i',str(store.contained(pid,clip['output'])),'-frames:v','1',str(target)],check=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   if not target.is_file():raise ValueError('Could not extract an approved video frame')
   frames.append({'path':str(target.relative_to(ROOT)),'signature':signature(s,frame,rendered=True),'clip':clip['id'],'clip_version':clip.get('version',0)})
  if not frames:raise ValueError('Attach shot references before approving continuity')
  entry={'id':revision,'episode':eid,'title':s['nodes'][eid]['title'],'approved':time.time(),'frames':frames}
  catalog=records(pid);catalog.append(entry);store.atomic(ROOT/pid/'catalog.json',catalog)
  store.mutate(pid,lambda state:store.log(state,'Approved episode continuity: '+entry['title']+'; '+str(len(frames))+' real video frames retained'))
  return entry
 except Exception:
  # Keep incomplete extraction files private; never publish a partial approval.
  raise

def previous_frame(s,n):
 eid=store.episode_of(s,n['id']);order=[e['id'] for e in timeline(s)]
 if eid not in order:return None
 earlier=set(order[:order.index(eid)]);sig=json.loads(json.dumps(signature(s,n)))
 if not sig:return None
 rank={e:i for i,e in enumerate(order)}
 eligible=sorted((r for r in records(s['id']) if r['episode'] in earlier),key=lambda r:(rank[r['episode']],r['approved']),reverse=True)
 for entry in eligible:
  for frame in entry['frames']:
   if frame['signature']==sig:
    path=(ROOT/frame['path']).resolve()
    if path.is_relative_to(ROOT.resolve()) and path.is_file():return {'path':str(path),'approval':entry['id'],'episode':entry['episode']}
 return None

def select_references(s,text):
 """Match attached asset names, deduplicate by asset; never pick arbitrary first references."""
 result=[];seen=set();text=text.casefold()
 for ref in s['nodes'].values():
  if ref['kind']!='reference' or not ref.get('output') or ref.get('status')!='saved':continue
  asset=s['nodes'].get(ref.get('parent'),{});name=asset.get('title','').strip()
  if not name or name.casefold() not in text or asset.get('id') in seen:continue
  seen.add(asset.get('id'));result.append(ref['id'])
 return result
