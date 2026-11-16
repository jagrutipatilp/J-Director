"""Project state and on-disk context for the browser-based director workspace."""
from __future__ import annotations
import copy, json, os, re, threading, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / 'projects'
KINDS = {'arc','episode','scene','sequence','keyframe','clip','character','location','prop','reference'}
STATUSES = {'idle','queued','running','succeeded','failed','saved','redo'}
_LOCK = threading.RLock()

def uid(): return uuid.uuid4().hex[:12]
def slug(text): return re.sub(r'[^a-z0-9]+','-',text.lower()).strip('-')[:70] or 'project'
def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uid() + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)

def project_dir(pid):
    if not re.fullmatch(r'[a-z0-9-]{1,100}',pid): raise ValueError('Invalid project')
    base = (PROJECTS / pid).resolve()
    if not base.is_relative_to(PROJECTS.resolve()): raise ValueError('Invalid project path')
    return base

def contained(pid, relative):
    p = (project_dir(pid) / relative).resolve()
    if not p.is_relative_to(project_dir(pid)): raise ValueError('Path must stay inside this project')
    return p

def load(pid):
    # Readers must not race an atomic replace on Windows. File scanners can also
    # briefly deny sharing, so retry only that transient condition.
    with _LOCK:
        for attempt in range(4):
            try:return json.loads((project_dir(pid)/'project.json').read_text(encoding='utf-8'))
            except PermissionError:
                if attempt==3:raise
                time.sleep(.02*(attempt+1))

def history(pid, state):
    path = project_dir(pid)/'.history.json'
    h = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'undo':[], 'redo':[]}
    snapshot = {k:copy.deepcopy(v) for k,v in state.items() if k not in ('logs','revision')}
    h['undo'] = (h['undo'] + [snapshot])[-40:]; h['redo'] = []
    atomic(path,h)

def log(state, message, level='info'):
    state.setdefault('logs',[]).append({'time':time.time(),'message':message,'level':level})
    state['logs'] = state['logs'][-300:]

def node_dir(state, node):
    root = project_dir(state['id'])
    if node['kind'] in ('character','location','prop'):
        return root/({'character':'characters','location':'backgrounds','prop':'props'}[node['kind']])/(slug(node['title'])+'-'+node['id'][:5])
    if node['kind']=='reference': return node_dir(state,state['nodes'][node['parent']])/'images'/node['id']
    if node['kind']=='arc': return root/'outline'/('arc-'+node['id'])
    if node['kind']=='episode': return root/'outline'/('episode-'+str(node['order']+1).zfill(2)+'-'+node['id'][:5])
    if node['kind'] in ('scene','sequence'):
        return node_dir(state,state['nodes'][node['parent']])/(node['kind']+'-'+str(node['order']+1).zfill(2)+'-'+node['id'][:5])
    return node_dir(state,state['nodes'][node['parent']])/('keyframes' if node['kind']=='keyframe' else 'clips')/node['id']

def persist(state):
    root = project_dir(state['id'])
    if (root/'.deleted-project.json').exists():raise ValueError('This project is deleted. Restore it before editing.')
    previous=load(state['id']) if (root/'project.json').exists() else {}
    state['revision'] = state.get('revision',0)+1
    atomic(root/'project.json', state)
    if previous.get('story_working')!=state['story_working'] or not (root/'story-working.md').exists():
        (root/'story-working.md').write_text(state['story_working'],encoding='utf-8')
    arcs=[]
    for node in state['nodes'].values():
        folder=node_dir(state,node); folder.mkdir(parents=True,exist_ok=True)
        if node['kind']=='arc': arcs.append('# '+node['title']+'\n\n'+node['text'])
        name='reference-prompts.md' if node['kind'] in ('character','location','prop') else (node['kind']+'.md')
        old=previous.get('nodes',{}).get(node['id'],{})
        if old.get('title')!=node['title'] or old.get('text')!=node.get('text') or not (folder/name).exists():
            (folder/name).write_text('# '+node['title']+'\n\n'+node.get('text',''),encoding='utf-8')
        if node['kind'] in ('keyframe','clip','reference'):
            if old.get('prompt')!=node.get('prompt') or not (folder/'prompt.md').exists():
                (folder/'prompt.md').write_text(node.get('prompt',''),encoding='utf-8')
            if node.get('redo_seen') and (old.get('negative')!=node.get('negative') or not (folder/'negative.md').exists()):
                (folder/'negative.md').write_text(node.get('negative',''),encoding='utf-8')
    (root/'outline/arcs.md').write_text('\n\n'.join(arcs),encoding='utf-8')
    episodes=[ep for top in children(state,None) for ep in ([top] if top['kind']=='episode' else children(state,top['id']) if top['kind']=='arc' else []) if ep['kind']=='episode']
    index='# Episodes\n\n'+''.join(str(i)+'. ['+ep['title']+']('+str((node_dir(state,ep)/'episode.md').relative_to(root/'outline')).replace('\\','/')+')\n' for i,ep in enumerate(episodes,1))
    (root/'outline/episodes.md').write_text(index,encoding='utf-8')
    from . import story_assets
    story_assets.persist_docs(state)
    atomic(root/'project.json',state)
    return state

