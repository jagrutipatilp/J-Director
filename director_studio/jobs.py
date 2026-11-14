"""Persistent single-worker operations, shared by HTTP and WebSocket clients."""
from __future__ import annotations
import json, shutil, threading, time
from pathlib import Path
from PIL import Image
from . import store, engines, continuity, production, story_assets, reference_planner

QUEUE=store.ROOT/'director_studio/queue.json'
GUARD=threading.RLock()
STOP=threading.Event()
CURRENT=threading.local()

class WorkStopped(Exception):pass

def control(pid,command):
    if command not in ('pause','resume','stop'):raise ValueError('Unknown work control')
    with GUARD:
        q=queue_state();active=[j for j in q if j['project']==pid and j['state'] in ('queued','running')]
        if not active:raise ValueError('No active work in this project')
        for j in active:
            j['control']=command if command!='resume' else None
            if command=='stop' and j['state']=='queued':j.update(state='stopped',finished=time.time())
        store.atomic(QUEUE,q)
    if command=='stop':reset_queued(pid)
    report(pid,{'pause':'Pause requested: finishing the current item before waiting.','resume':'Resuming work.','stop':'Stop requested: finishing the current item; remaining work cancelled.'}[command])

def reset_queued(pid):
    def reset(state):
        for n in state['nodes'].values():
            if n['status']=='queued':n.update(status='idle',progress=None)
    store.mutate(pid,reset,False)

def checkpoint():
    jid=getattr(CURRENT,'job',None)
    if not jid:return
    if STOP.is_set():raise WorkStopped()
    waiting=False
    while True:
        with GUARD:
            q=queue_state();job=next((j for j in q if j['id']==jid),None)
            if not job:return
            command=job.get('control')
            if command=='stop':raise WorkStopped()
            if command!='pause':
                if job.pop('waiting',False):store.atomic(QUEUE,q)
                return
            if not job.get('waiting'):job['waiting']=True;store.atomic(QUEUE,q)
        if not waiting:report(job['project'],'Paused between items. Resume to continue.');waiting=True
        if STOP.wait(.25):raise WorkStopped()


def queue_state():return json.loads(QUEUE.read_text(encoding='utf-8')) if QUEUE.exists() else []
def pending(pid=None):
    with GUARD:return [j for j in queue_state() if j['state'] in ('queued','running') and (not pid or j['project']==pid)]

def enqueue(pid,operation,ids=None,instruction='',skip_nodes=None):
    migration=QUEUE.with_name('generation-maintenance.json')
    if operation in ('run','episode_run','assets','character_sheet') and migration.is_file() and json.loads(migration.read_text(encoding='utf-8')).get('active'):
        raise ValueError('ComfyUI model installation is in progress. Completed images and projects remain available; generation resumes when setup finishes.')
    s=store.load(pid);ids=ids or []
    if operation not in ('run','enhance','breakdown','assets','episode_run','rebreakdown','import_written','character_sheet'):raise ValueError('Invalid operation')
    if any(i not in s['nodes'] for i in ids):raise ValueError('Select an existing project node')
    if operation=='breakdown' and ids and s['nodes'][ids[0]]['kind'] not in ('arc','episode','scene','sequence'):raise ValueError('Select an outline level to break down')
    with GUARD:
        if store.is_deleted(pid):raise ValueError('Restore this deleted project before generating work')
        q=queue_state()
        activekeys={(j['project'],j['operation'],tuple(j['nodes'])) for j in q if j['state'] in ('queued','running')}
        if (pid,operation,tuple(ids)) in activekeys:raise ValueError('This operation is already queued')
        if operation=='run':
            for nid in ids:
                n=s['nodes'][nid]
                if n['kind'] not in ('keyframe','clip','reference') or n['locked'] or n['status'] not in ('idle','redo','failed'):raise ValueError('Run accepts only editable image/video boxes. Use Redo first for existing results.')
                if not n.get('prompt','').strip():raise ValueError('Enter a prompt for '+n['title'])
        if operation=='character_sheet':
            if len(ids)!=1 or s['nodes'][ids[0]]['kind']!='character':raise ValueError('Select a story character')
            master=story_assets.reference(s,ids[0])
            if not master or not master.get('output'):raise ValueError('Attach a master character reference first')
        if operation=='enhance' and any(s['nodes'][i]['locked'] or s['nodes'][i]['status'] in ('running','queued','succeeded') for i in ids):raise ValueError('Unlock saved boxes with Redo first')
        job={'id':store.uid(),'project':pid,'operation':operation,'nodes':ids,'instruction':instruction[:8000],'state':'queued','created':time.time(),'skip_nodes':skip_nodes or []}
        if operation=='run':
            def mark(state):
                for nid in ids:state['nodes'][nid]['status']='queued'
                store.log(state,'Queued '+str(len(ids))+' generation boxes')
            store.mutate(pid,mark)
        q.append(job);store.atomic(QUEUE,q[-500:]);return job

