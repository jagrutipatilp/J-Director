"""Versioned Omnichar snapshots of selected project characters, kept outside episodes."""
import hashlib,json,re
from pathlib import Path
from PIL import Image
from omnichar_sdk import encode_character,write,Character
from . import store,production,library

def export_selected(s,n,folder):
    rows=production.resolve(s,n);owners={r['owner'] for r in rows if r['role']=='identity'};outputs=[]
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    for owner in sorted(owners):
        asset=s['nodes'].get(owner,{})
        if asset.get('kind')!='character':continue
        canonical=None
        if asset.get('library_asset'):
            try:canonical=library.find(library.load(),asset['library_asset'])
            except ValueError:pass
        canonical_name=canonical['name'] if canonical else asset['title']
        selected=[r for r in rows if r.get('owner')==owner and r['role'] in ('identity','outfit','expression')]
        images=[];sources=[]
        for row in selected:
            ref=s['nodes'][row['id']];path=store.contained(s['id'],ref['output'])
            with Image.open(path) as im:images.append((im.convert('RGB').copy(),'cloth' if row['role']=='outfit' else 'face'))
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            sources.append({'reference':(ref.get('library_variant') or digest) if canonical else ref['id'],'role':row['role'],'sha256':digest})
        if not images:continue
        # Do not rewrite the user's description or invent a trained adapter.
        description=canonical['description'] if canonical else asset.get('text','');payload={'character':canonical['id'] if canonical else owner,'description':description,'sources':sources}
        if not canonical:payload['project']=s['id']
        signature=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()[:16]
        name=re.sub(r'[^A-Za-z0-9_-]+','-',canonical_name).strip('-') or 'Character'
        prefix='catalogue-'+canonical['id'] if canonical else s['id']+'-'+owner
        target=folder/(prefix+'-'+name+'-'+signature+'.char')
        if not target.exists():write(target,encode_character(canonical_name,description,images,resolution=512,app_version='J Director'))
        Character.open(target) # Validate the archive before reporting it as available.
        store.atomic(target.with_suffix('.json'),payload)
        outputs.append({'character':owner,'path':str(target),'signature':signature,'trained_lora':False})
    return outputs