def create(title, story, episode_count=None):
    if episode_count not in (None,''):
        try:episode_count=int(episode_count)
        except (ValueError,TypeError):raise ValueError('Episode count must be a number from 1 to 100')
        if not 1<=episode_count<=100:raise ValueError('Choose 1 to 100 episodes')
    else:episode_count=None
    if not title.strip() or not story.strip(): raise ValueError('Enter a project title and story')
    if len(story)>2_000_000: raise ValueError('Story exceeds the 2 million character limit')
    pid=slug(title)+'-'+uid()[:6]; root=project_dir(pid)
    for folder in ('outline','characters','backgrounds','exports','.engine'): (root/folder).mkdir(parents=True,exist_ok=True)
    (root/'story.md').write_text(story,encoding='utf-8')
    state={'id':pid,'title':title.strip()[:150],'created':time.time(),'revision':0,'story_working':story,'nodes':{},'logs':[],'quality':'final','episode_count':episode_count}
    log(state,'Project created. Original story preserved in story.md.')
    with _LOCK: return persist(state)

def listing():
    PROJECTS.mkdir(exist_ok=True); result=[]
    for p in PROJECTS.glob('*/project.json'):
        if (p.parent/'.deleted-project.json').exists():continue
        try:
            d=json.loads(p.read_text(encoding='utf-8'));result.append({k:d[k] for k in ('id','title','created')})
        except (OSError,ValueError,KeyError): pass
    return sorted(result,key=lambda p:p['created'],reverse=True)

def add_node(state, kind, title, text='', parent=None, **extra):
    if kind not in KINDS: raise ValueError('Invalid node kind')
    if parent and parent not in state['nodes']: raise ValueError('Parent does not exist')
    n={'id':uid(),'kind':kind,'title':str(title)[:160],'text':str(text),'parent':parent,'order':len(children(state,parent)), 'prompt':'','negative':'','status':'idle','locked':False,'redo_seen':False,'references':[],'depends_on':None,'output':None,'progress':None,'dialogue':'','sound':'','seconds':4,**extra}
    state['nodes'][n['id']]=n;return n

def children(state,parent):
    return sorted([n for n in state['nodes'].values() if n['parent']==parent],key=lambda n:n['order'])

def episode_of(state,nid):
    while nid:
        n=state['nodes'][nid]
        if n['kind']=='episode': return nid
        nid=n['parent']
    return None

def is_deleted(pid):return (project_dir(pid)/'.deleted-project.json').is_file()

def mutate(pid, fn, checkpoint=True):
    with _LOCK:
        if is_deleted(pid):raise ValueError('This project is deleted. Restore it before editing.')
        s=load(pid)
        if checkpoint: history(pid,s)
        fn(s)
        return persist(s)

def edit(pid,nid,updates):
    def action(s):
        n=s['nodes'][nid];old_text=n.get('text','')
        if n['locked'] or n['status'] in ('queued','running'): raise ValueError('Use Redo to unlock a saved box; wait for active work to finish')
        if n['status']=='succeeded' and any(k in ('prompt','negative','references','dialogue','sound','seconds','production','asset_links','camera_choices') and v!=n.get(k) for k,v in updates.items()):raise ValueError('Use Redo before changing a generated take')
        allowed={'title','text','prompt','negative','references','dialogue','sound','seconds','production','asset_links','camera_choices'}
        for k,v in updates.items():
            if k not in allowed: continue
            if k=='camera_choices':
                from .generation_settings import camera_validate
                if n['kind'] not in ('keyframe','clip'):raise ValueError('Choose a keyframe or video for camera settings')
                v=camera_validate(v)
            elif k=='asset_links':
                from . import production
                if any(x['status'] in ('running','queued') and nid in [a['id'] for a in production.ancestors(s,x).values()] for x in s['nodes'].values()):raise ValueError('Stop active work before changing linked character/background references')
                if not isinstance(v,dict) or set(v)-{'characters','backgrounds'}:raise ValueError('Choose story character/background links')
                for bucket,ids in v.items():
                    expected='character' if bucket=='characters' else 'location'
                    if not isinstance(ids,list) or any(s['nodes'].get(i,{}).get('kind')!=expected for i in ids):raise ValueError('Choose valid story assets')
                n['asset_links_manual']=True
            elif k=='production':
                from . import production
                affected=[x for x in s['nodes'].values() if x['status'] in ('running','queued') and n['id'] in [a['id'] for a in production.ancestors(s,x).values()]]
                if affected:raise ValueError('Pause or stop active work before changing inherited selections')
                v=production.validate(s,n,v)
            elif k=='references':
                if not isinstance(v,list) or len(v)>30 or any(x not in s['nodes'] or s['nodes'][x]['kind']!='reference' for x in v): raise ValueError('Select valid project reference images')
            elif k=='seconds':
                v=int(v)
                if not 4<=v<=15: raise ValueError('Clips must be 4 to 15 seconds')
            elif not isinstance(v,str) or len(v)>100000: raise ValueError('Invalid field value')
            n[k]=v
        n['error']=None
        if n['kind'] in ('character','location') and 'text' in updates:
            n['description_user_edited']=True
            for ref in children(s,nid):
                if ref['kind']=='reference' and not ref.get('output') and ref['status']=='idle' and ref.get('prompt')==old_text:ref['prompt']=n['text']
        from . import story_assets
        if any(k in updates for k in ('text','prompt','dialogue','sound','title')):story_assets.rebind(s,nid)
    return mutate(pid,action)

