"""Windows installer. Default: inspect hardware only; --install performs setup."""
import argparse, hashlib, json, os, shutil, subprocess, sys, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(*args):
    subprocess.run([str(a) for a in args],check=True)

def hardware():
    try:
        data=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader,nounits'],text=True)
        gpus=[{'name':s.rsplit(',',1)[0].strip(),'vram_mb':int(s.rsplit(',',1)[1])} for s in data.strip().splitlines()]
    except (OSError,ValueError,subprocess.CalledProcessError):gpus=[]
    try:
        ram=int(subprocess.check_output(['powershell','-NoProfile','-Command','(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory'],text=True).strip())/2**30
    except (OSError,ValueError,subprocess.CalledProcessError):ram=None
    vram=max((g['vram_mb'] for g in gpus),default=0)
    return {'gpus':gpus,'ram_gb':round(ram,1) if ram else None,'free_gb':round(shutil.disk_usage(ROOT).free/2**30,1),'profile':'low-vram' if vram<12000 else 'standard','image_resolution':[576,1024],'video_resolution':[480,832]}

def metadata(rows):
    cache={};result=[]
    for row in rows:
        repo=row['repo']
        if repo not in cache:
            with urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'?blobs=true',timeout=60) as r:cache[repo]=json.load(r)
        info=cache[repo];item=next(x for x in info['siblings'] if x['rfilename']==row['file'])
        lfs=item.get('lfs',{});digest=lfs.get('sha256') or lfs.get('oid')
        if not digest or len(digest)!=64:raise RuntimeError('No SHA256 available: '+row['file'])
        result.append(dict(row,revision=info['sha'],bytes=item.get('size') or lfs['size'],sha256=digest))
    return result

def model_target(comfy,row):
    name=Path(row['file']).name
    if row['repo']=='unsloth/Qwen2.5-VL-7B-Instruct-GGUF' and name=='mmproj-BF16.gguf':name='Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf'
    return comfy/'models'/row['folder']/name

