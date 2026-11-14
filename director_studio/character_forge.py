"""Run upstream Character Forge in a separate, local-only process."""
import json,os,subprocess,uuid,shutil,hashlib
from pathlib import Path
from . import store,story_assets,engines

def run(pid,aid,outfit,report,checkpoint):
 s=store.load(pid);asset=s['nodes'][aid];master=story_assets.reference(s,aid)
 if asset['kind']!='character' or not master or not master.get('output'):raise ValueError('Attach a character master reference first')
 engines.ensure_comfy(engines.settings(),lambda *args:report(str(args[0]),None))
 folder=store.project_dir(pid)/'.engine'/('character-forge-'+uuid.uuid4().hex);folder.mkdir(parents=True)
 source=store.contained(pid,master['output']);snapshot=folder/('master-source'+source.suffix);shutil.copy2(source,snapshot);master_hash=hashlib.sha256(snapshot.read_bytes()).hexdigest()
 request={'name':asset['title'],'reference':str(snapshot),'output':str(folder/'output'),'outfit':outfit}
 store.atomic(folder/'request.json',request);bridge=store.ROOT/'tools/CharacterForge/jdirector_bridge.py'
 env=os.environ.copy();env['PYTHONIOENCODING']='utf-8';env.pop('GEMINI_API_KEY',None)
 proc=subprocess.Popen([str(store.ROOT/'.venv/Scripts/python.exe'),str(bridge),str(folder/'request.json')],cwd=bridge.parent,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 store.mutate(pid,lambda state:state['nodes'][aid].update(status='running',progress=0),False)
 try:
  current_stage=0
  with (folder/'forge.log').open('w',encoding='utf-8') as log:
   for line in proc.stdout:
    log.write(line);log.flush()
    if line.startswith('FORGE_STAGE '):
     event=json.loads(line[len('FORGE_STAGE '):]);current_stage=int(event['stage']);report('Character Forge: '+event['message'],min(95,int(current_stage*100/5)));checkpoint();proc.stdin.write('continue\n');proc.stdin.flush()
    elif line.startswith('FORGE_PROGRESS '):
     event=json.loads(line[len('FORGE_PROGRESS '):]);value=int(event['value']);maximum=max(1,int(event['max']));percent=min(95,int((current_stage+value/maximum)*100/5));report('Character Forge view '+str(current_stage+1)+' / 5: sampling '+str(value)+' / '+str(maximum),percent)
  if proc.wait()!=0:raise RuntimeError('Character Forge failed; the original master and completed checkpoint images were kept. Log: '+str(folder/'forge.log'))
  result=json.loads((folder/'output/result.json').read_text());required={'reference_full_body','front_portrait','side_portrait','side_body','rear_body'}
  if not required.issubset({v['name'] for v in result['views']}):raise RuntimeError('Incomplete character sheet; master was kept')
  entries=result['views']+[{'name':'character_sheet','path':result['sheet'],'prompt':'Character Forge combined review sheet'}]
  for row in entries:
   path=Path(row['path']).resolve()
   if not path.is_relative_to((folder/'output').resolve()) or not path.is_file():raise RuntimeError('Invalid Character Forge output')
  labels={'reference_full_body':'Front full body','front_portrait':'Front portrait','side_portrait':'Side portrait','side_body':'Side full body','rear_body':'Rear full body','character_sheet':'Character sheet'}
  def attach(state):
   for row in entries:
    n=store.add_node(state,'reference',asset['title']+' / '+labels[row['name']],parent=aid,prompt=row.get('prompt',''),category='Angles',status='succeeded',requires_review=True,reference_source='character_forge',derived_from=master['id'],derived_from_version=master.get('version',0),derived_from_hash=master_hash,forge_view=row['name'],version=1)
    dest=store.node_dir(state,n)/'preview.jpg';dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(row['path'],dest);n['output']=str(dest.relative_to(store.project_dir(pid))).replace('\\','/')
   store.log(state,'Character Forge created five views and a review sheet. Original primary reference retained. Review and Save derived views before reuse.')
  store.mutate(pid,attach);report('Character Forge finished: five views and a sheet ready for review; master unchanged',100)
 finally:
  if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
  store.mutate(pid,lambda state:state['nodes'][aid].update(status='idle'),False)