def node_context(state,nid):
    parts=[];node=state['nodes'].get(nid)
    while node:
        if node['kind']!='arc':parts.append(node['title'])
        node=state['nodes'].get(node.get('parent'))
    return ' / '.join(reversed(parts))

def job_context(job):
    state=store.load(job['project']);nid=job['nodes'][0] if job['nodes'] else None
    context=node_context(state,nid) if nid else state['title']
    name={'episode_run':'Selected work generation','run':'Generation','import_written':'Import written story','rebreakdown':'Redo scene breakdown','breakdown':'Breakdown','enhance':'Prompt refinement','assets':'Reference preparation','character_sheet':'Character Forge sheet'}[job['operation']]
    return name+': '+context

def report(pid,message,nid=None,percent=None,task=None):
    def action(s):
        label=task or message;old=s.get('activity',{});now=time.time()
        s['activity']={'task':label,'detail':message,'node':nid,'started':old.get('started',now) if old.get('task')==label else now,'updated':now,'progress':percent,'active':True}
        store.log(s,(label+' — '+message) if label!=message else message)
        if nid and nid in s['nodes']:
            n=s['nodes'][nid];n['stage']=message
            if message.startswith('ComfyUI queue:'):n['status']='queued'
            elif message.startswith(('ComfyUI rendering','ComfyUI sampling')):n['status']='running'
            if percent is not None:n['progress']=max(0,min(100,percent))
    store.mutate(pid,action,False)

def output_ready(pid,node):
    if not node.get('output'):return False
    try:return store.contained(pid,node['output']).is_file()
    except ValueError:return False


def generate_node(pid,nid,position=None,total=None):
    checkpoint()
    existing=store.load(pid)['nodes'][nid]
    if existing.get('locked') or (existing['status'] in ('saved','succeeded') and output_ready(pid,existing)):return
    jid=getattr(CURRENT,'job',None)
    if jid:
        with GUARD:
            q=queue_state()
            for job in q:
                if job['id']==jid:job['active_node']=nid
            store.atomic(QUEUE,q)
    def start(s):s['nodes'][nid].update(status='running',progress=0,error=None);store.log(s,'Generating '+s['nodes'][nid]['title'])
    s=store.mutate(pid,start,False);n=s['nodes'][nid]
    label='Generating '+({'clip':'video','reference':'reference image','keyframe':'image'}[n['kind']])+': '+node_context(s,nid)
    if position and total:label+=' (item '+str(position)+' of '+str(total)+')'
    report(pid,label,nid,0,task=label)
    try:
        path=engines.generate(s,n,lambda msg,p=None:report(pid,msg,nid,p,task=label));folder=store.node_dir(s,n);folder.mkdir(parents=True,exist_ok=True)
        target=folder/('preview.mp4' if n['kind']=='clip' else 'preview.jpg')
        if n['kind']=='clip':shutil.copy2(path,target)
        else:
            with Image.open(path) as im:im.convert('RGB').save(target,'JPEG',quality=95)
        def finish(state):
            x=state['nodes'][nid];x['version']=x.get('version',0)+1;x['reference_versions']={rid:state['nodes'][rid].get('version',0) for rid in production.ids(s,n)};x['render_references']=production.resolve(s,n)
            x.update(render_quality=s.get('quality','final'),status='succeeded',output=str(target.relative_to(store.project_dir(pid))).replace('\\','/'),progress=100,stage='Ready to review')
            x.pop('reference_update_note',None);x.pop('engine_job',None)
            if path.is_relative_to(store.project_dir(pid)):x['temporary_output']=str(path.relative_to(store.project_dir(pid)))
            store.log(state,'Completed '+x['title']+'. Review and Save to lock it.','success')
        store.mutate(pid,finish,False)
    except WorkStopped:raise
    except Exception as error:
        def fail(state):state['nodes'][nid].update(status='failed',error=str(error),progress=None,stage='Failed');store.log(state,n['title']+': '+str(error),'error')
        store.mutate(pid,fail,False)
        # Continue Run All so independent scenes still get a chance to finish.