def download(row,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    def valid(p):
        if not p.exists() or p.stat().st_size!=row['bytes']:return False
        with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()==row['sha256']
    if valid(target):print('Verified:',target.name);return
    part=target.with_suffix(target.suffix+'.part');offset=part.stat().st_size if part.exists() else 0
    if offset>row['bytes']:raise RuntimeError('Oversize partial file: '+str(part))
    if offset==row['bytes']:
        if not valid(part):raise RuntimeError('Checksum failed: '+str(part))
        part.replace(target);return
    url='https://huggingface.co/'+row['repo']+'/resolve/'+row['revision']+'/'+row['file']
    req=urllib.request.Request(url,headers={'Range':'bytes='+str(offset)+'-'} if offset else {})
    with urllib.request.urlopen(req,timeout=120) as response:
        append=bool(offset and response.status==206)
        if append and not response.headers.get('Content-Range','').startswith('bytes '+str(offset)+'-'):raise RuntimeError('Invalid resume response')
        with part.open('ab' if append else 'wb') as f:
            shutil.copyfileobj(response,f,8*1024*1024)
    if not valid(part):raise RuntimeError('Download incomplete or checksum failed; partial retained: '+str(part))
    part.replace(target)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--install',action='store_true')
    parser.add_argument('--with-video',action='store_true')
    parser.add_argument('--yes',action='store_true')
    parser.add_argument('--resolve-only',action='store_true')
    args=parser.parse_args();hw=hardware();print(json.dumps(hw,indent=2))
    if not args.install and not args.resolve_only:return
    if args.install and (sys.platform!='win32' or sys.version_info[:2]!=(3,11)):raise RuntimeError('Use Windows 11 x64 with Python 3.11.')
    rows=json.loads((ROOT/'install/models.json').read_text())
    rows=[r for r in rows if r['group']=='images' or args.with_video]
    lock=metadata(rows);total=sum(r['bytes'] for r in lock)
    print('Selected model weights: %.1f GiB. Additional runtime space: allow 25 GiB.'%(total/2**30))
    if args.resolve_only:print('All selected model sources and hashes resolved.');return
    if not hw['gpus']:raise RuntimeError('NVIDIA GPU/driver not detected. Install its driver and retry.')
    if hw['ram_gb'] and hw['ram_gb']<30:print('WARNING: under 32 GB RAM; large image/video models may fail or page heavily.')
    if not args.yes and input('Download runtimes and selected model weights? Type YES: ')!='YES':return
    runtime=ROOT/'tools';comfy=runtime/'ComfyUI';venv=ROOT/'.venv';cp=runtime/'comfy-venv';py=venv/'Scripts/python.exe';cpy=cp/'Scripts/python.exe'
    remaining=sum(r['bytes'] for r in lock if not model_target(comfy,r).exists())
    if shutil.disk_usage(ROOT).free<remaining+25*2**30:raise RuntimeError('Insufficient free storage for models plus 25 GiB runtime reserve.')
    (ROOT/'logs').mkdir(exist_ok=True);runtime.mkdir(exist_ok=True)
    (ROOT/'install/models.lock.local.json').write_text(json.dumps(lock,indent=2))
    if not py.exists():run(sys.executable,'-m','venv',venv)
    if not cpy.exists():run(sys.executable,'-m','venv',cp)
    run(py,'-m','pip','install','-r',ROOT/'requirements-director.txt','numpy')
    run(py,ROOT/'install_ffmpeg.py')
    if not comfy.exists():run('git','clone','https://github.com/Comfy-Org/ComfyUI.git',comfy)
    node=comfy/'custom_nodes/ComfyUI-GGUF'
    if not node.exists():run('git','clone','https://github.com/city96/ComfyUI-GGUF.git',node)
    run(cpy,'-m','pip','install','torch','torchvision','torchaudio','--index-url','https://download.pytorch.org/whl/cu128')
    run(cpy,'-m','pip','install','-r',comfy/'requirements.txt')
    if (node/'requirements.txt').exists():run(cpy,'-m','pip','install','-r',node/'requirements.txt')
    run(cpy,'-c',"import torch; assert torch.cuda.is_available(), 'CUDA unavailable: check NVIDIA driver/PyTorch compatibility'")
    for row in lock:
        print('Downloading/verifying:',row['file'],flush=True)
        download(row,model_target(comfy,row))
    cfgpath=ROOT/'director_studio/settings.json'
    cfg=json.loads(cfgpath.read_text()) if cfgpath.exists() else {}
    cfg.update(ollama_url='http://127.0.0.1:11434',ollama_model='qwen2.5:7b',comfy_url='http://127.0.0.1:8190',generator='comfyui',existing_runtime=str(ROOT),comfy_root=str(comfy),comfy_python=str(cpy),image_resolution=hw['image_resolution'],video_resolution=hw['video_resolution'])
    cfgpath.write_text(json.dumps(cfg,indent=2))
    # Qwen GGUF vision projector must retain the encoder prefix expected by the loader.
    projector=comfy/'models/text_encoders/mmproj-BF16.gguf'
    named=projector.with_name('Qwen2.5-VL-7B-Instruct-mmproj-BF16.gguf')
    if projector.exists() and not named.exists():projector.replace(named)
    if args.with_video:
        specpath=ROOT/'director_studio/workflows/h3.json';spec=json.loads(specpath.read_text())
        spec['graph']['1']['inputs']['unet_name']='minimax_h3_fl2va_pruned_int8_convrot.safetensors'
        spec['graph']['2']['inputs']['clip_name']='Qwen3-VL-32B-Instruct-MiniMax-H3-L0-49-Q4_K_M.gguf'
        specpath.write_text(json.dumps(spec,indent=2))
    if not shutil.which('ollama'):raise RuntimeError('Install Ollama, reopen terminal, and rerun. Completed model files are retained.')
    # System Ollama must be started once from Start Menu before pulling.
    run('ollama','pull','qwen2.5:7b')
    report={'hardware':hw,'models':[dict(r) for r in lock],'note':'Installation complete; run health check and a small render to validate GPU workflow compatibility.'}
    (ROOT/'logs/setup-report.json').write_text(json.dumps(report,indent=2))
    print('Setup completed. Open J Director.cmd. Model installation does not guarantee render quality or speed.')
if __name__=='__main__':main()
