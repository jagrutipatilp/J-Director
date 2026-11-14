import json,hashlib,io,time
from pathlib import Path
from PIL import Image
from director_studio import library,store,jobs
assert not jobs.pending(),'Wait for active project work before assigning new references'
store.atomic(store.ROOT/'director_studio/generation-maintenance.json',{'active':True,'reason':'Importing Claire reference pack'})
folder=Path(r'C:\Users\mrkar\Downloads\Railey Refrence\railey model')
files={'body':folder/'railey_armstrong_full_body_reference_1794184172988.jpg','face':folder/'railey_armstrong_facial_model_sheet_1794184735532.jpg','angles':folder/'railey_armstrong_6views_turnaround_1794184538201.jpg','expressions':folder/'railey_armstrong_9_expression_sheet_1794186022711.jpg'}
for p in files.values():assert p.is_file(),str(p)
pack_hash=hashlib.sha256(''.join(p.name+hashlib.sha256(p.read_bytes()).hexdigest() for p in files.values()).encode()).hexdigest()
old=next((a for a in library.load()['assets'] if a['kind']=='character' and a['name'].casefold()=='claire'),None)
a=library.save_asset({'kind':'character','name':'Claire','description':'Reusable core-cast character based on the user-provided Railey reference pack. Keep the supplied facial features and long straight black hair consistent. The supplied wardrobe is a black tailored suit and black shirt. Story-specific names and personalities are separate from this shared appearance.'},old['id'] if old else None);aid=a['id'];made={}
def add(title,category,prompt,source,bounds=None,role=None,sheet=False):
 catalog=library.load();asset=library.find(catalog,aid)
 existing=next((v for v in asset['variants'] if v.get('provenance',{}).get('pack_sha256')==pack_hash and v['title']==title),None)
 if existing:made[title]=existing['id'];return existing['id']
 v=library.save_variant(aid,{'title':title,'category':category,'prompt':prompt})
 raw=source.read_bytes()
 if bounds:
  with Image.open(source) as im:crop=im.crop(bounds).convert('RGB')
  data=io.BytesIO();crop.save(data,'JPEG',quality=95,subsampling=0);raw=data.getvalue()
 saved=library.save_image(aid,v['id'],raw)
 with library.LOCK:
  catalog=library.load();asset=library.find(catalog,aid);variant=library.variant(asset,v['id']);variant['provenance']={'origin':'user-provided reference pack' if not bounds else 'panel extracted from user-provided sheet','source_path':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_bounds':bounds,'pack_sha256':pack_hash,'role':role,'reference_sheet':sheet,'ai_generated_here':False};library.persist(catalog)
 assert library.media_path(saved['output']).read_bytes()==raw
 made[title]=v['id'];return v['id']
body=add('Master full body and black business outfit','Outfits','Use the supplied body proportions and black business outfit. Preserve the Claire identity; do not redesign her face.',files['body'],role='body')
add('Original facial model sheet','Angles','Original supplied facial reference sheet. Use individual face panels when a single portrait is required.',files['face'],role='sheet',sheet=True)
add('Original six-view turnaround sheet','Angles','Original supplied six-view turnaround. Individual views are available separately.',files['angles'],role='sheet',sheet=True)
add('Original nine-expression sheet','Expressions','Original supplied expression sheet. Use individual expression panels when selecting one emotion.',files['expressions'],role='sheet',sheet=True)
face_names=['Front neutral portrait','Three-quarter portrait','Side profile portrait','Lowered gaze portrait','Three-quarter slight smile','Front alternate portrait']
for i,name in enumerate(face_names):
 row,col=divmod(i,3)
 with Image.open(files['face']) as im:w,h=im.size
 b=[round(col*w/3)+2,round(row*h/2)+2,round((col+1)*w/3)-2,round((row+1)*h/2)-2]
 add(name,'Angles','Claire facial identity reference: '+name+'. Preserve these facial features, hair and natural appearance.',files['face'],b,role='identity')
angle_names=['Front body view','Three-quarter body view','Side body view','Rear body view','High-angle body view','Low-angle body view']
for i,name in enumerate(angle_names):
 with Image.open(files['angles']) as im:w,h=im.size
 b=[round(i*w/6)+2,38,round((i+1)*w/6)-2,h-2]
 add(name,'Angles','Claire pose and wardrobe reference: '+name+'. Keep the same black suit and hair.',files['angles'],b,role='body')
expression_names=['Small smile','Tearful','Laughing','Neutral','Subtle smile','Chin raised','Furrowed brows','Tilted smile','Soft smile']
for i,name in enumerate(expression_names):
 row,col=divmod(i,3)
 with Image.open(files['expressions']) as im:w,h=im.size
 b=[round(col*w/3)+2,round(row*h/3)+2,round((col+1)*w/3)-2,round((row+1)*h/3)-2]
 add('Expression '+str(i+1).zfill(2)+' - '+name,'Expressions','Claire expression reference: '+name+'. Keep the same facial appearance; apply only this expression when selected.',files['expressions'],b,role='expression')
with library.LOCK:
 catalog=library.load();asset=library.find(catalog,aid);asset.update(primary_variant=made['Front neutral portrait'],default_outfit_variant=body,core_cast=True,reference_pack_source=str(folder),reference_pack_sha256=pack_hash);library.persist(catalog)
if not any(a['kind']=='character' and a['name'].casefold()=='annie' for a in library.load()['assets']):library.save_asset({'kind':'character','name':'Annie','description':'Reusable core-cast character. Add the user-selected reference pack before using this identity. No appearance is assigned yet.'})
result=library.attach('test1-8922ff',aid,target_asset='454048cb46c3');s=result['project'];role=s['nodes']['454048cb46c3'];assert role['title']=='Isabella Carter' and role['library_asset']==aid
primary=s['nodes'][role['primary_reference']];assert primary['library_variant']==made['Front neutral portrait'];assert role['default_outfit'];assert primary.get('output')
summary={'catalogue_character':'Claire','catalogue_id':aid,'project_role':'Isabella Carter','project':'test1-8922ff','references':len(library.find(library.load(),aid)['variants']),'primary_reference':primary['id'],'primary_path':str(store.contained(s['id'],primary['output'])),'outfit_reference':role['default_outfit'],'folder':str(library.ROOT/'characters'/aid),'original_files_unchanged':True,'no_ai_regeneration':True,'annie':'placeholder, no images yet'}
Path('logs/claire-catalogue-import.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,ensure_ascii=True))
