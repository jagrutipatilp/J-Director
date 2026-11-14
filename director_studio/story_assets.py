"""Project-owned characters/backgrounds and requirement/usage documents. Catalogue is separate."""
import hashlib,json,re,time
from . import store,planning_rules

def key(text):return re.sub(r'[^\w]+',' ',text.casefold()).strip()
def asset_nodes(s):return [n for n in s['nodes'].values() if n['kind'] in ('character','location') and not n.get('archived')]
def scope_text(n):return '\n'.join(str(n.get(k,'')) for k in ('title','text','prompt','dialogue','sound'))
def code(s,nid):
 n=s['nodes'].get(nid);parts=[]
 if not n:return 'story'
 if n['kind']=='clip':
  frame=s['nodes'].get(n.get('depends_on'))
  peers=[x for x in store.children(s,n['parent']) if x['kind']=='clip' and x.get('depends_on')==n.get('depends_on')]
  return code(s,frame['id'])+'kv'+str(next((i+1 for i,x in enumerate(peers) if x['id']==nid),1)) if frame else n['title']
 while n:
  if n['kind'] in ('episode','scene','keyframe'):
   siblings=[x for x in store.children(s,n['parent']) if x['kind']==n['kind']]
   index=next((i+1 for i,x in enumerate(siblings) if x['id']==n['id']),1)
   parts.append({'episode':'ep','scene':'s','keyframe':'k'}[n['kind']]+str(index))
  n=s['nodes'].get(n.get('parent'))
 return ''.join(reversed(parts)) or 'story'
def rebind(s,nid):
 n=s['nodes'].get(nid)
 if n and n.get('asset_links_manual'):
  selected=set(n.get('asset_links',{}).get('characters',[])+n.get('asset_links',{}).get('backgrounds',[]))
  for asset in asset_nodes(s):
   if asset['id'] not in selected:asset.setdefault('requirements',{}).pop(nid,None)
  for aid in n.get('asset_links',{}).get('characters',[])+n.get('asset_links',{}).get('backgrounds',[]):
   if aid in s['nodes']:s['nodes'][aid].setdefault('requirements',{})[nid]={'text':scope_text(n),'updated':time.time()}
  return
 if not n or n['kind'] not in ('episode','scene','keyframe','clip'):return
 text=key(scope_text(n));links={'characters':[],'backgrounds':[]}
 for asset in asset_nodes(s):
  names=[asset['title']]+asset.get('aliases',[])
  if any(key(name) and re.search(r'(?<!\w)'+re.escape(key(name))+r'(?!\w)',text) for name in names):links['characters' if asset['kind']=='character' else 'backgrounds'].append(asset['id'])
 n['asset_links']=links
 selected=set(links['characters']+links['backgrounds'])
 effective_characters,effective_backgrounds=automatic(s,n)
 selected.update(effective_characters+effective_backgrounds)
 for asset in asset_nodes(s):
  if asset['id'] not in selected:asset.setdefault('requirements',{}).pop(nid,None)
 for aid in selected:
  s['nodes'][aid].setdefault('requirements',{})[nid]={'text':scope_text(n),'updated':time.time()}
def reference(s,aid):
 primary=s['nodes'].get(s['nodes'].get(aid,{}).get('primary_reference'))
 if primary and primary.get('parent')==aid and primary.get('kind')=='reference':return primary
 refs=[n for n in store.children(s,aid) if n['kind']=='reference' and not n.get('archived') and not n.get('requires_review')]
 return next((n for n in refs if n.get('output') and n.get('status') in ('saved','succeeded')),None) or next(iter(refs),None)
def automatic(s,n):
 from . import production
 chain=production.ancestors(s,n);characters=[];backgrounds=[]
 for level in ('episode','scene','sequence','keyframe','clip'):
  scope=chain.get(level)
  if not scope:continue
  links=scope.get('asset_links',{})
  if links.get('characters') or scope.get('asset_links_manual'):characters=links.get('characters',[])
  if links.get('backgrounds') or scope.get('asset_links_manual'):backgrounds=links.get('backgrounds',[])
 return [aid for aid in characters if aid in s['nodes'] and not s['nodes'][aid].get('archived') and s['nodes'][aid].get('reference_policy')!='prompt_only'],[aid for aid in backgrounds if aid in s['nodes'] and not s['nodes'][aid].get('archived')]

