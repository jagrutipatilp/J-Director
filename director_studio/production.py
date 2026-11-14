"""Optional scene/sequence/shot direction and complete Qwen reference boards."""
import copy, math
from pathlib import Path
from PIL import Image, ImageOps, ImageDraw
from . import store

def ancestors(s,n):
 result={}
 while n:
  result[n['kind']]=n;n=s['nodes'].get(n.get('parent'))
 return result

def validate(s,n,value):
 if not isinstance(value,dict):raise ValueError('Invalid production selection')
 allowed={'episode':{'background','cast','props'},'scene':{'background','cast','props'},'sequence':{'cast','props'},'keyframe':{'characters','expressions','inherit_background'}}.get(n['kind'],set())
 if set(value)-allowed:raise ValueError('Selection does not belong to this outline level')
 def ref(rid,kind=None,parent=None,category=None):
  if rid in (None,''):return
  r=s['nodes'].get(rid,{})
  if r.get('kind')!='reference':raise ValueError('Choose an existing project reference')
  owner=s['nodes'].get(r.get('parent'),{})
  if kind and owner.get('kind')!=kind:raise ValueError('Reference belongs to the wrong asset type')
  if parent and r.get('parent')!=parent:raise ValueError('Reference belongs to a different character')
  if category and r.get('category')!=category:raise ValueError('Choose a reference from '+category)
 if 'background' in value:ref(value['background'],'location')
 if 'cast' in value:
  if not isinstance(value['cast'],list) or len(value['cast'])>20:raise ValueError('Choose up to 20 characters')
  seen=set()
  for row in value['cast']:
   if not isinstance(row,dict) or set(row)-{'character','identity','outfit','accessories'}:raise ValueError('Invalid character selection')
   cid=row.get('character')
   if s['nodes'].get(cid,{}).get('kind')!='character' or cid in seen:raise ValueError('Choose unique project characters')
   seen.add(cid)
   ref(row.get('identity'),'character',cid);ref(row.get('outfit'),'character',cid,'Outfits')
   if not isinstance(row.get('accessories',[]),list):raise ValueError('Choose accessory references')
   for rid in row.get('accessories',[]):ref(rid,'character',cid,'Accessories')
 if 'props' in value:
  if not isinstance(value['props'],list):raise ValueError('Choose prop references')
  for rid in value['props']:ref(rid,'prop')
 if 'characters' in value:
  if not isinstance(value['characters'],list):raise ValueError('Choose shot characters')
  cast=direction(s,n).get('cast',[])
  ids={row['character'] for row in cast}
  if any(cid not in ids for cid in value['characters']):raise ValueError('Choose a character from this scene or episode')
 if 'expressions' in value:
  if not isinstance(value['expressions'],dict):raise ValueError('Choose expressions by character')
  cast=direction(s,n).get('cast',[])
  for cid,rid in value['expressions'].items():
   if cid not in {row['character'] for row in cast}:raise ValueError('Expression character is not in this scene or episode')
   ref(rid,'character',cid,'Expressions')
 if 'inherit_background' in value and not isinstance(value['inherit_background'],bool):raise ValueError('Invalid background choice')
 return copy.deepcopy(value)

def direction(s,n):
 chain=ancestors(s,n);result={}
 for level in ('episode','scene','sequence'):result.update(chain.get(level,{}).get('production',{}))
 manual=any(scope.get('asset_links_manual') for scope in chain.values())
 if manual:result.pop('background',None)
 if 'cast' not in result or manual:
  from . import story_assets
  characters,_=story_assets.automatic(s,n)
  result['cast']=[{'character':aid,'identity':story_assets.reference(s,aid)['id'],'accessories':[],'outfit':s['nodes'][aid].get('default_outfit')} for aid in characters if story_assets.reference(s,aid) and not s['nodes'][aid].get('offscreen')]
 return result