def asset_inventory(pid,nid=None):
    return story_assets.discover(pid,nid,lambda message:report(pid,message))


def add_planned_item(state,kind,item,parent):
    node=store.add_node(state,kind,item['title'],item.get('text',''),parent,prompt=item.get('prompt',''),references=[])
    if kind=='keyframe':
        store.add_node(state,'clip',item['title']+' / motion',item.get('text',''),parent,prompt=item.get('video_prompt') or ('Animate this keyframe: '+item.get('prompt','')),dialogue=str(item.get('dialogue','')),sound=str(item.get('sound','')),seconds=max(4,min(15,int(item.get('seconds',4) or 4))),depends_on=node['id'])
    elif item.get('authored'):
        if kind=='episode':
            scenes=engines.explicit_scenes(node['text'])
            if scenes:
                for scene in scenes:add_planned_item(state,'scene',scene,node['id'])
            else:
                for frame in engines.explicit_keyframes(node['text']):add_planned_item(state,'keyframe',frame,node['id'])
        elif kind=='scene':
            for frame in engines.explicit_keyframes(node['text']):add_planned_item(state,'keyframe',frame,node['id'])
    return node

def import_written(pid):
    s=store.load(pid);episodes=engines.explicit_episodes(s['story_working'])
    if not episodes:raise ValueError('Add numbered EPISODE headings before importing written structure')
    if s.get('episode_count') and len(episodes)!=s['episode_count']:raise ValueError('Episode count and written episode headings do not match')
    outline=[n for n in s['nodes'].values() if n['kind'] in ('arc','episode','scene','sequence','keyframe','clip')]
    if any(n.get('output') or n.get('locked') or n['status'] not in ('idle','failed') for n in outline):raise ValueError('This project has rendered or active work. Import into a new project to keep existing work safe.')
    store.atomic(store.project_dir(pid)/'previous-breakdowns'/(str(time.time_ns())+'-written-import.json'),s)
    def apply(state):
        if state['story_working']!=s['story_working'] or state['nodes']!=s['nodes']:raise ValueError('Project changed during import; retry with the latest text')
        for n in outline:del state['nodes'][n['id']]
        for item in episodes:add_planned_item(state,'episode',item,None)
        state['story_summary']=state['story_working'];store.log(state,'Imported written episodes, scenes, keyframes and video prompts exactly. No media generated.')
    store.mutate(pid,apply);asset_inventory(pid)