def upsert(s,result,scopes):
 valid=set(scopes);created=[]
 for nid in valid:
  if nid in s['nodes'] and not s['nodes'][nid].get('asset_links_manual'):
   s['nodes'][nid]['asset_links']={'characters':[],'backgrounds':[]}
   for asset in asset_nodes(s):asset.setdefault('requirements',{}).pop(nid,None)
 for bucket,kind in (('characters','character'),('backgrounds','location')):
  for row in result.get(bucket,[]):
   name=row.get('name','').strip();description=row.get('description','').strip()
   if not name or not description:continue
   if kind=='character':
    override=s.get('asset_policy_overrides',{}).get(key(name))
    if override:row={**row,'reference_policy':override}
   if kind=='character' and planning_rules.incidental(row):
    prior=next((a for a in asset_nodes(s) if a['kind']=='character' and key(a['title'])==key(name)),None)
    if prior:planning_rules.retire(s,prior['id'])
    for nid in row.get('used_in',[]):
     if nid in s['nodes']:s['nodes'][nid].setdefault('incidental_figures',{})[name]=description
    continue
   asset=next((a for a in asset_nodes(s) if a['kind']==kind and key(name) in [key(a['title'])]+[key(x) for x in a.get('aliases',[])]),None)
   if not asset:
    asset=store.add_node(s,kind,name,description,managed_by='story',requirements={},aliases=[]);created.append(asset['id'])
    store.add_node(s,'reference',name+' / Main reference',parent=asset['id'],prompt=description,category='Outfits' if kind=='character' else 'Angles')
   elif asset.get('managed_by')=='story' and not asset.get('description_user_edited'):asset['text']=description
   if kind=='location' and not asset.get('view_policy_locked'):asset['view_policy']=row.get('view_policy',asset.get('view_policy','single'))
   if kind=='character':asset['reference_policy']='persistent'
   if isinstance(row.get('aliases'),list):asset['aliases']=list(dict.fromkeys(asset.get('aliases',[])+[a for a in row['aliases'] if isinstance(a,str)]))
   if row.get('offscreen'):asset['offscreen']=True
   used=[i for i in row.get('used_in',[]) if i in valid]
   for nid in used:
    asset.setdefault('requirements',{})[nid]={'text':description,'updated':time.time()}
    if nid in s['nodes'] and not s['nodes'][nid].get('asset_links_manual'):
     ids=s['nodes'][nid].setdefault('asset_links',{}).setdefault(bucket,[])
     if asset['id'] not in ids:ids.append(asset['id'])
 for nid in valid:
  if nid in s['nodes']:
   # Keep explicit extracted links; add exact name mentions as well.
   old=s['nodes'][nid].get('asset_links',{});rebind(s,nid)
   for bucket,ids in old.items():
    for aid in ids:
     if aid not in s['nodes'][nid]['asset_links'].setdefault(bucket,[]):s['nodes'][nid]['asset_links'][bucket].append(aid)
 return created

def persist_docs(s):
 assets=asset_nodes(s);actual={a['id']:set() for a in assets}
 from . import production
 for n in s['nodes'].values():
  for aid in n.get('asset_links',{}).get('characters',[])+n.get('asset_links',{}).get('backgrounds',[]):
   if aid in actual:actual[aid].add(n['id'])
  if n['kind'] in ('keyframe','clip'):
   frame=s['nodes'].get(n.get('depends_on'),n) if n['kind']=='clip' else n
   for rid in production.ids(s,frame):
    aid=s['nodes'][rid].get('parent')
    if aid in actual:actual[aid].add(n['id'])
 for asset in assets:
  uses=set(asset.get('requirements',{}))|actual[asset['id']]
  asset['used_in']=[code(s,nid) for nid in sorted(uses) if nid=='story' or nid in s['nodes']]
  folder=store.node_dir(s,asset);folder.mkdir(parents=True,exist_ok=True)
  (folder/'used-in.md').write_text('# Used in\n\n'+'\n'.join('- '+u for u in asset['used_in']),encoding='utf-8')
  text='# '+asset['title']+' — requirements\n\n'+asset['text']
  for nid,req in asset.get('requirements',{}).items():
   if nid=='story' or nid in s['nodes']:text+='\n\n## '+code(s,nid)+'\n\n'+req['text']
  (folder/'requirements.md').write_text(text,encoding='utf-8')