def resolve(s,n):
 chain=ancestors(s,n);shot=n.get('production',{});scene=direction(s,n);sequence=scene
 from . import story_assets
 auto_characters,auto_backgrounds=story_assets.automatic(s,n)
 def chosen_background(aid):
  selected=n.get('background_view_selection',{}).get(aid,{}).get('reference');ref=s['nodes'].get(selected,{})
  return ref if ref.get('kind')=='reference' and ref.get('parent')==aid else story_assets.reference(s,aid)
 if 'cast' not in sequence:
  sequence=dict(sequence);sequence['cast']=[{'character':aid,'identity':story_assets.reference(s,aid)['id'],'accessories':[],'outfit':s['nodes'][aid].get('default_outfit')} for aid in auto_characters if story_assets.reference(s,aid) and not s['nodes'][aid].get('offscreen')]
 if 'background' not in scene and len(auto_backgrounds)==1:
  ref=chosen_background(auto_backgrounds[0])
  if ref:scene=dict(scene);scene['background']=ref['id']
 rows=[];seen=set()
 def add(rid,role,owner=None):
  if not rid or rid in seen:return
  ref=s['nodes'].get(rid)
  if not ref or ref['kind']!='reference':return
  seen.add(rid);rows.append({'id':rid,'role':role,'owner':owner or ref.get('parent'),'title':ref['title'],'library_asset':ref.get('library_asset'),'library_variant':ref.get('library_variant'),'library_version':ref.get('library_version',ref.get('version',0)),'version':ref.get('version',0)})
 if n['kind']=='keyframe':
  if shot.get('inherit_background',True):
   add(scene.get('background'),'background')
   if 'background' not in scene:
    for aid in auto_backgrounds:
     ref=chosen_background(aid)
     if ref:add(ref['id'],'background')
  selected=shot.get('characters')
  for row in sequence.get('cast',[]):
   cid=row['character']
   if selected is not None and cid not in selected:continue
   master=story_assets.reference(s,cid)
   add(row.get('identity') or (master['id'] if master else None),'identity',cid);add(row.get('outfit'),'outfit',cid)
   for rid in row.get('accessories',[]):add(rid,'accessory',cid)
   add(shot.get('expressions',{}).get(cid),'expression',cid)
  for rid in sequence.get('props',[]):add(rid,'prop')
 for rid in n.get('references',[]):add(rid,'additional')
 return rows

def ids(s,n):return [r['id'] for r in resolve(s,n)]

def boards(s,n,folder,identity_first=False):
 rows=resolve(s,n)
 if identity_first:rows.sort(key=lambda row: 0 if row['role']=='identity' else 1 if row['role'] in ('outfit','expression','accessory') else 2)
 for row in rows:
  ref=s['nodes'][row['id']]
  if not ref.get('output') or not store.contained(s['id'],ref['output']).is_file():raise ValueError('Missing selected reference: '+ref['title'])
 groups={}
 identities=[row for row in rows if row['role'] in ('identity','expression')] if identity_first else []
 for row in rows:
  if row not in identities:groups.setdefault(row['owner'] or row['id'],[]).append(row)
 chunks=[[row] for row in identities]+list(groups.values())
 if len(chunks)>3:chunks=[chunks[0],chunks[1],[r for group in chunks[2:] for r in group]]
 paths=[];legend=[]
 for i,group in enumerate(chunks):
  if len(group)==1:
   paths.append(str(store.contained(s['id'],s['nodes'][group[0]['id']]['output'])))
  else:
   cols=min(3,len(group));width=512;label=62;count=math.ceil(len(group)/cols)
   sheet=Image.new('RGB',(cols*width,count*(width+label)),(240,240,240));draw=ImageDraw.Draw(sheet)
   for j,row in enumerate(group):
    x=(j%cols)*width;y=(j//cols)*(width+label)
    with Image.open(store.contained(s['id'],s['nodes'][row['id']]['output'])) as im:
     thumb=ImageOps.contain(im.convert('RGB'),(width,width));sheet.paste(thumb,(x+(width-thumb.width)//2,y+(width-thumb.height)//2))
    text=(row['role']+': '+row['title']).encode('ascii','replace').decode()[:90];draw.text((x+8,y+width+6),text,fill=(0,0,0))
   path=folder/('reference-board-'+str(i+1)+'.jpg');sheet.save(path,'JPEG',quality=98);paths.append(str(path))
  legend.append('Reference image '+str(i+1)+': '+'; '.join(r['role']+' = '+r['title'] for r in group))
 return paths,rows,legend
