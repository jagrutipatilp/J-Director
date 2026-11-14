"""Optional user references: plan reusable masters and choose background views locally."""
import hashlib,json
from . import store,story_assets,production,engines
VIEWS={'master':'Master / front wide view','left':'Left quarter view','right':'Right quarter view','high':'High angle view','low':'Low angle view','close':'Close/detail viewpoint','reverse':'Reverse viewpoint'}

def scope_frames(s,scope):
 root=s['nodes'].get(scope,{})
 if root.get('kind')=='clip':
  frame=s['nodes'].get(root.get('depends_on'));return [frame] if frame and not frame.get('output') else []
 return [n for n in s['nodes'].values() if n['kind']=='keyframe' and scope in [a['id'] for a in production.ancestors(s,n).values()] and not n.get('locked') and n['status']!='saved']

def backgrounds(s,frame):
 _,aids=story_assets.automatic(s,frame);result=list(aids)
 ref=production.direction(s,frame).get('background')
 if ref in s['nodes']:
  aid=s['nodes'][ref].get('parent')
  if aid and aid not in result:result.append(aid)
 for rid in frame.get('references',[]):
  owner=s['nodes'].get(s['nodes'].get(rid,{}).get('parent'),{})
  if owner.get('kind')=='location' and owner['id'] not in result:result.append(owner['id'])
 return result

def ensure_master(s,aid):
 asset=s['nodes'][aid];ref=story_assets.reference(s,aid)
 if not ref:
  ref=store.add_node(s,'reference',asset['title']+' / Main reference',parent=aid,prompt=asset['text'],category='Outfits' if asset['kind']=='character' else 'Angles');asset['primary_reference']=ref['id']
 return ref

def ensure_views(s,aid):
 asset=s['nodes'][aid];master=ensure_master(s,aid);result={'master':master['id']};asset['background_master']=master['id']
 for view,label in VIEWS.items():
  if view=='master':continue
  if asset.get('view_policy','single')=='single':
   provided=next((r for r in store.children(s,aid) if r['kind']=='reference' and not r.get('archived') and r.get('view_kind')==view and r.get('provided_view') and r.get('output')),None)
   if provided:result[view]=provided['id']
   continue
  ref=next((r for r in store.children(s,aid) if r['kind']=='reference' and r.get('view_kind')==view and r.get('view_master')==master['id'] and (not r.get('output') or r.get('reference_versions',{}).get(master['id'])==master.get('version',0))),None)
  if not ref:
   ref=store.add_node(s,'reference',asset['title']+' / '+label,parent=aid,prompt='Show the exact same environment from the '+label+'. Preserve architecture, furniture, materials, colors and lighting. No people, captions or collage. '+asset['text'],category='Angles',references=[master['id']],view_kind=view,view_master=master['id'],auto_reference=True)
   if view in ('left','right','high','low','close','reverse'):ref['camera_angle']=view
  result[view]=ref['id']
 asset['background_views']=result
 return result


def checked_choices(batch,result):
 expected={(r['keyframe'],r['background']):r for r in batch};accepted={};invalid=0
 choices=result.get('background_choices',[]) if isinstance(result,dict) else []
 if not isinstance(choices,list):choices=[]
 for choice in choices:
  if not isinstance(choice,dict):invalid+=1;continue
  pair=(choice.get('keyframe'),choice.get('background'));request=expected.get(pair)
  if pair in accepted or not request or choice.get('reference') not in {v['reference'] for v in request['available_views']}:
   invalid+=1;continue
  accepted[pair]={**choice,'source':'ollama'}
 for pair,request in expected.items():
  if pair in accepted:continue
  views=request['available_views']
  if not views:raise ValueError('No background reference is available for this shot')
  overhead=any(word in request['shot'].lower() for word in ('overhead','top-down','top down','high-angle','high angle','bird'))
  selected=next((v for v in views if overhead and v['view']=='High angle view'),None) or next((v for v in views if v['view']=='Master / front wide view'),None) or views[0]
  accepted[pair]={'keyframe':pair[0],'background':pair[1],'reference':selected['reference'],'reason':'Planner choice missing or invalid; using the supplied '+selected['view']+' for this location.','source':'validated_fallback'}
 return list(accepted.values()),invalid