def written_inventory(state,source,scopes):
 from . import engines
 story=state['story_working'];end=re.search(r'(?im)^\s*(?:#{1,6}\s*)?EPISODE\s+\d+\s*[:—–-]',story);profiles=story[:end.start()] if end else story
 headings=list(re.finditer(r'(?im)^\s*\d+[.)]\s+([^\r\n(]+?)\s*\((?:Female|Male|Main|Supporting)[^\r\n)]*\)\s*$',profiles))
 if not headings:return None
 characters=[];aliases={}
 for index,heading in enumerate(headings):
  name=heading[1].strip();description=profiles[heading.end():headings[index+1].start() if index+1<len(headings) else len(profiles)].strip();first=name.split()[0]
  used=[sid for sid,text in scopes.items() if re.search(r'(?i)\b'+re.escape(first)+r'\b',text)]
  characters.append({'name':name,'description':description,'aliases':[first],'used_in':used});aliases[first.casefold()]=name
 # Supporting speakers are explicit roles, never invented identities.
 for speaker in dict.fromkeys(re.findall(r"(?m)^([A-Z][A-Za-z .'-]{1,40}):\s*[\x22\u201c]",source)):
  if speaker.casefold() in aliases:continue
  used=[sid for sid,text in scopes.items() if re.search(r'(?m)^'+re.escape(speaker)+r':',text)]
  characters.append({'name':speaker,'description':'Supporting speaking role: '+speaker+'. Appearance is not specified in the script.','used_in':used,'offscreen':'phone' in speaker.casefold()})
 backgrounds=[]
 for scene in engines.explicit_scenes(source):
  location=re.search(r'(?im)^\s*Location\s*:\s*([^\r\n]+)',scene['text'])
  if not location:continue
  name=location[1].strip().rstrip('\\.');description='Location: '+name
  frames=engines.explicit_keyframes(scene['text'])
  if frames:
   sentences=re.split(r'(?<=[.!?])\s+',frames[0]['prompt'])
   environment=[sentence for sentence in sentences if not re.search(r'(?i)\b(?:woman|man|isabella|alexander|she|he)\b',sentence)]
   description+='\n'+' '.join(environment[:3])
  used=[sid for sid,text in scopes.items() if name.casefold() in text.casefold()]
  row=next((r for r in backgrounds if r['name']==name),None)
  if row:row['used_in']=list(set(row['used_in']+used))
  else:backgrounds.append({'name':name,'description':description,'used_in':used})
 return {'characters':characters,'backgrounds':backgrounds} if backgrounds else None

def discover(pid,nid,report):
 from . import engines
 s=store.load(pid);text=s['story_working'] if not nid else scope_text(s['nodes'][nid]);digest=hashlib.sha256(text.encode()).hexdigest();tag=nid or 'story'
 if s.get('asset_discovery',{}).get(tag)==digest:return
 report('Discovering story-owned characters and backgrounds for '+(s['nodes'][nid]['title'] if nid else 'the outline'))
 context=engines.compact_story(text,report) if len(text)>20000 else text
 scopes={tag:text}
 from . import production
 scopes.update({n['id']:scope_text(n) for n in s['nodes'].values() if n['kind'] in ('episode','scene','keyframe','clip') and (not nid or nid in [a['id'] for a in production.ancestors(s,n).values()])})
 existing=[{'kind':a['kind'],'name':a['title'],'description':a['text'][:600]} for a in asset_nodes(s)]
 schema={'type':'object','properties':{bucket:{'type':'array','items':{'type':'object','properties':{'name':{'type':'string'},'description':{'type':'string'},'used_in':{'type':'array','items':{'type':'string'}},'reference_policy':{'type':'string','enum':['persistent','prompt_only']},'view_policy':{'type':'string','enum':['single','multi']}},'required':['name','description','used_in']}} for bucket in ('characters','backgrounds')},'required':['characters','backgrounds']}
 result=written_inventory(s,text,scopes)
 if result:report('Reading written character profiles and location fields directly; no AI rewrite')
 if result is None:result=engines.chat(planning_rules.RULES+'\nExtract characters and physical backgrounds explicitly required by this story text. Return characters and backgrounds, with name, detailed visual description and used_in IDs selected ONLY from the supplied scope IDs. Reuse existing asset names exactly. Do not invent named people, clothing or locations. Separate different required places. These are project requirement documents, not image generation. Preserve existing identity facts.',json.dumps({'selected_text':context,'existing_assets':existing,'scopes':{k:v[:400] for k,v in scopes.items()}},ensure_ascii=False),schema)
 def apply(state):
  current=state['story_working'] if not nid else scope_text(state['nodes'][nid])
  if hashlib.sha256(current.encode()).hexdigest()!=digest:raise ValueError('Text changed during asset discovery; retry to use the latest text')
  created=upsert(state,result,scopes);state.setdefault('asset_discovery',{})[tag]=digest;store.log(state,'Story requirements updated: '+str(len(created))+' new characters/backgrounds. No images generated.')
 return store.mutate(pid,apply)