def save_box(pid,nid):
    def action(s):
        n=s['nodes'][nid]
        if n['status'] not in ('succeeded','saved'): raise ValueError('Generate a successful result before saving')
        if not n.get('output') or not contained(pid,n['output']).is_file(): raise ValueError('Generated asset is missing')
        n.update(status='saved',locked=True)
        if n['kind']=='reference' and n.get('requires_review'):n['requires_review']=False
        log(s,'Saved and locked '+n['title'])
    state=mutate(pid,action)
    if state['nodes'][nid]['kind']=='reference':
        from . import library
        library.remember_reference(pid,nid)
        state=load(pid)
    return state

def redo_box(pid,nid):
    def action(s):
        n=s['nodes'][nid]
        targets=[n]+[x for x in s['nodes'].values() if x.get('depends_on')==nid]
        if any(x['status'] in ('running','queued') for x in targets): raise ValueError('Wait for these boxes to finish before Redo')
        for i,x in enumerate(targets):
            if x.get('output'):
                p=contained(pid,x['output'])
                if p.is_file(): p.unlink()
            if x.get('temporary_output'):
                temporary=contained(pid,x['temporary_output'])
                if temporary.is_file():temporary.unlink()
            x.update(temporary_output=None,output=None,status='redo' if i==0 else 'idle',locked=False,progress=None,error=None)
            if i==0:x['redo_seen']=True
        log(s,'Redo: '+n['title']+'; dependent clip invalidated.')
    return mutate(pid,action)

def reorder(pid,nid,direction):
    def action(s):
        n=s['nodes'][nid];all_siblings=children(s,n['parent']);positions=[i for i,x in enumerate(all_siblings) if x['kind']==n['kind']];siblings=[all_siblings[i] for i in positions];i=next(i for i,x in enumerate(siblings) if x['id']==nid);j=i+direction
        if 0<=j<len(siblings):siblings[i],siblings[j]=siblings[j],siblings[i]
        for position,x in zip(positions,siblings):all_siblings[position]=x
        for i,x in enumerate(all_siblings):x['order']=i
    return mutate(pid,action)

def undo(pid, direction):
    with _LOCK:
        s=load(pid)
        if any(n['status'] in ('queued','running') for n in s['nodes'].values()): raise ValueError('Wait for active jobs before changing history')
        path=project_dir(pid)/'.history.json';h=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'undo':[],'redo':[]}
        src,dst=('undo','redo') if direction=='undo' else ('redo','undo')
        if not h[src]:raise ValueError('No '+direction+' available')
        previous=h[src].pop();h[dst].append({k:v for k,v in s.items() if k not in ('logs','revision')})
        previous['logs']=s['logs'];previous['revision']=s['revision']
        for n in previous['nodes'].values():
            if n.get('output') and not contained(pid,n['output']).is_file():n.update(output=None,status='redo',locked=False,redo_seen=True)
            if n['status'] in ('queued','running'):n.update(status='idle',progress=None)
        atomic(path,h);log(previous,'History '+direction);return persist(previous)

def refresh(pid):
    def action(s):
        working=project_dir(pid)/'story-working.md'
        if working.exists():s['story_working']=working.read_text(encoding='utf-8')
        for n in s['nodes'].values():
            if n['locked'] or n['status'] in ('running','queued'):continue
            folder=node_dir(s,n)
            context=folder/(('reference-prompts.md' if n['kind'] in ('character','location','prop') else n['kind']+'.md'))
            if context.is_file():
                content=context.read_text(encoding='utf-8');n['text']=content.split('\n\n',1)[-1]
            for field,name in [('prompt','prompt.md'),('negative','negative.md')]:
                p=folder/name
                if p.exists():n[field]=p.read_text(encoding='utf-8')
        log(s,'Re-read editable context and prompt files from disk.')
    return mutate(pid,action)
