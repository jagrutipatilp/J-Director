"""AI Director Studio HTTP and live state API. Projects always stay in ROOT/projects."""
from __future__ import annotations
import asyncio, ipaddress, json, os, threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from . import store, engines, jobs, library, continuity, story_assets, project_management

@asynccontextmanager
async def lifespan(app):
    jobs.STOP.clear();jobs.recover();thread=threading.Thread(target=jobs.worker,daemon=True);thread.start()
    yield
    jobs.STOP.set();thread.join(timeout=2)

app=FastAPI(title='J Director',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')

def check_host(host):
    host=host.split(':')[0].lower()
    if host in ('localhost','127.0.0.1','testserver'):return True
    if host.endswith('.ts.net'):return True
    try:return ipaddress.ip_address(host) in ipaddress.ip_network('100.64.0.0/10')
    except ValueError:return False

def remote_identity_allowed(headers):
    host=headers.get('host','').split(':')[0].lower()
    if host in ('localhost','127.0.0.1','testserver'):return True
    owner_path=Path(__file__).parent/'.remote-owner.json'
    if not owner_path.exists():return False
    owner=json.loads(owner_path.read_text(encoding='utf-8')).get('login','')
    return bool(owner) and headers.get('tailscale-user-login','').casefold()==owner.casefold()

@app.middleware('http')
async def local_access(request,call_next):
    if not check_host(request.headers.get('host','')):return JSONResponse({'detail':'Use localhost or your private Tailscale address'},status_code=403)
    if not remote_identity_allowed(request.headers):return JSONResponse({'detail':'Use a device signed in to the project owner’s Tailscale account'},status_code=403)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc!=request.headers.get('host'):return JSONResponse({'detail':'Cross-site writes are disabled'},status_code=403)
    response=await call_next(request)
    if request.url.path=='/' or request.url.path.startswith('/api/projects') or request.url.path.endswith(('.js','.css')):
        response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(ValueError)
async def invalid(request,error):return JSONResponse({'detail':str(error)},status_code=400)
@app.exception_handler(KeyError)
async def missing_key(request,error):return JSONResponse({'detail':'Selected item no longer exists'},status_code=404)
@app.exception_handler(FileNotFoundError)
async def missing_file(request,error):return JSONResponse({'detail':'Project or asset does not exist'},status_code=404)

@app.get('/')
def index():return FileResponse(Path(__file__).parent/'static/index.html')
@app.post('/api/work/stop-all')
def stop_all_work():
    import requests
    cancelled=[]
    for pid in sorted({j['project'] for j in jobs.pending()}):
        try:jobs.control(pid,'stop');cancelled.append(pid)
        except ValueError:pass
    warnings=[];base=engines.settings()['comfy_url'].rstrip('/')
    for endpoint,payload in [('/queue',{'clear':True}),('/interrupt',{})]:
        try:requests.post(base+endpoint,json=payload,timeout=5).raise_for_status()
        except requests.RequestException:warnings.append('Could not reach ComfyUI '+endpoint+'; local queues are cancelled.')
    return {'cancelled_projects':cancelled,'warnings':warnings}

@app.get('/api/generation-settings')
def get_generation_settings():
    from . import generation_settings as profiles
    return {'settings':profiles.load(),'camera_groups':profiles.CAMERAS,'image_formats':profiles.SIZES}

@app.patch('/api/generation-settings')
def update_generation_settings(data:dict):
    if jobs.pending():raise ValueError('Stop or finish active work before changing generation settings')
    from . import generation_settings as profiles
    return profiles.save(data)

@app.post('/api/projects/{pid}/nodes/{nid}/camera-auto')
def auto_camera(pid:str,nid:str):
    from . import generation_settings as profiles
    s=store.load(pid);n=s['nodes'][nid]
    if n['kind'] not in ('keyframe','clip') or n['status'] in ('running','queued','succeeded','saved') or n['locked']:raise ValueError('Select an editable keyframe or video; use Redo for a completed take')
    options={g:[r[0] for r in rows] for g,_,rows in profiles.CAMERAS}
    result=engines.chat('Choose camera options for this shot. Return ONLY a JSON object with keys from the allowed groups and values from their allowed choices. Follow explicit camera wording in the prompt. Do not add people or alter actions.',json.dumps({'allowed':options,'title':n['title'],'prompt':n['prompt']},ensure_ascii=False),True)
    return store.edit(pid,nid,{'camera_choices':profiles.camera_validate(result)})

@app.get('/api/health')
def health():return engines.service_health()
@app.get('/api/library')
def shared_library():return library.load()
@app.post('/api/library')
def create_library_asset(data:dict):return library.save_asset(data)
@app.patch('/api/library/{aid}')
def edit_library_asset(aid:str,data:dict):return library.save_asset(data,aid)
@app.post('/api/library/{aid}/variants')
def create_library_variant(aid:str,data:dict):return library.save_variant(aid,data)
@app.patch('/api/library/{aid}/variants/{vid}')
def edit_library_variant(aid:str,vid:str,data:dict):return library.save_variant(aid,data,vid)
@app.post('/api/library/{aid}/variants/{vid}/archive')
def archive_library_variant(aid:str,vid:str):return library.archive_variant(aid,vid,True)
@app.post('/api/library/{aid}/variants/{vid}/restore')
def restore_library_variant(aid:str,vid:str):return library.archive_variant(aid,vid,False)
@app.post('/api/library/{aid}/variants/{vid}/image')
async def upload_library_image(aid:str,vid:str,file:UploadFile=File(...)):
    raw=await file.read(30*1024*1024+1)
    return library.save_image(aid,vid,raw)
@app.get('/api/library/media')
def library_media(path:str):return FileResponse(library.media_path(path))
@app.post('/api/projects/{pid}/library/{aid}')
def attach_library(pid:str,aid:str,data:dict):
    if jobs.pending(pid):raise ValueError('Wait for active project work before attaching a library asset')
    return library.attach(pid,aid,data.get('variants'),data.get('target_asset'))
@app.post('/api/projects/{pid}/references/{nid}/publish')
def publish_library_reference(pid:str,nid:str):return library.publish(pid,nid)

@app.get('/api/projects')
def projects():return store.listing()
@app.post('/api/projects')
def create_project(data:dict):return store.create(str(data.get('title','')),str(data.get('story','')),data.get('episode_count'))
@app.post('/api/projects/{pid}/story-assets')
def create_story_asset(pid:str,data:dict):
    return story_assets.create(pid,data.get('kind'),str(data.get('name','')),str(data.get('description','')),data.get('scope'))

@app.post('/api/projects/{pid}/story-assets/{aid}/references')
def add_story_reference(pid:str,aid:str,data:dict):
    if jobs.pending(pid):raise ValueError('Stop active project work before changing reference images')
    result=story_assets.add_reference(pid,aid,data.get('source'),str(data.get('prompt','')),data.get('catalogue_asset'),data.get('catalogue_variant'))
    if data.get('source')=='generate':result['job']=jobs.enqueue(pid,'run',[result['reference']])
    return result

@app.post('/api/projects/{pid}/backgrounds/{aid}/stock')
def download_stock_background(pid:str,aid:str,data:dict):
    if jobs.pending(pid):raise ValueError('Stop project generation before changing its background master')
    from . import stock_backgrounds
    return stock_backgrounds.fetch(pid,aid,str(data.get('query','')).strip() or None)

@app.post('/api/projects/{pid}/characters/{aid}/sheet')
def create_character_sheet(pid:str,aid:str,data:dict):
    job=jobs.enqueue(pid,'character_sheet',[aid],str(data.get('outfit',''))[:4000])
    return {'project':store.load(pid),'jobs':jobs.pending(pid),'job':job}

@app.get('/api/deleted-projects')
def deleted_projects():return project_management.deleted()
@app.delete('/api/projects/{pid}')
def delete_project(pid:str):return project_management.delete(pid)
@app.post('/api/projects/{pid}/restore')
def restore_project(pid:str):return {'project':project_management.restore(pid)}

@app.get('/api/projects/{pid}')
def project(pid:str):
    if store.is_deleted(pid):raise ValueError('This project is deleted. Restore it from Manage projects.')
    return {'project':store.load(pid),'jobs':jobs.pending(pid)}
@app.patch('/api/projects/{pid}')
def update_project(pid:str,data:dict):
    if jobs.pending(pid):raise ValueError('Wait for project work to finish before changing story or quality')
    def apply(s):
        if 'story' in data:
            if not isinstance(data['story'],str) or not data['story'].strip():raise ValueError('Enter a story')
            s['story_working']=data['story']
        if 'quality' in data:
            if data['quality'] not in ('draft','final'):raise ValueError('Choose draft or final')
            s['quality']=data['quality']
    return store.mutate(pid,apply)
@app.patch('/api/projects/{pid}/nodes/{nid}')
def update_node(pid:str,nid:str,data:dict):return store.edit(pid,nid,data)
@app.post('/api/projects/{pid}/nodes')
def add_node(pid:str,data:dict):
    kind=data.get('kind');parent=data.get('parent');category=data.get('category','Outfits')
    if kind not in ('character','location','prop','reference','arc','episode','scene','keyframe'):raise ValueError('Invalid node kind')
    if kind=='keyframe':
        state=store.load(pid)
        if state['nodes'].get(parent,{}).get('kind') not in ('episode','scene'):raise ValueError('Create keyframes under an episode or scene')
    if kind in ('arc','episode','scene','sequence'):
        state=store.load(pid);expected={'arc':None,'episode':'arc','scene':'episode','sequence':'scene'}[kind]
        if kind=='episode' and parent is None:expected=None
        if (expected is None and parent is not None) or (expected is not None and state['nodes'].get(parent,{}).get('kind')!=expected):raise ValueError('Choose a valid outline parent')
        if not str(data.get('title','')).strip():raise ValueError('Enter a title')
    return store.mutate(pid,lambda s:store.add_node(s,kind,data.get('title','Untitled'),data.get('text',''),parent,prompt=data.get('prompt',''),category=category))
@app.post('/api/projects/{pid}/action')
def action(pid:str,data:dict):
    command=data.get('action');nid=data.get('node');episode=data.get('episode');s=store.load(pid)
    if command in ('pause','resume','stop'):
        jobs.control(pid,command);return {'project':store.load(pid),'jobs':jobs.pending(pid)}
    if command in ('undo','redo_history'):return {'project':store.undo(pid,'undo' if command=='undo' else 'redo')}
    if command=='approveContinuity':
        if jobs.pending(pid):raise ValueError('Wait for active work before approving continuity')
        entry=continuity.approve(pid,episode);return {'project':store.load(pid),'approval':entry}
    if command=='refresh':return {'project':store.refresh(pid)}
    if command=='save':return {'project':store.save_box(pid,nid)}
    if command=='redo':return {'project':store.redo_box(pid,nid)}
    if command=='move':return {'project':store.reorder(pid,nid,-1 if data.get('direction')=='up' else 1)}
    if command=='saveAll':
        for n in list(s['nodes'].values()):
            if n['status']=='succeeded' and (not episode or store.episode_of(s,n['id'])==episode):store.save_box(pid,n['id'])
        return {'project':store.load(pid)}
    if command=='importWritten':
        if jobs.pending(pid):raise ValueError('Wait for active work before importing written structure')
        return {'job':jobs.enqueue(pid,'import_written')}
    if command=='rebreakdown':
        if jobs.pending(pid):raise ValueError('Wait for active project work before redoing scenes')
        if s['nodes'].get(nid,{}).get('kind')!='episode':raise ValueError('Select an episode')
        return {'job':jobs.enqueue(pid,'rebreakdown',[nid])}
    if command=='runAll':
        scope=nid or episode
        if s['nodes'].get(scope,{}).get('kind') not in ('episode','scene','sequence','keyframe','clip'):raise ValueError('Select an episode, scene or shot to run')
        if any(j['operation']=='episode_run' and any(jobs.within(s,scope,root) or jobs.within(s,root,scope) for root in j['nodes']) for j in jobs.pending(pid)):
            return {'message':'This selection is already queued or running','project':s}
        return {'job':jobs.enqueue(pid,'episode_run',[scope])}
    if command=='enhanceAllOutline':
        ids=[n['id'] for n in store.children(s,nid) if not n['locked'] and n['status'] not in ('queued','running')]
        if not ids:raise ValueError('No editable outline cards at this level')
        return {'job':jobs.enqueue(pid,'enhance',ids)}
    if command=='enhanceAll':
        ids=[n['id'] for n in s['nodes'].values() if n['kind'] in ('keyframe','clip') and not n['locked'] and n['status'] not in ('running','queued','succeeded') and (not episode or store.episode_of(s,n['id'])==episode)]
        if not ids:raise ValueError('No editable prompts in this episode')
        return {'job':jobs.enqueue(pid,'enhance',ids)}
    if command in ('run','enhance','breakdown','assets'):
        if command=='run' and not nid:raise ValueError('Select a keyframe, clip or reference')
        return {'job':jobs.enqueue(pid,command,[nid] if nid else [],str(data.get('instruction','')))}
    raise ValueError('Unknown action')

@app.post('/api/projects/{pid}/keyframes/{nid}/upload')
@app.post('/api/projects/{pid}/references/{nid}/upload')
async def upload_reference(pid:str,nid:str,file:UploadFile=File(...)):
    s=store.load(pid);n=s['nodes'][nid]
    if n['kind'] not in ('reference','keyframe') or n['status'] in ('queued','running','succeeded') or n['locked']:raise ValueError('Select an editable image box; use Redo first to replace an existing take')
    if n['kind']=='keyframe' and any(c.get('depends_on')==nid and c['status'] in ('queued','running','succeeded','saved') for c in s['nodes'].values()):raise ValueError('Use Redo on this keyframe first to reset its dependent video')
    raw=await file.read(30*1024*1024+1)
    if len(raw)>30*1024*1024:raise ValueError('Use an image smaller than 30 MB')
    import io
    try:
        image=Image.open(io.BytesIO(raw))
        if image.width*image.height>40_000_000:raise ValueError('Image exceeds 40 megapixels')
        image.load()
        from PIL import ImageOps
        image=ImageOps.exif_transpose(image).convert('RGB')
    except Exception:raise ValueError('Upload a valid image')
    dest=store.node_dir(s,n)/'preview.jpg';dest.parent.mkdir(parents=True,exist_ok=True);image.save(dest,'JPEG',quality=95)
    def apply(state):state['nodes'][nid].update(output=str(dest.relative_to(store.project_dir(pid))).replace('\\','/'),status='succeeded',progress=100);store.log(state,('Set keyframe from computer: ' if n['kind']=='keyframe' else 'Uploaded reference ')+n['title'])
    return store.mutate(pid,apply)

@app.get('/api/projects/{pid}/asset')
def asset(pid:str,path:str):
    target=store.contained(pid,path)
    if target.suffix.lower() not in ('.jpg','.jpeg','.png','.mp4','.webm'):raise ValueError('Not a media asset')
    return FileResponse(target)

@app.websocket('/ws/{pid}')
async def live(ws:WebSocket,pid:str):
    if not check_host(ws.headers.get('host','')) or not remote_identity_allowed(ws.headers):await ws.close(code=1008);return
    origin=ws.headers.get('origin')
    if origin and urlparse(origin).netloc!=ws.headers.get('host'):await ws.close(code=1008);return
    await ws.accept();revision=-1
    try:
        while True:
            if store.is_deleted(pid):
                await ws.send_json({'type':'project_deleted','project':pid});await ws.close();return
            s=store.load(pid);work=jobs.pending(pid)
            if s['revision']!=revision or work:
                await ws.send_json({'type':'state','project':s,'jobs':work});revision=s['revision']
            await asyncio.sleep(.75)
    except (WebSocketDisconnect,RuntimeError):pass

@app.post('/api/projects/{pid}/export')
def export_episode(pid:str,data:dict):
    if jobs.pending(pid):raise ValueError('Wait for generation to finish')
    s=store.load(pid);episode=data.get('episode');clips=[n for n in s['nodes'].values() if n['kind']=='clip' and store.episode_of(s,n['id'])==episode]
    if not clips or any(n['status']!='saved' or not n.get('output') for n in clips):raise ValueError('Save and lock every clip in this episode before export')
    # Reuse KupkaProd FFmpeg installation; concat normalized clips in pipeline order.
    import subprocess,shutil,datetime,re
    runtime=Path(engines.settings()['existing_runtime'])
    bundled=list((runtime/'.venv/Lib/site-packages/imageio_ffmpeg/binaries').glob('ffmpeg*.exe'))
    ffmpeg=str(bundled[0]) if bundled else shutil.which('ffmpeg') or str(store.ROOT/'tools/ffmpeg/ffmpeg.exe')
    if not Path(ffmpeg).is_file() and not shutil.which(ffmpeg):raise ValueError('FFmpeg is not installed')
    order=[]
    def visit(parent):
        for node in store.children(s,parent):
            if node['kind']=='clip':order.append(node['id'])
            else:visit(node['id'])
    visit(episode);rank={nid:i for i,nid in enumerate(order)};clips.sort(key=lambda n:rank[n['id']])
    work=store.project_dir(pid)/'.engine'/store.uid();work.mkdir()
    probes=[]
    for n in clips:
        result=subprocess.run([ffmpeg,'-hide_banner','-i',str(store.contained(pid,n['output']))],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        probes.append(result.stderr)
    size=re.search(r'Video:[^\n]*?\b(\d{2,5})x(\d{2,5})\b',probes[0]);width,height=(int(size[1])//2*2,int(size[2])//2*2) if size else (720,1280)
    for i,n in enumerate(clips):
        command=[ffmpeg,'-y','-loglevel','error','-i',str(store.contained(pid,n['output']))]
        if 'Audio:' in probes[i]:command+=['-map','0:v:0','-map','0:a:0','-af','apad','-shortest']
        else:command+=['-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-map','0:v:0','-map','1:a:0','-shortest']
        command+=['-vf',f"scale=w='min({width},iw)':h='min({height},ih)':force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=24",'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-ac','2','-ar','48000',str(work/(str(i)+'.mp4'))]
        subprocess.run(command,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    listing=work/'concat.txt';listing.write_text(''.join("file '"+str(i)+".mp4'\n" for i in range(len(clips))))
    dest=store.project_dir(pid)/'exports'/(store.slug(s['nodes'][episode]['title'])+'-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+store.uid()[:6]+'.mp4')
    subprocess.run([ffmpeg,'-y','-loglevel','error','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(dest)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return {'path':str(dest.relative_to(store.project_dir(pid)))}
