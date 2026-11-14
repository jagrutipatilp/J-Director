from pathlib import Path
p=Path('director_studio/engines.py');text=p.read_text(encoding='utf-8');start=text.index('def generate_comfy(');end=text.index('\ndef generate(s,n,report):',start)
new='''def generate_comfy(s,n,report):
    """Execute a validated native ComfyUI graph and retrieve only this job's result."""
    import websocket
    from . import comfy_workflows
    cfg=settings();kind='h3' if n['kind']=='clip' else 'qwen';base=cfg['comfy_url'].rstrip('/')
    work=store.project_dir(s['id'])/'.engine'/uuid.uuid4().hex;work.mkdir(parents=True)
    rows=[];legend=[]
    if kind=='qwen':paths,rows,legend=production.boards(s,n,work)
    else:
        first=s['nodes'].get(n.get('depends_on'))
        if not first or not first.get('output'):raise RuntimeError('Generate the keyframe before this video')
        paths=[str(store.contained(s['id'],first['output']))]
    variant='qwen_text' if kind=='qwen' and not paths else kind
    specpath=store.ROOT/'director_studio/workflows'/(variant+'.json')
    if not specpath.is_file():raise RuntimeError('The local '+variant+' workflow is not configured yet; no generation was submitted')
    spec=json.loads(specpath.read_text(encoding='utf-8'))
    schema_response=requests.get(base+'/object_info',timeout=20);schema_response.raise_for_status();schema=schema_response.json()
    comfy_workflows.validate_local(spec['graph'],schema)
    refs=[]
    for path in paths:
        path=Path(path)
        with path.open('rb') as f:
            r=requests.post(base+'/upload/image',files={'image':(uuid.uuid4().hex+path.suffix,f)},data={'overwrite':'false'},timeout=60);r.raise_for_status();v=r.json();refs.append('/'.join(x for x in (v.get('subfolder'),v['name']) if x))
    draft=s.get('quality')=='draft';width,height=((480,832) if draft else (768,1344)) if kind=='h3' else ((576,1024) if draft else (832,1472))
    prompt=n['prompt']
    if kind=='h3':
        if n.get('dialogue'):prompt+='\\nExact dialogue: <d>[English] '+n['dialogue']+'</d>'
        if n.get('sound'):prompt+='\\noverall_soundscape: '+n['sound']
    elif legend:prompt+='\\nReference guide: '+' | '.join(legend)+'\\nRender one coherent scene, never a collage or labeled sheet. Uploaded identity references take priority over conflicting text descriptions.'
    fields={'prompt':prompt,'negative':n.get('negative',''),'seed':n.get('seed',42),'seconds':int(n.get('seconds',4)),'steps':(12 if draft else 20) if kind=='h3' else (12 if draft else 30),'guidance':4.0,'width':width,'height':height}
    graph=comfy_workflows.build(spec,fields,refs,kind)
    comfy_workflows.validate_local(graph,schema)
    store.atomic(work/'workflow.json',graph);store.atomic(work/'reference-manifest.json',{'source_references':rows,'references':paths,'quality':s.get('quality','final'),'resolution':str(width)+'x'+str(height)})
    client=str(uuid.uuid4());ws=websocket.create_connection(base.replace('http','ws',1)+'/ws?clientId='+client,timeout=2)
    prompt_id=None
    try:
        r=requests.post(base+'/prompt',json={'prompt':graph,'client_id':client},timeout=30)
        if not r.ok:raise RuntimeError('ComfyUI rejected workflow: '+r.text[:1200])
        prompt_id=r.json()['prompt_id'];store.atomic(work/'comfy-job.json',{'prompt_id':prompt_id,'client_id':client});start=time.monotonic();report('ComfyUI queued '+kind+' locally: '+prompt_id)
        while time.monotonic()-start<10800:
            try:
                event=ws.recv()
                if isinstance(event,str):
                    event=json.loads(event);data=event.get('data',{})
                    if data.get('prompt_id') not in (None,prompt_id):continue
                    if event['type']=='progress':report('ComfyUI sampling '+kind,round(100*data['value']/max(data['max'],1)))
                    elif event['type']=='executing' and data.get('node'):
                        node=graph.get(str(data['node']),{});report('ComfyUI '+kind+': '+node.get('class_type',str(data['node'])))
                    elif event['type']=='execution_error':raise RuntimeError(str(data.get('exception_message','ComfyUI execution failed')))
            except websocket.WebSocketTimeoutException:pass
            result=requests.get(base+'/history/'+prompt_id,timeout=10).json().get(prompt_id)
            if not result:continue
            if result.get('status',{}).get('status_str')=='error':raise RuntimeError('ComfyUI workflow failed: '+json.dumps(result.get('status'))[:1200])
            outputs=result.get('outputs',{})
            if spec.get('output_node'):outputs={str(spec['output_node']):outputs.get(str(spec['output_node']),{})}
            for output in outputs.values():
                for entries in output.values():
                    if not isinstance(entries,list):continue
                    for item in entries:
                        if not isinstance(item,dict) or not item.get('filename'):continue
                        ext=Path(item['filename']).suffix.lower()
                        if ext not in (('.mp4',) if kind=='h3' else ('.png','.jpg','.jpeg')):continue
                        r=requests.get(base+'/view',params={k:item[k] for k in ('filename','subfolder','type') if k in item},timeout=120);r.raise_for_status()
                        path=work/('result'+ext);path.write_bytes(r.content);return path
            if result.get('status',{}).get('completed'):raise RuntimeError('Workflow completed without the expected image/video output')
            time.sleep(.5)
        raise RuntimeError('ComfyUI generation timed out; job '+str(prompt_id)+' is recorded in '+str(work))
    finally:ws.close()
'''
p.write_text(text[:start]+new+text[end:],encoding='utf-8')
print('ComfyUI adapter updated; engine setting left unchanged pending model tests')
