"""Activate the native ComfyUI backend only after the local migration tests pass."""
import json
from pathlib import Path
import requests
from director_studio import jobs,store
assert not jobs.pending(),'Wait for Director jobs to finish'
base='http://127.0.0.1:8190';q=requests.get(base+'/queue',timeout=5).json();assert not q.get('queue_running') and not q.get('queue_pending'),'Wait for ComfyUI jobs to finish'
job=json.loads(Path('logs/comfy-isabella-job.json').read_text());result=requests.get(base+'/history/'+job['prompt_id'],timeout=10).json().get(job['prompt_id'],{});assert result.get('status',{}).get('status_str')=='success','Normal Qwen comparison has not succeeded'
models=Path(r'C:\src\ai drama\tools\ComfyUI\models')
for name in ['unet/qwen-image-2512-Q4_K_M.gguf','unet/qwen-image-edit-2511-Q4_K_M.gguf','text_encoders/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf','text_encoders/Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf','vae/qwen_image_vae.safetensors','vae/minimax_h3_audio_vae_fp32.safetensors']:assert (models/name).is_file(),name
p=Path('director_studio/engines.py');t=p.read_text(encoding='utf-8');a=t.index('def _wait_gpu_idle(');b=t.index('COMFY_START_LOCK=',a);t=t[:a]+t[b:];t=t.replace("'generator':'wangp'","'generator':'comfyui'");t=t.replace("return generate_comfy(s,n,report) if settings()['generator']=='comfyui' else generate_wangp(s,n,report)","return generate_comfy(s,n,report)")
a=t.index('def service_health():');b=t.index('\nCOMFY_START_LOCK=',a)
health='''def service_health():
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
'''
t=t[:a]+health+t[b:];p.write_text(t,encoding='utf-8')
p=Path('director_studio/settings.json');d=json.loads(p.read_text());d.update(generator='comfyui',comfy_root='C:/src/ai drama/tools/ComfyUI',comfy_python='C:/src/ai drama/.wan-venv/Scripts/python.exe');store.atomic(p,d)
p=Path('director_studio/workflows/README.md');p.write_text('# Native local ComfyUI workflows\n\n`qwen.json` edits from up to three composed reference boards; character identity comes first. `qwen_text.json` is Qwen-Image 2512 prompt-only generation. `h3.json` generates H.264 MP4 with native AAC audio from a preceding keyframe.\n\nJ Director uploads inputs, validates installed nodes/models, queues `/prompt`, receives real `/ws` progress, polls the matching history, and fetches the matching output. Hosted generation nodes are rejected.\n\nOmnichar creates immutable, content-versioned `.char` snapshots from selected character references. These archives do not invent trained LoRA weights. The installed FL2VA H3 workflow uses the approved keyframe; direct `.char` multi-reference H3 conditioning requires a compatible Ref2VA workflow/model and is not claimed by this I2V graph.\n\nThe old WanGP adapter is removed. Shared H3 weights, project assets and completed output files stay in their original locations. Qwen uses ComfyUI-compatible Q4_K_M GGUF models; quality must be checked against references, not inferred from the job status.\n',encoding='utf-8')
p=Path('DIRECTOR_STUDIO.md');t=p.read_text(encoding='utf-8');a=t.index('The initial settings deliberately reuse');b=t.index('Manifest contract:',a);t=t[:a]+'''J Director now uses native local ComfyUI workflows for Qwen-Image 2512 text-to-image, Qwen-Image-Edit 2511 reference edits, and MiniMax H3 image-to-video with audio. The WanGP application adapter is removed. Existing shared H3 weights and completed outputs are preserved; engine-specific Qwen quanto files were retired with the user's approval.

Workflow manifests are supplied as `qwen.json`, `qwen_text.json` and `h3.json`. `settings.json` points to the existing ComfyUI installation. Generation starts ComfyUI locally when it is offline. Model presence is validated before submission. Omnichar exports selected character references to versioned `.char` files; this does not mean a character LoRA has been trained.

'''+t[b:];t=t.replace('Actual node identifiers must come from the tested workflow; no pretend Qwen/H3 graphs are shipped.','Node identifiers come from the supplied native graphs and are checked against the running ComfyUI schema.');t=t.replace('H3 and the configurable ComfyUI adapter are implemented but have not received a new end-to-end video render in this build.','Native ComfyUI H3 produced a verified five-frame H.264/AAC compatibility MP4 during migration. This small test verifies the pipeline, not full-scene quality. A separate normal-setting Qwen reference edit is used for visual comparison.');p.write_text(t,encoding='utf-8')
print('ComfyUI configured; keep generation maintenance enabled until final startup checks pass')
