"""Local Ollama and native ComfyUI image/video workflows. No simulated generation."""
from __future__ import annotations
import copy, json, math, os, re, subprocess, time, uuid, threading, hashlib
from pathlib import Path
import requests
from . import store, continuity, production, planning_rules

SETTINGS_FILE=store.ROOT/'director_studio/settings.json'
DEFAULTS={'ollama_url':'http://127.0.0.1:11434','ollama_model':'gemma4:e4b','comfy_url':'http://127.0.0.1:8190','generator':'comfyui','existing_runtime':'C:/src/ai drama'}
def settings():
    return {**DEFAULTS,**(json.loads(SETTINGS_FILE.read_text(encoding='utf-8')) if SETTINGS_FILE.exists() else {})}

WRITER_LOCK=threading.Lock()

def ensure_writer():
    cfg=settings();url=cfg['ollama_url'].rstrip('/')
    try:
        requests.get(url+'/api/tags',timeout=2).raise_for_status();return
    except requests.RequestException:pass
    if url not in ('http://127.0.0.1:11434','http://localhost:11434'):raise RuntimeError('Local writing engine is offline. Start the configured Ollama service and retry.')
    with WRITER_LOCK:
        try:
            requests.get(url+'/api/tags',timeout=2).raise_for_status();return
        except requests.RequestException:pass
        executable=next((p for p in (store.ROOT/'tools/ollama-bootstrap/ollama.exe',store.ROOT/'tools/ollama/ollama.exe') if p.is_file()),None)
        if not executable:raise RuntimeError('Ollama is not installed in J Director/tools. Install or start Ollama, then retry breakdown.')
        env=os.environ.copy();env.update(OLLAMA_HOST='127.0.0.1:11434',OLLAMA_MODELS=str(store.ROOT/'local-models/ollama'),OLLAMA_NO_CLOUD='true',OLLAMA_KEEP_ALIVE='0s',CUDA_VISIBLE_DEVICES='-1')
        logs=store.ROOT/'logs';logs.mkdir(exist_ok=True)
        with (logs/'writer.out.log').open('a') as out,(logs/'writer.err.log').open('a') as err:
            proc=subprocess.Popen([str(executable),'serve'],cwd=executable.parent,env=env,stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(60):
            try:
                requests.get(url+'/api/tags',timeout=1).raise_for_status();return
            except requests.RequestException:pass
            if proc.poll() is not None:break
            time.sleep(.25)
        raise RuntimeError('The local writing engine could not start. Check logs/writer.err.log, then retry breakdown.')

def chat(system, text, structured=False):
    ensure_writer()
    cfg=settings();payload={'model':cfg['ollama_model'],'messages':[{'role':'system','content':system},{'role':'user','content':text}], 'stream':False,'think':False,'keep_alive':0,'options':{'temperature':0.2,'num_ctx':8192,'num_predict':4000,'num_gpu':0}}
    if isinstance(structured,dict) and structured.get('properties',{}).get('items',{}).get('maxItems',0)>20:
        payload['options']['num_predict']=16000
        payload['options']['num_ctx']=16384
    if isinstance(structured,dict) and any(k in structured.get('properties',{}) for k in ('backgrounds','reference_plans','background_choices')):payload['options']['num_ctx']=16384
    if structured:payload['format']=structured if isinstance(structured,dict) else 'json'
    
    try:r=requests.post(cfg['ollama_url']+'/api/chat',json=payload,timeout=(10,900));r.raise_for_status()
    except requests.ConnectionError:raise RuntimeError('The local writing engine stopped. Retry breakdown; J Director will restart it automatically.') from None
    except requests.Timeout:raise RuntimeError('The local writing engine took too long. Your existing outline was kept; retry this step.') from None
    result=r.json().get('message',{}).get('content','').strip()
    if not result:raise RuntimeError('Ollama returned empty text')
    if structured:
        try:return json.loads(result)
        except ValueError:raise RuntimeError('Ollama returned invalid JSON; no outline changes were applied')
    return result

def compact_story(text, report):
    if len(text)<=20000:return text
    cache=store.ROOT/'local-models/story-summaries'/(hashlib.sha256(text.encode('utf-8')).hexdigest()+'.json')
    if cache.is_file():
        cached=json.loads(cache.read_text(encoding='utf-8')).get('summary')
        if isinstance(cached,str) and cached.strip():report('Reusing the unchanged story summary');return cached
    pieces=[text[i:i+14000] for i in range(0,len(text),14000)];notes=[]
    for i,part in enumerate(pieces):
        report('Reading story section '+str(i+1)+' / '+str(len(pieces)))
        notes.append(chat('Summarize this story section faithfully in under 700 words. Preserve names, character descriptions, chronology, motivations, turning points and unresolved events. Do not invent events.',part))
    combined='\n\n'.join(notes)
    if len(combined)>24000:return compact_story(combined,report)
    store.atomic(cache,{'summary':combined})
    return combined

def enhance(prompt,kind,instruction=''):
    if len(prompt)>18000:
        return '\n\n'.join(enhance(prompt[i:i+14000],kind,instruction) for i in range(0,len(prompt),14000))
    system='You are a careful film director and copy editor. Preserve all requested people, ages, actions, outfits, identities, quoted dialogue, emotional intent and setting. Correct grammar and make instructions concrete. Do not invent content. Return only the revised text.'
    if kind=='clip':system+=' Format a local MiniMax H3 shot description, then overall_soundscape and non_diegetic_music. Keep exact dialogue and identify its speaker. Include natural movement, camera and timing only when provided.'
    elif kind in ('keyframe','reference'):system+=' Format for Qwen Image: composition and medium, subjects and spatial relationships, exact quoted visible text if requested, lighting and finish. For an edit preserve everything except requested changes.'
    else:system+=' Improve story pacing without dropping plot points or changing facts.'
    return chat(system,json.dumps({'text':prompt,'requested_edit':instruction},ensure_ascii=False))

def requested_episode_count(text):
    # Prefer declared format/count over incidental numbers inside dialogue or commentary.
    declared=re.search(r'(?im)^\s*(?:\*\*)?(?:format|episode count|total episodes)\s*:\s*(\d+)(?:\s*[-–—]\s*(\d+))?\s*(?:episodes?\b|$)',text)
    if declared:
        value=int(declared[1])
        if 1<=value<=100:return value
    numbered=re.findall(r'(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?EPISODE\s+(\d+)\s*[:—–-]',text)
    if numbered:return len(numbered)
    values=[int(end) for end in re.findall(r'(?i)episodes?\s+\d+\s*[-–—]\s*(\d+)',text)]
    if values:return max(values) if max(values)<=100 else None
    values=[int(number) for number in re.findall(r'(?i)\b(\d+)\s*[- ]episodes?\b',text)]
    valid=[v for v in values if 1<=v<=100]
    return max(valid,default=None)


def explicit_scenes(text):
    # Only complete numbered scene headings or screenplay slugs; never dialogue mentioning scenes.
    pattern=r'(?im)^[ \t]*(?:\#{1,6}[ \t]+)?(?:\*\*)?(?:SCENE[ \t]+\d+[^\r\n]*|(?:INT\./EXT\.|INT\.|EXT\.)[ \t]+[^\r\n]+)[ \t]*$'
    matches=list(re.finditer(pattern,text))
    if not matches:return []
    items=[]
    for index,match in enumerate(matches):
        block=text[match.start():matches[index+1].start() if index+1<len(matches) else len(text)].strip()
        title=re.sub(r'^[ \t#*]+','',match.group().strip()).rstrip('*').strip()
        items.append({'title':title,'text':block,'prompt':'','authored':True})
    return items

def explicit_episodes(text):
    pattern=r'(?im)^[ \t]*(?:\#{1,6}[ \t]+)?(?:\*\*)?EPISODE[ \t]+\d+[ \t]*[:—–-][^\r\n]+$'
    matches=list(re.finditer(pattern,text));items=[]
    for index,match in enumerate(matches):
        body=text[match.start():matches[index+1].start() if index+1<len(matches) else len(text)].strip()
        title=re.sub(r'^[ \t#*]+','',match.group().strip()).rstrip('*').strip()
        items.append({'title':title,'text':body,'prompt':'','authored':True})
    return items

def explicit_keyframes(text):
    pattern=r'(?im)^[ \t]*(?:\#{1,6}[ \t]+)?(?:\d+[.)][ \t]+)?(?:\*\*)?(?:KEY[ -]?FRAME|IMAGE(?:[ \t]+PROMPT)?)[ \t#:-]*\d+[^\r\n]*$'
    matches=list(re.finditer(pattern,text));items=[]
    for index,match in enumerate(matches):
        body=text[match.end():matches[index+1].start() if index+1<len(matches) else len(text)].strip()
        title=re.sub(r'^[ \t#*]+','',match.group().strip()).rstrip('*').strip()
        fields={};current=None
        for line in body.splitlines():
            field=re.match(r'^\s*(?:\*\*)?(keyframe prompt|image prompt|visual prompt|prompt|video prompt|motion|dialogue|sound|duration|seconds)(?:\s*\([^\r\n)]+\))?(?:\*\*)?\s*:\s*(.*)',line,re.I)
            if field:current=field[1].lower();fields[current]=field[2]
            elif current:fields[current]+='\n'+line
        image=fields.get('keyframe prompt',fields.get('image prompt',fields.get('visual prompt',fields.get('prompt',body)))).strip()
        if not image:raise ValueError('Enter an image prompt for '+title)
        duration=re.search(r'\d+',fields.get('duration',fields.get('seconds','4')))
        items.append({'title':title,'text':body,'prompt':image,'video_prompt':fields.get('video prompt',fields.get('motion','Animate this keyframe with natural restrained motion.')).strip(),'dialogue':fields.get('dialogue','').strip(),'sound':fields.get('sound','').strip(),'seconds':max(4,min(15,int(duration[0]) if duration else 4))})
    return items

def breakdown_target(s,parent):
    if parent is None:return 'episode'
    n=s['nodes'][parent]
    if n['kind']=='episode' and explicit_scenes(n['text']):return 'scene'
    if n['kind']=='episode' and explicit_keyframes(n['text']):return 'keyframe'
    return {'arc':'episode','episode':'scene','scene':'keyframe','sequence':'keyframe'}.get(n['kind'])

def breakdown(s,parent,report):
    kind='story' if parent is None else s['nodes'][parent]['kind']
    target=breakdown_target(s,parent)
    if not target:raise ValueError('Select Story, an episode or a scene to break down')
    if kind=='story':
        episodes=explicit_episodes(s['story_working'])
        if episodes:
            expected=s.get('episode_count')
            if expected and len(episodes)!=expected:raise ValueError('The written story has '+str(len(episodes))+' episode headings, but Episode count is '+str(expected)+'. Change the count or headings; no partial plan was imported.')
            report('Importing '+str(len(episodes))+' written episodes with their existing scene/keyframe structure')
            return 'episode',episodes,s['story_working']
    if kind=='episode':
        scenes=explicit_scenes(s['nodes'][parent]['text'])
        if scenes:
            report('Found '+str(len(scenes))+' explicit scene headings; preserving each scene and its exact dialogue')
            return 'scene',scenes,s.get('story_summary','')
    if kind in ('episode','scene','sequence'):
        frames=explicit_keyframes(s['nodes'][parent]['text'])
        if frames:
            report('Importing '+str(len(frames))+' keyframes and their video prompts directly; no sequence step')
            return 'keyframe',frames,s.get('story_summary','')
    context=compact_story(s['story_working'],report) if kind=='story' else s.get('story_summary',s['story_working'][:20000])
    selected=s['story_working'] if parent is None else s['nodes'][parent]['text']
    if len(selected)>20000 and kind=='story':selected=context
    system=('You are a film director planning a single-user episodic drama. Return JSON with items: an array of objects with title, text, prompt, dialogue, sound, seconds. '
            'Break ONLY the selected '+kind+' into '+target+' entries. Preserve all plot facts, names and chronology; no new characters or events. '
            'For story planning create episodes covering the full story; for other levels use 1 to 6 entries. Do not create an arc layer. Respect any explicit episode count up to 100. Include detailed descriptions. The final entry must include the final event in the selected text; do not stop early. Episodes need clear progression; do not invent cliffhangers. '
            'Use the complete season outline and adjacent episode plans to preserve chronology, reveals and unresolved threads. Do not resolve later events early. '
            'For keyframes each entry is a still image prompt plus video_prompt, dialogue and sound for its paired 4-second clip. Each video must start from that still. '
            'The text field contains narrative context. Prompt is visual, in English. Include consistent character/outfit details. Never put visible captions in the image unless requested.')
    system+='\n'+planning_rules.RULES
    if kind=='episode':system+=' Split on changes of location, time, flashbacks and distinct dramatic beats. Never put the whole episode into one scene when it contains several distinct scenes. Preserve exact dialogue in its corresponding scene. Return only the selected episode content, not the season summary.'
    expected=(s.get('episode_count') or requested_episode_count(s['story_working'])) if kind=='story' else None
    if expected:system+=' This story specifies exactly '+str(expected)+' episodes. Return one separate entry for every episode, numbered 1 through '+str(expected)+', with concise editable outlines; do not merge episode ranges.'
    if kind=='story':system+=' These are editable episode outlines, not detailed scripts: keep each episode text to 30–60 words. Leave image prompt empty. Detailed scenes will be developed later by the user.'
    report('Planning '+(str(expected)+' episodes' if expected else target+' entries')+' from the complete story context')
    item_schema={'type':'object','properties':{key:{'type':'string'} for key in ('title','text','prompt','video_prompt','dialogue','sound')},'required':['title','text','prompt']}
    item_schema['properties']['seconds']={'type':'integer','minimum':4,'maximum':15}
    schema={'type':'object','properties':{'items':{'type':'array','minItems':expected or 1,'maxItems':expected or (20 if kind in ('story','episode') else 6),'items':item_schema}},'required':['items']}
    result=chat(system+' The top-level JSON key must be items, regardless of the outline level.',json.dumps({'story_context':context,'season_outline':[{'kind':x['kind'],'title':x['title'],'text':x['text']} for x in s['nodes'].values() if x['kind'] in ('arc','episode')],'asset_bible':[{'name':x['title'],'kind':x['kind'],'description':x['text']} for x in s['nodes'].values() if x['kind'] in ('character','location','prop') and not x.get('archived')],'production_direction':{k:{'title':v['title'],'selection':v.get('production',{})} for k,v in production.ancestors(s,s['nodes'][parent]).items()} if parent else {},'selected':selected,'target':target},ensure_ascii=False),schema)
    items=result.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=100:raise RuntimeError('Outline must contain 1 to 100 entries; previous state was kept')
    if expected and len(items)!=expected:raise RuntimeError('Expected '+str(expected)+' separate episodes; no partial episode plan was applied. Retry breakdown.')
    for item in items:
        if not isinstance(item,dict) or not item.get('title') or not isinstance(item.get('text',''),str):raise RuntimeError('Invalid outline entry; previous state was kept')
    return target,items,context

def discover_assets(context):
    result=chat(planning_rules.RULES+'\nExtract only explicitly described recurring characters and locations. Return JSON with characters and locations arrays, each entry has name and description. Preserve stated ages, physical appearance and wardrobe. Do not invent missing traits. Maximum 12 characters and 12 locations.',context,True)
    for key in ('characters','locations'):
        if not isinstance(result.get(key,[]),list):raise RuntimeError('Invalid reference inventory')
        for row in result.get(key,[]):
            if not isinstance(row,dict) or not isinstance(row.get('name'),str) or not isinstance(row.get('description'),str):raise RuntimeError('Invalid reference description')
    return result

def service_health():
    from . import comfy_workflows
    cfg=settings();status={'auto_references':True,'written_import':True,'story_assets':True,'ollama':False,'comfyui':False,'models':[],'generator':'comfyui','qwen':False,'qwen_edit':False,'qwen_text':False,'h3':False,'omnichar':False}
    try:
        r=requests.get(cfg['ollama_url']+'/api/tags',timeout=2);r.raise_for_status();status['models']=[m['name'] for m in r.json().get('models',[])];status['ollama']=cfg['ollama_model'] in status['models']
    except requests.RequestException:pass
    try:
        r=requests.get(cfg['comfy_url']+'/object_info',timeout=5);r.raise_for_status();schema=r.json();status['comfyui']=True;status['omnichar']='OmnicharLoadCharacter' in schema
        for key,filename in [('qwen_edit','qwen'),('qwen_text','qwen_text'),('h3','h3')]:
            try:
                spec=json.loads((store.ROOT/'director_studio/workflows'/(filename+'.json')).read_text(encoding='utf-8'));comfy_workflows.validate_local(spec['graph'],schema);status[key]=True
            except (OSError,ValueError,KeyError):pass
        status['qwen']=status['qwen_edit'] and status['qwen_text']
    except (requests.RequestException,ValueError):pass
    flag=store.ROOT/'director_studio/generation-maintenance.json'
    status['generation_maintenance']=flag.is_file() and json.loads(flag.read_text(encoding='utf-8')).get('active',False)
    return status

COMFY_START_LOCK=threading.Lock()

def ensure_comfy(cfg,report):
    url=cfg['comfy_url'].rstrip('/')
    try:
        r=requests.get(url+'/system_stats',timeout=2);r.raise_for_status();return
    except requests.RequestException:pass
    if url not in ('http://127.0.0.1:8190','http://localhost:8190'):raise RuntimeError('Start the configured ComfyUI service and retry')
    with COMFY_START_LOCK:
        try:
            r=requests.get(url+'/system_stats',timeout=2);r.raise_for_status();return
        except requests.RequestException:pass
        root=Path(cfg.get('comfy_root',str(Path(cfg['existing_runtime'])/'tools/ComfyUI')))
        runtime=Path(cfg.get('comfy_python',str(Path(cfg['existing_runtime'])/'.wan-venv/Scripts/python.exe')))
        if not (root/'main.py').is_file() or not runtime.is_file():raise RuntimeError('The local ComfyUI installation is missing')
        logs=store.ROOT/'logs';logs.mkdir(exist_ok=True);report('Starting ComfyUI locally')
        args=[str(runtime),'main.py','--listen','127.0.0.1','--port','8190','--lowvram','--cache-none','--reserve-vram','0.6','--disable-pinned-memory','--disable-auto-launch']
        with (logs/'comfyui.out.log').open('a') as out,(logs/'comfyui.err.log').open('a') as err:
            proc=subprocess.Popen(args,cwd=root,stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(240):
            try:
                r=requests.get(url+'/system_stats',timeout=1);r.raise_for_status();return
            except requests.RequestException:pass
            if proc.poll() is not None:break
            time.sleep(.5)
        raise RuntimeError('ComfyUI could not start; check logs/comfyui.err.log')

def generate_comfy(s,n,report):
    """Execute a validated native ComfyUI graph and retrieve only this job's result."""
    import websocket
    from . import comfy_workflows
    cfg=settings();kind='h3' if n['kind']=='clip' else 'qwen';base=cfg['comfy_url'].rstrip('/')
    from . import comfy_resume
    previous=n.get('engine_job')
    if previous and previous.get('signature')==comfy_resume.signature(s,n):
        work=store.contained(s['id'],previous['work'])
        saved=work/'comfy-job.json'
        if saved.is_file():
            latest=json.loads(saved.read_text(encoding='utf-8'))
            if latest.get('prompt_id')==previous['prompt_id']:previous.update(latest)
        report('Reconnecting to existing '+kind+' task; no duplicate render: '+previous['prompt_id'])
        try:return comfy_resume.wait(base,previous,work,report,json.loads((work/'workflow.json').read_text(encoding='utf-8')))
        except (comfy_resume.LostPrompt,comfy_resume.FailedPrompt) as error:
            from . import jobs
            jobs.checkpoint()
            report(str(error)+' Retrying this unfinished box.')
            store.mutate(s['id'],lambda state:state['nodes'][n['id']].pop('engine_job',None),False)
    work=store.project_dir(s['id'])/'.engine'/uuid.uuid4().hex;work.mkdir(parents=True)
    rows=[];legend=[]
    if kind=='qwen':paths,rows,legend=production.boards(s,n,work,identity_first=True)
    else:
        first=s['nodes'].get(n.get('depends_on'))
        if not first or not first.get('output'):raise RuntimeError('Generate the keyframe before this video')
        paths=[str(store.contained(s['id'],first['output']))]
    prior=continuity.previous_frame(s,n) if kind=='qwen' and n['kind']=='keyframe' and len(paths)<3 else None
    if prior:
        paths.append(prior['path']);legend.append('Reference image '+str(len(paths))+': approved prior-episode output for continuity; retain the uploaded master identity');report('Using approved previous-episode output for continuity')
    from . import generation_settings as profiles
    prefs=profiles.load()
    styled_prompt=n['prompt'];styled_negative=n.get('negative','')
    if kind=='qwen':
        styled_prompt,styled_negative,paths=profiles.style_prepare(cfg,prefs,styled_prompt,styled_negative,paths,work)
    shot_camera=n.get('camera_choices',{})
    if kind=='h3' and not shot_camera:shot_camera=s['nodes'].get(n.get('depends_on'),{}).get('camera_choices',{})
    camera_words=profiles.camera_prompt(shot_camera)
    if camera_words:styled_prompt+='\n'+camera_words
    store.atomic(work/'generation-settings.json',{'profile':prefs,'camera':shot_camera,'style_reference':kind=='qwen' and prefs['style']=='manhwa','reference_paths':list(map(str,paths))})
    variant='qwen_text' if kind=='qwen' and not paths else kind
    specpath=store.ROOT/'director_studio/workflows'/(variant+'.json')
    if not specpath.is_file():raise RuntimeError('The local '+variant+' workflow is not configured yet; no generation was submitted')
    spec=json.loads(specpath.read_text(encoding='utf-8'))
    if kind=='qwen':
        from . import omnichar_assets
        characters=omnichar_assets.export_selected(s,n,Path(cfg.get('comfy_root',str(Path(cfg['existing_runtime'])/'tools/ComfyUI')))/'models/characters')
        store.atomic(work/'omnichar-manifest.json',characters)
        for character in characters:report('Omnichar character snapshot: '+s['nodes'][character['character']]['title']+' / '+character['signature'])
    ensure_comfy(cfg,report)
    schema_response=requests.get(base+'/object_info',timeout=20);schema_response.raise_for_status();schema=schema_response.json()
    comfy_workflows.validate_local(spec['graph'],schema)
    refs=[]
    for path in paths:
        path=Path(path)
        with path.open('rb') as f:
            r=requests.post(base+'/upload/image',files={'image':(uuid.uuid4().hex+path.suffix,f)},data={'overwrite':'false'},timeout=60);r.raise_for_status();v=r.json();refs.append('/'.join(x for x in (v.get('subfolder'),v['name']) if x))
    draft=s.get('quality')=='draft';width,height=profiles.dimensions(kind,prefs)
    prompt=styled_prompt
    if n['kind'] in ('keyframe','clip') and n.get('incidental_figures'):
        prompt+='\nIncidental scene details, not separate identity references: '+'; '.join(name+': '+text for name,text in n['incidental_figures'].items())
    if kind=='h3':
        if n.get('dialogue'):prompt+='\nExact dialogue: <d>[English] '+n['dialogue']+'</d>'
        if n.get('sound'):prompt+='\noverall_soundscape: '+n['sound']
    elif legend:prompt+='\nReference guide: '+' | '.join(legend)+'\nRender one coherent scene, never a collage or labeled sheet. Build the named subjects from the identity references. Background references describe the environment only; people already visible there are not character identity references. Preserve facial identity while applying explicitly requested outfit or hairstyle edits.'
    fields={'prompt':prompt,'negative':styled_negative or ('different face, inconsistent character, duplicate person, distorted face, malformed hands, blurry face, low quality, plastic skin, over-sharpened, oversaturated, text, watermark, incorrect anatomy' if kind=='qwen' else ''),'seed':n.get('seed',8831 if kind=='h3' else 42),'seconds':int(n.get('seconds',4)),'steps':20 if kind=='h3' else (40 if width*height>=1000000 else 30),'guidance':4.0,'width':width,'height':height}
    camera=n.get('camera_angle') if kind=='qwen' else None
    if camera:
        angles={'high':'<sks> front view high-angle shot','left':'<sks> front-left quarter view eye-level shot','right':'<sks> front-right quarter view eye-level shot','low':'<sks> front view low-angle shot','close':'<sks> front view eye-level shot','reverse':'<sks> back view eye-level shot'}
        if camera not in angles or not refs:raise ValueError('Camera control requires a supported angle and reference image')
        distance='close-up' if camera=='close' else 'wide shot' if s['nodes'].get(n.get('parent'),{}).get('kind')=='location' else 'medium shot'
        fields['prompt']=angles[camera]+' '+distance+'\n'+fields['prompt']
    graph=comfy_workflows.build(spec,fields,refs,kind)
    graph=profiles.apply_graph(graph,spec,kind,prefs,schema)
    report('Lora profile: '+prefs['style']+' / '+prefs['image_mode' if kind=='qwen' else 'video_mode']+' / '+str(width)+' x '+str(height))
    if camera:
        choices=schema.get('LoraLoaderModelOnly',{}).get('input',{}).get('required',{}).get('lora_name',[[]])[0]
        lora=next((name for name in choices if Path(name).name=='qwen-image-edit-2511-multiple-angles-lora.safetensors'),None)
        if not lora:raise RuntimeError('The installed Qwen camera adapter is unavailable to ComfyUI')
        comfy_workflows.attach_model_lora(graph,spec,lora,0.9);report('Using the local Qwen camera-angle adapter: '+camera)
    comfy_workflows.validate_local(graph,schema)
    store.atomic(work/'workflow.json',graph);store.atomic(work/'reference-manifest.json',{'source_references':rows,'references':paths,'previous_episode':prior,'quality':s.get('quality','final'),'resolution':str(width)+'x'+str(height)})
    client=str(uuid.uuid4())
    response=requests.post(base+'/prompt',json={'prompt':graph,'client_id':client},timeout=30)
    if not response.ok:raise RuntimeError('ComfyUI rejected workflow: '+response.text[:1200])
    prompt_id=response.json()['prompt_id']
    record=comfy_resume.record(s,n,work,prompt_id,client,kind,spec.get('output_node'))
    report('ComfyUI queued '+kind+' locally: '+prompt_id)
    return comfy_resume.wait(base,record,work,report,graph)

def generate(s,n,report):
    return generate_comfy(s,n,report)
