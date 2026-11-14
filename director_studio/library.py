"""User-created, versioned character and location library shared across stories."""
from __future__ import annotations
import copy, io, json, threading, time
from pathlib import Path
from PIL import Image, ImageOps
from . import store

ROOT=store.ROOT/'library'
LOCK=threading.RLock()
CATEGORIES={'Outfits','Expressions','Accessories','Dialogs','Hairstyles','Poses','Angles'}

def load():
    path=ROOT/'catalog.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'assets':[]}

def persist(catalog):
    store.atomic(ROOT/'catalog.json',catalog)
    for asset in catalog['assets']:
        folder=ROOT/({'character':'characters','location':'locations','prop':'props'}[asset['kind']])/asset['id'];folder.mkdir(parents=True,exist_ok=True)
        text='# '+asset['name']+'\n\n'+asset['description']
        for variant in asset['variants']:
            text+='\n\n## '+variant['title']+' · '+variant['category']+'\n\n'+variant['prompt']+'\n\nVersion: '+str(variant['version'])
        (folder/'reference-prompts.md').write_text(text,encoding='utf-8')
    return catalog

def canonical_id(catalog,aid):
    seen=set()
    while aid in catalog.get('asset_aliases',{}):
        if aid in seen:raise ValueError('Invalid catalogue alias cycle')
        seen.add(aid);aid=catalog['asset_aliases'][aid]
    return aid

def find(catalog,aid):
    aid=canonical_id(catalog,aid)
    for asset in catalog['assets']:
        if asset['id']==aid:return asset
    raise ValueError('Shared asset does not exist')

def merge_assets(source_id,target_id):
    with LOCK:
        catalog=load();source=find(catalog,source_id);target=find(catalog,target_id)
        if source['id']==target['id']:return copy.deepcopy(target)
        if source['kind']!=target['kind']:raise ValueError('Merge matching asset types only')
        backup=ROOT/'merge-backups'/store.uid();backup.mkdir(parents=True);store.atomic(backup/'catalog.json',catalog)
        known={v['id'] for v in target['variants']}
        target['variants'].extend(copy.deepcopy(v) for v in source['variants'] if v['id'] not in known)
        target['aliases']=sorted(set(target.get('aliases',[])+source.get('aliases',[])+[source['name'],'Railey'] if source['name'].casefold()=='raily' else target.get('aliases',[])+source.get('aliases',[])+[source['name']]))
        target.setdefault('merged_assets',[]).append({'id':source['id'],'name':source['name'],'description':source.get('description',''),'merged_at':time.time()})
        target['updated']=time.time();catalog.setdefault('asset_aliases',{})[source['id']]=target['id'];catalog['assets']=[a for a in catalog['assets'] if a['id']!=source['id']];persist(catalog)
        return copy.deepcopy(target)


def variant(asset,vid):
    for v in asset['variants']:
        if v['id']==vid:return v
    raise ValueError('Reference variant does not exist')