def breakdown_job(pid,parent,queue_refs=False,replace_existing=False):
    checkpoint()
    s=store.load(pid)
    target=engines.breakdown_target(s,parent)
    existing=[n for n in store.children(s,parent) if n['kind']==target]
    if existing and not replace_existing:
        asset_inventory(pid,parent)
        report(pid,'Existing '+target+' entries kept. Character/background requirements refined from the edited text; no scenes or images were replaced.');return
    if replace_existing:
        if not parent or s['nodes'][parent]['kind']!='episode':raise ValueError('Redo scene breakdown applies to an episode only')
        if any(store.children(s,n['id']) or n.get('output') or n.get('locked') or n['status'] not in ('idle','failed') for n in existing):raise ValueError('Existing scenes contain developed or rendered work. Keep them and edit individually; no work was replaced.')
    kind=s['nodes'][parent]['kind'] if parent else 'story'
    context_title=node_context(s,parent) if parent else s['title']
    label='Breaking down '+kind+': '+context_title+' → '+({'scene':'scenes','sequence':'sequences','keyframe':'image and video shots','episode':'episodes','arc':'story arcs'}[target])
    report(pid,label,task=label)
    target,items,context=engines.breakdown(s,parent,lambda m:report(pid,m,task=label))
    if existing:
        store.atomic(store.project_dir(pid)/'previous-breakdowns'/(str(time.time_ns())+'.json'),{'episode':parent,'episode_text':s['nodes'][parent]['text'],'scenes':existing})
    def apply(state):
        if parent and state['nodes'][parent]['text']!=s['nodes'][parent]['text']:raise ValueError('Episode text changed while planning; retry with the latest text')
        for old in existing:
            current=state['nodes'].get(old['id'])
            if current!=old or store.children(state,old['id']):raise ValueError('Scene changed while planning; nothing was replaced')
        for old in existing:del state['nodes'][old['id']]
        if not parent:state['story_summary']=context
        for item in items:add_planned_item(state,target,item,parent)
        store.log(state,'Breakdown complete: '+context_title+' → '+str(len(items))+' '+target+' entries.')
    store.mutate(pid,apply)
    try:asset_inventory(pid,parent)
    except Exception as e:report(pid,'Outline saved; character/background discovery needs retry: '+str(e))
    if target=='keyframe':
        current=store.load(pid);refs=[n['id'] for n in current['nodes'].values() if n['kind']=='reference' and n['status'] in ('idle','redo','failed')]
        if refs and queue_refs:enqueue(pid,'run',refs)

def plan_story(pid):
    state=store.load(pid)
    existing=[n for n in state['nodes'].values() if n['kind']=='episode']
    if existing:
        asset_inventory(pid)
        report(pid,'Keeping '+str(len(existing))+' existing episodes. Edit and reorder the episode cards; no duplicate plan was created.');return
    arcs=[n for n in store.children(state,None) if n['kind']=='arc']
    if arcs:
        for arc in arcs:breakdown_job(pid,arc['id'],False)
    else:breakdown_job(pid,None,False)
    state=store.load(pid);episodes=[n for n in state['nodes'].values() if n['kind']=='episode']
    report(pid,'Episode plan ready: '+str(len(episodes))+' editable episodes. Reorder with up/down, write episode details, then develop scenes when ready.')


def within(state,nid,root):
    while nid in state['nodes']:
        if nid==root:return True
        nid=state['nodes'][nid].get('parent')
    return False