def prepare(pid,scope,report):
 s=store.load(pid);frames=scope_frames(s,scope)
 if not frames:return
 assets=set();background_ids=set()
 for frame in frames:
  chars,_=story_assets.automatic(s,frame)
  for rid in frame.get('references',[]):
   owner=s['nodes'].get(s['nodes'].get(rid,{}).get('parent'),{})
   if owner.get('kind') in ('character','location'):assets.add(owner['id'])
  assets.update(a for a in chars if not s['nodes'][a].get('offscreen'))
  assets.update(row['character'] for row in production.direction(s,frame).get('cast',[]) if not s['nodes'][row['character']].get('offscreen'))
  if frame.get('production',{}).get('inherit_background',True):background_ids.update(backgrounds(s,frame))
 assets.update(background_ids)
 if not assets:return
 from . import stock_backgrounds,library
 for aid in sorted(assets):
  if s['nodes'][aid]['kind']=='character' and library.reuse_character(pid,aid):report('Reusing saved character identity: '+s['nodes'][aid]['title'])
 stock_backgrounds.prepare(pid,assets,report)
 def layout(state):
  for aid in assets:
   ensure_master(state,aid)
   if aid in background_ids:ensure_views(state,aid)
 store.mutate(pid,layout,False);s=store.load(pid);missing=[]
 for aid in sorted(assets):
  asset=s['nodes'][aid];ref=story_assets.reference(s,aid)
  # Never overwrite a user's custom prompt or any existing image.
  if ref.get('output') or ref.get('reference_source') in ('system','catalogue','generate'):continue
  if ref.get('auto_prompt_for')==hashlib.sha256(asset['text'].encode()).hexdigest():continue
  if ref.get('prompt') and ref['prompt']!=asset['text'] and not ref.get('auto_reference'):continue
  missing.append({'asset':aid,'reference':ref['id'],'kind':asset['kind'],'name':asset['title'],'requirements':asset['text'][:5000]})
 for offset in range(0,len(missing),5):
  batch=missing[offset:offset+5];report('Ollama is writing missing reference prompts: '+', '.join(r['name'] for r in batch))
  schema={'type':'object','properties':{'reference_plans':{'type':'array','minItems':len(batch),'maxItems':len(batch),'items':{'type':'object','properties':{k:{'type':'string'} for k in ('asset','reference','prompt')},'required':['asset','reference','prompt']}}},'required':['reference_plans']}
  result=engines.chat(story_assets.planning_rules.RULES+'\nWrite one reusable reference image prompt per supplied asset. Preserve stated ages, identity traits and requirements; fill unspecified visual details coherently once for reuse. Characters: clear identity portrait, neutral presentation, preserve faces across wardrobe changes. Backgrounds: empty environment master wide view, no people; detailed architecture and layout. Follow the story medium/style. No visible captions, logos or collage. Return the exact supplied asset/reference IDs.',json.dumps({'style_context':s['story_working'][:1600],'assets':batch},ensure_ascii=False),schema)
  plans=result.get('reference_plans',[]);expected={(r['asset'],r['reference']) for r in batch};actual=[(r.get('asset'),r.get('reference')) for r in plans]
  if len(actual)!=len(expected) or set(actual)!=expected or any(not r.get('prompt','').strip() for r in plans):raise ValueError('Reference prompt planner returned invalid IDs or incomplete prompts. No images started; retry Run All.')
  def prompts(state):
   for plan in plans:
    ref=state['nodes'][plan['reference']]
    if ref.get('output'):continue
    ref.update(prompt=plan['prompt'],auto_reference=True,auto_prompt_for=hashlib.sha256(state['nodes'][plan['asset']]['text'].encode()).hexdigest())
    if state['nodes'][plan['asset']]['kind']=='location':
     ref['prompt']='Unoccupied environment reference, architecture and scenery only. No people, human figures or silhouettes. '+ref['prompt']
     if not ref.get('negative'):ref['negative']='people, person, human, face, body, crowd, silhouettes, over-sharpened, oversaturated, text, watermark'
    store.log(state,'Auto reference prompt: '+state['nodes'][plan['asset']]['title']+' — '+plan['prompt'])
  store.mutate(pid,prompts,False)
 s=store.load(pid);requests=[]
 for frame in scope_frames(s,scope):
  explicit=production.direction(s,frame).get('background')
  for aid in backgrounds(s,frame) if frame.get('production',{}).get('inherit_background',True) else []:
   views=s['nodes'][aid]['background_views'];manual=[rid for rid in frame.get('references',[]) if s['nodes'].get(rid,{}).get('parent')==aid]
   chosen=explicit if explicit and s['nodes'][explicit].get('parent')==aid else manual[0] if manual else None
   reason='User-selected background reference';source='user'
   if not chosen and len(views)==1:chosen=next(iter(views.values()));reason='Only one background master is needed and available';source='automatic'
   if chosen:
    def pin(state):state['nodes'][frame['id']].setdefault('background_view_selection',{})[aid]={'reference':chosen,'reason':reason,'source':source}
    store.mutate(pid,pin,False);continue
   signature=hashlib.sha256((frame['prompt']+aid+json.dumps(views,sort_keys=True)).encode()).hexdigest();old=frame.get('background_view_selection',{}).get(aid,{})
   if old.get('signature')==signature and old.get('reference') in views.values():continue
   requests.append({'keyframe':frame['id'],'background':aid,'shot':frame['prompt'][:2400],'available_views':[{'reference':rid,'view':VIEWS[v],'description':s['nodes'][rid]['prompt'][:500]} for v,rid in views.items()],'signature':signature})
 for offset in range(0,len(requests),8):
  batch=requests[offset:offset+8];report('Ollama is selecting background viewpoints for '+str(len(batch))+' shots')
  schema={'type':'object','properties':{'background_choices':{'type':'array','minItems':len(batch),'maxItems':len(batch),'items':{'type':'object','properties':{k:{'type':'string'} for k in ('keyframe','background','reference','reason')},'required':['keyframe','background','reference','reason']}}},'required':['background_choices']}
  result=engines.chat('Select exactly one supplied background view for each keyframe/background pair. Decide from the shot description and labeled viewpoint metadata; do not claim to have inspected image pixels. Match camera angle, framing and viewpoint. Use only supplied IDs. Preserve the same location. Return a short reason for each choice.',json.dumps({'shots':batch},ensure_ascii=False),schema)
  choices,invalid=checked_choices(batch,result);expected={(r['keyframe'],r['background']):r for r in batch}
  fallback=sum(c['source']=='validated_fallback' for c in choices)
  if invalid or fallback:
   store.atomic(store.project_dir(pid)/'.planning'/('background-selection-'+store.uid()+'.json'),{'requests':batch,'response':result,'validated_choices':choices,'invalid_count':invalid})
   report('Background planner returned '+str(invalid)+' invalid/duplicate choices; '+str(fallback)+' shots use a validated existing reference. Continuing without extra reference renders.')
  def apply(state):
   for choice in choices:
    pair=(choice['keyframe'],choice['background']);frame=state['nodes'][pair[0]];frame.setdefault('background_view_selection',{})[pair[1]]={'reference':choice['reference'],'reason':choice['reason'],'source':choice['source'],'signature':expected[pair]['signature']}
    store.log(state,'Background view for '+frame['title']+': '+state['nodes'][choice['reference']]['title']+' — '+choice['reason'])
  store.mutate(pid,apply,False)