def media_path(relative):
    path=(ROOT/relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or path.suffix.lower() not in ('.jpg','.jpeg','.png','.webp'):raise ValueError('Invalid library image')
    return path

def save_asset(data,aid=None):
    name=str(data.get('name','')).strip();description=str(data.get('description','')).strip();kind=data.get('kind')
    if kind not in ('character','location','prop') or not name or len(name)>120 or len(description)>12000:raise ValueError('Enter a name and valid character/location/prop details')
    with LOCK:
        catalog=load()
        if aid:
            asset=find(catalog,aid)
            if asset['kind']!=kind:raise ValueError('A character cannot be changed into a location')
            asset.update(name=name,description=description,updated=time.time())
        else:
            asset={'id':store.uid(),'kind':kind,'name':name,'description':description,'created':time.time(),'updated':time.time(),'variants':[]};catalog['assets'].append(asset)
        persist(catalog);return copy.deepcopy(asset)

def save_variant(aid,data,vid=None):
    category=data.get('category','Outfits');title=str(data.get('title','')).strip();prompt=str(data.get('prompt','')).strip()
    if category not in CATEGORIES or not title or not prompt or len(prompt)>16000:raise ValueError('Enter a reference title, category and prompt')
    with LOCK:
        catalog=load();asset=find(catalog,aid)
        if vid:
            v=variant(asset,vid);v.update(title=title[:160],category=category,prompt=prompt)
        else:
            v={'id':store.uid(),'title':title[:160],'category':category,'prompt':prompt,'version':0,'output':None};asset['variants'].append(v)
        asset['updated']=time.time();persist(catalog);return copy.deepcopy(v)

def archive_variant(aid,vid,removed=True):
    with LOCK:
        catalog=load();asset=find(catalog,aid);v=variant(asset,vid)
        v['archived']=bool(removed);asset['updated']=time.time();persist(catalog)
        return copy.deepcopy(v)

def save_image(aid,vid,raw):
    if len(raw)>30*1024*1024:raise ValueError('Use an image smaller than 30 MB')
    try:
        im=Image.open(io.BytesIO(raw));im.load();preserve_jpeg=raw[:3]==b'\xff\xd8\xff' and im.mode=='RGB' and im.getexif().get(274,1)==1;im=ImageOps.exif_transpose(im).convert('RGB')
    except Exception:raise ValueError('Choose a valid image')
    with LOCK:
        catalog=load();asset=find(catalog,aid);v=variant(asset,vid);version=v['version']+1
        folder=ROOT/({'character':'characters','location':'locations','prop':'props'}[asset['kind']])/aid/'images';folder.mkdir(parents=True,exist_ok=True)
        target=folder/(vid+'-v'+str(version).zfill(3)+'.jpg')
        if preserve_jpeg:target.write_bytes(raw)
        else:im.save(target,'JPEG',quality=95)
        v.update(output=str(target.relative_to(ROOT)).replace('\\','/'),version=version);asset['updated']=time.time();persist(catalog);return copy.deepcopy(v)

def attach(pid,aid,vids=None,target_asset=None):
    with LOCK:
        catalog=load();asset=copy.deepcopy(find(catalog,aid))
    aid=asset['id']
    variants=[v for v in asset['variants'] if not v.get('archived') and (not vids or v['id'] in vids)]
    requested=[v['id'] for v in variants]
    if asset['kind']=='character':
        defaults={asset.get('primary_variant'),asset.get('default_outfit_variant')}
        variants += [v for v in asset['variants'] if v['id'] in defaults and v['id'] not in requested and not v.get('archived')]
    masters={v.get('provenance',{}).get('master_variant') for v in variants}
    variants += [v for v in asset['variants'] if v['id'] in masters and v['id'] not in requested]
    if not variants:raise ValueError('Add at least one reference variant first')
    refs=[]
    def action(s):
        parent=s['nodes'].get(target_asset) if target_asset else next((n for n in s['nodes'].values() if canonical_id(catalog,n.get('library_asset'))==aid and n['kind']==asset['kind']),None)
        if target_asset and (not parent or parent['kind']!=asset['kind']):raise ValueError('Choose a matching story character or background')
        old_refs=[n['id'] for n in s['nodes'].values() if target_asset and n.get('parent')==target_asset and n['kind']=='reference' and n.get('library_asset')!=aid]
        if target_asset:parent.update(library_asset=aid,catalogue_name=asset['name'])
        if not parent:parent=store.add_node(s,asset['kind'],asset['name'],asset['description'],library_asset=aid)
        parent['library_asset']=aid
        parent['catalogue_name']=asset['name']
        for v in variants:
            existing=next((n for n in s['nodes'].values() if n['kind']=='reference' and n.get('parent')==parent['id'] and n.get('library_variant')==v['id'] and n.get('library_version')==v['version']),None)
            if existing:refs.append(existing['id']);continue
            ref=store.add_node(s,'reference',parent['title']+' / '+v['title'],parent=parent['id'],prompt=v['prompt'],category=v['category'],library_asset=aid,library_variant=v['id'],library_version=v['version'])
            ref['source_provenance']=copy.deepcopy(v.get('provenance',{}))
            if v['output']:
                folder=store.node_dir(s,ref);folder.mkdir(parents=True,exist_ok=True);target=folder/'preview.jpg';target.write_bytes(media_path(v['output']).read_bytes())
                ref.update(output=str(target.relative_to(store.project_dir(pid))).replace('\\','/'),status='saved',locked=True,version=v['version'])
            if v.get('provenance',{}).get('fast_reference_edit'):ref['fast_reference_edit']=True
            refs.append(ref['id'])
        for v in variants:
            master_id=v.get('provenance',{}).get('master_variant')
            if not master_id:continue
            ref=next((n for n in s['nodes'].values() if n['kind']=='reference' and n.get('parent')==parent['id'] and n.get('library_variant')==v['id'] and n.get('library_version')==v['version']),None)
            master=next((n for n in s['nodes'].values() if n['kind']=='reference' and n.get('library_variant')==master_id and n.get('library_version')==variant(asset,master_id)['version']),None)
            if ref and master:
                ref['references']=[master['id']]
                angle=v.get('provenance',{}).get('camera_angle')
                if angle in ('high','low','left','right'):ref['camera_angle']=angle
        if asset['kind']=='character':
            imported={n.get('library_variant'):n for n in s['nodes'].values() if n.get('parent')==parent['id'] and n.get('library_asset')==aid and n.get('output')}
            primary=imported.get(asset.get('primary_variant'));outfit=imported.get(asset.get('default_outfit_variant'))
            if primary:parent['primary_reference']=primary['id']
            if outfit:parent['default_outfit']=outfit['id']
            if target_asset and primary:
                for rid in old_refs:s['nodes'][rid]['archived']=True
                for shot in s['nodes'].values():
                    if shot['id'] in old_refs:continue
                    if shot.get('references'):shot['references']=[rid for rid in shot['references'] if rid not in old_refs]
                    for row in shot.get('production',{}).get('cast',[]):
                        if row.get('character')==target_asset:
                            row['identity']=primary['id']
                            if outfit and (not row.get('outfit') or row.get('outfit') in old_refs):row['outfit']=outfit['id']
                    expression=shot.get('production',{}).get('expressions',{})
                    if expression.get(target_asset) in old_refs:expression.pop(target_asset)
                    if shot.get('output') and any(row.get('id') in old_refs for row in shot.get('render_references',[])):
                        shot['reference_update_note']='Character now uses '+asset['name']+' from the catalogue. Existing take was retained; regenerate to use the new reference.'
        refs[:]=[rid for rid in refs if s['nodes'][rid].get('library_variant') in requested]
        store.log(s,('Assigned shared '+asset['name']+' to '+parent['title']+'; old references archived and existing renders retained') if target_asset else 'Attached shared '+asset['kind']+' '+asset['name']+'; existing project references remain unchanged')
    state=store.mutate(pid,action);return {'project':state,'references':refs}

def publish(pid,nid):
    s=store.load(pid);n=s['nodes'][nid]
    if n['kind']!='reference' or not n.get('library_asset') or not n.get('library_variant'):raise ValueError('This is not a shared-library reference')
    if n['status'] not in ('succeeded','saved') or not n.get('output'):raise ValueError('Generate the reference first')
    saved=save_image(n['library_asset'],n['library_variant'],store.contained(pid,n['output']).read_bytes())
    store.mutate(pid,lambda state:state['nodes'][nid].update(library_version=saved['version']))
    return {'variant':saved,'message':'Reference saved to the shared library for future projects'}


def remember_reference(pid,nid):
    state=store.load(pid);ref=state['nodes'][nid];owner=state['nodes'].get(ref.get('parent'),{})
    if ref['kind']!='reference' or owner.get('kind') not in ('character','location') or not ref.get('output'):return
    raw=store.contained(pid,ref['output']).read_bytes()
    catalog=load();aid=owner.get('library_asset') or ref.get('library_asset')
    asset=find(catalog,aid) if aid else next((a for a in catalog['assets'] if a['kind']==owner['kind'] and a['name'].casefold()==owner['title'].casefold()),None)
    if not asset:asset=save_asset({'kind':owner['kind'],'name':owner['title'],'description':owner['text']})
    vid=ref.get('library_variant') if ref.get('library_asset')==asset['id'] else None
    v=variant(asset,vid) if vid else save_variant(asset['id'],{'title':ref['title'],'category':ref.get('category','Angles'),'prompt':ref.get('prompt') or owner['text'] or owner['title']})
    if not v.get('output') or media_path(v['output']).read_bytes()!=raw:v=save_image(asset['id'],v['id'],raw)
    with LOCK:
        catalog=load();a=find(catalog,asset['id'])
        if owner.get('primary_reference')==nid or not a.get('primary_variant'):a['primary_variant']=v['id']
        if owner.get('default_outfit')==nid:a['default_outfit_variant']=v['id']
        variant(a,v['id'])['provenance']=copy.deepcopy(ref.get('source_provenance') or {'origin':'approved project reference'})
        persist(catalog)
    def link(s):
        s['nodes'][owner['id']].update(library_asset=asset['id'],catalogue_name=asset['name'])
        s['nodes'][nid].update(library_asset=asset['id'],library_variant=v['id'],library_version=v['version'])
    store.mutate(pid,link,False)

def reuse_character(pid,aid):
    state=store.load(pid);owner=state['nodes'][aid]
    if owner['kind']!='character':return False
    from . import story_assets
    ref=story_assets.reference(state,aid)
    if ref and ref.get('output'):return True
    catalog=load();asset=find(catalog,owner['library_asset']) if owner.get('library_asset') else next((a for a in catalog['assets'] if a['kind']=='character' and owner['title'].casefold() in [a['name'].casefold()]+[x.casefold() for x in a.get('aliases',[])]),None)
    if not asset:return False
    primary=asset.get('primary_variant');v=next((v for v in asset['variants'] if v['id']==primary and v.get('output') and not v.get('archived')),None)
    if not v:return False
    attach(pid,asset['id'],[v['id']],target_asset=aid);return True