def run_episode(pid,eid,skip_nodes=None):
    skipped=set(skip_nodes or []);s=store.load(pid)
    if s['nodes'].get(eid,{}).get('kind') not in ('episode','scene','sequence','keyframe','clip'):raise ValueError('Select an episode, scene or shot first')
    root=s['nodes'][eid]
    try:asset_inventory(pid,eid)
    except Exception as e:report(pid,'Using existing story references; discovery needs retry: '+str(e))
    s=store.load(pid)
    if root['kind']=='episode' and not any(within(s,n['id'],eid) and n['kind'] in ('scene','keyframe','sequence') for n in s['nodes'].values()):
        breakdown_job(pid,eid,False);s=store.load(pid)
    for kind in ('scene','sequence'):
        parents=[n for n in s['nodes'].values() if n['kind']==kind and within(s,n['id'],eid)]
        for parent in parents:
            kids=store.children(store.load(pid),parent['id'])
            if not any(n['kind'] in ('keyframe','sequence') for n in kids):
                report(pid,'Preparing keyframes for '+parent['title']);breakdown_job(pid,parent['id'],False)
        s=store.load(pid)
    ordered=[]
    def pair(frame):
        nonlocal s
        clips=[n for n in store.children(s,frame['parent']) if n['kind']=='clip' and n.get('depends_on')==frame['id']]
        if not clips and frame.get('no_auto_clip'):
            ordered.append(frame['id']);return
        if not clips:
            made=[]
            def add_clip(state):made.append(store.add_node(state,'clip',frame['title']+' / motion',frame.get('text',''),frame['parent'],prompt='Animate the supplied starting keyframe. '+frame.get('prompt',''),depends_on=frame['id'])['id'])
            s=store.mutate(pid,add_clip);clips=[s['nodes'][made[0]]]
        ordered.append(frame['id']);ordered.extend(n['id'] for n in clips)
    def visit(nid):
        n=s['nodes'][nid]
        if n['kind']=='keyframe':pair(n);return
        if n['kind']=='clip':
            if nid==eid:
                first=s['nodes'].get(n.get('depends_on'))
                if first and not output_ready(pid,first):ordered.append(first['id'])
                ordered.append(nid)
            elif nid not in ordered:
                first=s['nodes'].get(n.get('depends_on'))
                if first and first['id'] not in ordered:ordered.append(first['id'])
                ordered.append(nid)
            return
        for child in store.children(s,nid):visit(child['id'])
    visit(eid)
    reference_planner.prepare(pid,eid,lambda message:report(pid,message));s=store.load(pid);needed=[];seen=set()
    def require(nid):
        node=s['nodes'][nid]
        if node.get('locked') or (node['status'] in ('saved','succeeded') and output_ready(pid,node)):return
        for rid in production.ids(s,s['nodes'][nid]):
            if rid in s['nodes'] and rid not in seen:seen.add(rid);require(rid);needed.append(rid)
    for nid in ordered:require(nid)
    failed=[];ran=0
    for position,nid in enumerate(needed+ordered,1):
        n=store.load(pid)['nodes'][nid]
        checkpoint()
        if n.get('locked') or (n['status'] in ('saved','succeeded') and output_ready(pid,n)):continue
        if nid in skipped:report(pid,'Retrying unfinished '+n['title']+'; an old skip marker was removed.')
        # Single worker: queued/running labels here are not proof of another GPU task.
        dependencies=production.ids(store.load(pid),n)+([n['depends_on']] if n.get('depends_on') else [])
        blocked=[rid for rid in dependencies if rid not in store.load(pid)['nodes'] or store.load(pid)['nodes'][rid]['status']=='failed' or not output_ready(pid,store.load(pid)['nodes'][rid])]
        if blocked:
            def block(state):state['nodes'][nid].update(status='failed',error='Required image missing: '+', '.join(blocked)+'; retry Run All after fixing it',progress=None,stage='Blocked by required image')
            store.mutate(pid,block,False);failed.append(nid);continue
        if n.get('output'):
            previous=store.contained(pid,n['output'])
            if previous.is_file():
                archive=previous.parent/'previous-takes';archive.mkdir(exist_ok=True)
                shutil.copy2(previous,archive/(str(time.time_ns())+previous.suffix))
        generate_node(pid,nid,position,len(needed+ordered));ran+=1
        if store.load(pid)['nodes'][nid]['status']=='failed':failed.append(nid)
    if failed:raise RuntimeError(str(len(failed))+' episode boxes failed; other results and previous takes were preserved')
    report(pid,'Selected work complete: '+str(ran)+' boxes generated. Review results and Save when ready.')

