"""Recoverable project deletion, exporting local assets before hiding a project."""
import copy,hashlib,json,time
from pathlib import Path
from . import store,library,jobs
MARKER='.deleted-project.json'

def deleted():
 result=[]
 for path in store.PROJECTS.glob('*/'+MARKER):
  try:
   row=json.loads(path.read_text(encoding='utf-8'));row['id']=path.parent.name;result.append(row)
  except (OSError,ValueError):continue
 return sorted(result,key=lambda x:x['deleted_at'],reverse=True)

def export_assets(state):
 """Never merge different project identities merely because they share a name."""
 with library.LOCK:
  catalog=library.load();exported=[];image_count=0
  for node in state['nodes'].values():
   if node['kind'] not in ('character','location','prop'):continue
   refs=[n for n in store.children(state,node['id']) if n['kind']=='reference'];refs.sort(key=lambda r:r['id']!=node.get('primary_reference'));sources=[]
   for ref in refs:
    raw=None
    if ref.get('output'):
     source=store.contained(state['id'],ref['output'])
     if not source.is_file():raise ValueError('Reference image is missing: '+ref['title']+'. Project was not deleted.')
     raw=source.read_bytes()
    sources.append((ref,raw))
   snapshot={'name':node['title'],'kind':node['kind'],'description':node['text'],'requirements':{k:v.get('text','') for k,v in node.get('requirements',{}).items()},'references':[{'name':r['title'],'prompt':r.get('prompt',''),'category':r.get('category'),'sha256':hashlib.sha256(raw).hexdigest() if raw else None} for r,raw in sources]}
   digest=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
   previous=next((a for a in catalog['assets'] if a.get('project_export',{}).get('project')==state['id'] and a.get('project_export',{}).get('node')==node['id'] and a.get('project_export',{}).get('snapshot')==digest),None)
   if previous:exported.append(previous['id']);continue
   now=time.time();aid=store.uid();asset={'id':aid,'kind':node['kind'],'name':node['title'],'description':node['text'],'created':now,'updated':now,'variants':[],'project_export':{'project':state['id'],'project_title':state['title'],'node':node['id'],'snapshot':digest}}
   folder=(library.ROOT/({'character':'characters','location':'locations','prop':'props'}[node['kind']])/aid).resolve()
   if not folder.is_relative_to(library.ROOT.resolve()):raise ValueError('Invalid catalogue export path')
   folder.mkdir(parents=True,exist_ok=True);store.atomic(folder/'project-source.json',{'asset':node,'source_project':state['id'],'requirements':node.get('requirements',{})})
   (folder/'requirements.md').write_text('# '+node['title']+'\n\n'+node['text']+'\n\n'+json.dumps(node.get('requirements',{}),ensure_ascii=False,indent=2),encoding='utf-8')
   for ref,raw in sources:
    vid=store.uid();v={'id':vid,'title':ref['title'],'category':ref.get('category') if ref.get('category') in library.CATEGORIES else 'Outfits' if node['kind']=='character' else 'Angles','prompt':ref.get('prompt') or node['text'] or node['title'],'version':0,'output':None,'provenance':{'origin':'preserved from deleted project','project':state['id'],'reference':ref['id']}}
    if raw:
     import io
     from PIL import Image,ImageOps
     try:
      with Image.open(io.BytesIO(raw)) as image:
       image.load();target=folder/'images'/(vid+'-v001.jpg');target.parent.mkdir(exist_ok=True)
       if image.format=='JPEG':target.write_bytes(raw)
       else:ImageOps.exif_transpose(image).convert('RGB').save(target,'JPEG',quality=98)
     except Exception as e:raise ValueError('Could not preserve reference '+ref['title']+'. Project was not deleted.') from e
     v.update(version=1,output=str(target.relative_to(library.ROOT.resolve())).replace('\\','/'));image_count+=1
    asset['variants'].append(v)
   if not asset['variants']:asset['variants'].append({'id':store.uid(),'title':'Main reference','category':'Outfits' if node['kind']=='character' else 'Angles','prompt':node['text'] or node['title'],'version':0,'output':None})
   catalog['assets'].append(asset);exported.append(aid)
  library.persist(catalog)
  return exported,image_count

def delete(pid):
 with jobs.GUARD,store._LOCK:
  if jobs.pending(pid):raise ValueError('Stop active work in this project before deleting it')
  marker=store.project_dir(pid)/MARKER
  if marker.exists():return json.loads(marker.read_text(encoding='utf-8'))
  state=store.load(pid);assets,images=export_assets(state)
  receipt={'id':pid,'title':state['title'],'deleted_at':time.time(),'catalogue_assets':assets,'preserved_assets':len(assets),'copied_images':images}
  # Marker is written only after every asset and image has been preserved.
  store.atomic(marker,receipt);return receipt

def restore(pid):
 with jobs.GUARD,store._LOCK:
  marker=store.project_dir(pid)/MARKER
  if not marker.is_file():raise ValueError('This project is not deleted')
  state=store.load(pid);marker.unlink();store.log(state,'Project restored. Preserved catalogue copies remain available.');return store.persist(state)