def create(pid,kind,name,description='',scope=None):
 if kind not in ('character','location') or not name.strip():raise ValueError('Enter a character or background name')
 made=[]
 def apply(s):
  if any(a['kind']==kind and key(a['title'])==key(name) for a in asset_nodes(s)):raise ValueError('That story asset already exists; edit it in the tree')
  asset=store.add_node(s,kind,name,description,managed_by='story',requirements={});made.append(asset['id'])
  if kind=='character':s.setdefault('asset_policy_overrides',{})[key(name)]='persistent'
  store.add_node(s,'reference',name+' / Main reference',parent=asset['id'],prompt=description,category='Outfits' if kind=='character' else 'Angles')
  if scope in s['nodes']:
   bucket='characters' if kind=='character' else 'backgrounds';s['nodes'][scope].setdefault('asset_links',{}).setdefault(bucket,[]).append(asset['id'])
 return {'project':store.mutate(pid,apply),'asset':made[0]}

def add_reference(pid,aid,source,prompt='',catalogue_asset=None,catalogue_variant=None):
 from . import library
 s=store.load(pid);asset=s['nodes'].get(aid,{})
 if asset.get('kind') not in ('character','location'):raise ValueError('Select a story character or background')
 if source not in ('generate','system','catalogue'):raise ValueError('Choose generate, system or catalogue')
 raw=None;origin=None
 if source=='catalogue':
  catalog=library.find(library.load(),catalogue_asset);v=library.variant(catalog,catalogue_variant)
  if catalog['kind']!=asset['kind'] or v.get('archived') or not v.get('output'):raise ValueError('Choose a valid catalogue image of the matching asset type')
  raw=library.media_path(v['output']).read_bytes();origin={'asset':catalogue_asset,'variant':catalogue_variant,'version':v['version']}
 text=prompt.strip() or asset['text']
 if source=='generate' and not text:raise ValueError('Enter a reference-image prompt')
 made=[]
 def apply(state):
  a=state['nodes'][aid];ref=store.add_node(state,'reference',a['title']+' / Reference '+str(len(store.children(state,aid))+1),parent=aid,prompt=text,category='Outfits' if a['kind']=='character' else 'Angles',reference_source=source);made.append(ref['id'])
  a['primary_reference']=ref['id']
  if raw:
   target=store.node_dir(state,ref)/'preview.jpg';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
   ref.update(output=str(target.relative_to(store.project_dir(pid))).replace('\\','/'),status='saved',locked=True,version=1,catalogue_origin=origin)
 state=store.mutate(pid,apply);return {'project':state,'reference':made[0]}


def require_character_references(state,scope):
 from . import production
 root=state['nodes'].get(scope)
 if not root:return
 required=set()
 for node in state['nodes'].values():
  if scope not in [a['id'] for a in production.ancestors(state,node).values()]:continue
  if node['kind'] not in ('episode','scene','sequence','keyframe','clip'):continue
  frame=state['nodes'].get(node.get('depends_on'),node) if node['kind']=='clip' else node
  characters,_=automatic(state,frame);required.update(characters)
  for row in production.direction(state,frame).get('cast',[]):required.add(row['character'])
  for rid in frame.get('references',[]):
   ref=state['nodes'].get(rid,{});asset=state['nodes'].get(ref.get('parent'),{})
   if asset.get('kind')=='character':required.add(asset['id'])
 missing=[]
 for aid in required:
  asset=state['nodes'].get(aid,{})
  if asset.get('offscreen'):continue
  ref=reference(state,aid)
  if not ref or not ref.get('output') or ref.get('status') not in ('saved','succeeded') or not store.contained(state['id'],ref['output']).is_file():missing.append(asset.get('title','Unknown character'))
 if missing:raise ValueError('Add or generate a reference image for these visible characters before Run All: '+', '.join(sorted(missing)))