def execute(job):
    pid=job['project'];op=job['operation'];label=job_context(job);report(pid,'Starting '+label)
    resume_node=job.get('resume_node')
    if resume_node and resume_node in store.load(pid)['nodes']:
        generate_node(pid,resume_node)
        if not output_ready(pid,store.load(pid)['nodes'][resume_node]):raise RuntimeError('The interrupted render could not resume; retry Run All.')
    if op=='import_written':import_written(pid)
    elif op=='episode_run':run_episode(pid,job['nodes'][0],job.get('skip_nodes'))
    elif op=='run':
        for position,nid in enumerate(job['nodes'],1):generate_node(pid,nid,position,len(job['nodes']))
        failed=[nid for nid in job['nodes'] if store.load(pid)['nodes'][nid]['status']=='failed']
        if failed:raise RuntimeError(str(len(failed))+' generation boxes failed; completed results were preserved')
    elif op=='enhance':
        if not job['nodes']:
            s=store.load(pid);text=engines.enhance(s['story_working'],'story',job['instruction'])
            store.mutate(pid,lambda state:state.update(story_working=text))
        else:
            for nid in job['nodes']:
                checkpoint()
                s=store.load(pid);n=s['nodes'][nid];field='prompt' if n['kind'] in ('keyframe','clip','reference') else 'text'
                text=engines.enhance(n[field],n['kind'],job['instruction']);store.edit(pid,nid,{field:text});report(pid,'Enhanced '+n['title'])
    elif op=='rebreakdown':breakdown_job(pid,job['nodes'][0],False,True)
    elif op=='breakdown':
        if job['nodes']:breakdown_job(pid,job['nodes'][0],False)
        else:plan_story(pid)
    elif op=='assets':asset_inventory(pid,job['nodes'][0] if job['nodes'] else None)
    elif op=='character_sheet':
        from . import character_forge
        aid=job['nodes'][0]
        character_forge.run(pid,aid,job.get('instruction',''),lambda message,percent:report(pid,message,aid,percent,task=label),checkpoint)
    report(pid,'Finished '+label)

def worker():
    while not STOP.is_set():
        job=None
        with GUARD:
            q=queue_state()
            for j in q:
                if j['state']=='queued' and j.get('control')!='pause':j.update(state='running',started=time.time());job=dict(j);store.atomic(QUEUE,q);break
        if not job:STOP.wait(.5);continue
        error=None;stopped=False;CURRENT.job=job['id']
        try:execute(job);checkpoint()
        except WorkStopped:
            stopped=True;reset_queued(job['project']);report(job['project'],'Stopped. Completed outputs were kept; unfinished items can be run again.')
        except Exception as e:error=str(e);report(job['project'],'Failed '+job_context(job)+' — '+error)
        CURRENT.job=None
        def settle(state):
            state.get('activity',{}).update(active=False)
            for n in state['nodes'].values():
                if n['status']=='running':
                    ready=output_ready(job['project'],n)
                    n.update(status=('saved' if n.get('locked') else 'succeeded') if ready else 'idle',progress=100 if ready else None,stage='Ready to review' if ready else 'Ready to retry')
        store.mutate(job['project'],settle,False)
        with GUARD:
            q=queue_state()
            for j in q:
                if j['id']==job['id']:j.update(state='stopped' if stopped else 'failed' if error else 'complete',waiting=False,active_node=None,error=error,finished=time.time())
            store.atomic(QUEUE,q)

def recover():
    """Recover every render box, including descendants of episode/scene jobs."""
    with GUARD:
        q=queue_state();projects={j['project'] for j in q}
        projects.update(p.parent.name for p in store.PROJECTS.glob('*/project.json'))
        for job in q:
            if job['state']=='running':
                if job.get('control')=='stop':job.update(state='stopped',finished=time.time())
                else:job.update(state='queued',waiting=False,recovered=True,resume_node=job.get('active_node') or job.get('resume_node'))
                job.pop('active_node',None)
            # A transient status must never become a permanent omission.
            job['skip_nodes']=[]
        for pid in projects:
            def reset(state):
                for n in state['nodes'].values():
                    if n['status'] not in ('running','queued'):continue
                    ready=output_ready(pid,n)
                    n.update(status=('saved' if n.get('locked') else 'succeeded') if ready else 'idle',error=None,progress=100 if ready else None,stage='Ready to review' if ready else 'Interrupted work ready to resume')
                state.get('activity',{}).update(active=False)
            try:store.mutate(pid,reset,False)
            except (OSError,ValueError):pass
        store.atomic(QUEUE,q)
