import requests,time,shutil,json,hashlib
from pathlib import Path
root=Path(r'C:\src\ai drama\tools\ComfyUI\models')
files=[('unsloth/Qwen-Image-2512-GGUF', 'qwen-image-2512-Q4_K_M.gguf', 'unet/qwen-image-2512-Q4_K_M.gguf', 13299575328)]
remaining=sum(max(0,size-((root/local).stat().st_size if (root/local).exists() else (root/local).with_suffix((root/local).suffix+'.part').stat().st_size if (root/local).with_suffix((root/local).suffix+'.part').exists() else 0)) for _,_,local,size in files)
if shutil.disk_usage(root).free < remaining+900_000_000:raise RuntimeError('Not enough disk space with 900 MB reserve')
for repo,name,local,size in files:
 dest=root/local;dest.parent.mkdir(parents=True,exist_ok=True);part=dest.with_suffix(dest.suffix+'.part')
 if dest.exists() and dest.stat().st_size==size:continue
 for attempt in range(8):
  try:
   offset=part.stat().st_size if part.exists() else 0
   url=f'https://huggingface.co/{repo}/resolve/main/{name}?download=true'
   r=requests.get(url,headers={'Range':f'bytes={offset}-'} if offset else {},stream=True,timeout=(30,90));r.raise_for_status()
   if r.status_code!=206:offset=0
   print(f'DOWNLOAD {name} from {offset}',flush=True);last=time.monotonic()
   with part.open('ab' if offset else 'wb') as f:
    for chunk in r.iter_content(8*1024*1024):
     if shutil.disk_usage(root).free<500_000_000:raise RuntimeError('Disk reserve reached; download retained for resume')
     f.write(chunk);offset+=len(chunk)
     if time.monotonic()-last>30:print(f'{name}: {offset}/{size} ({offset*100/size:.1f}%)',flush=True);last=time.monotonic()
   if part.stat().st_size!=size:raise RuntimeError('File length mismatch')
   # Verify the downloaded bytes against the repository LFS digest.
   meta=requests.get(f'https://huggingface.co/api/models/{repo}/tree/main',params={'recursive':'true','limit':1000},timeout=30).json()
   row=next(x for x in meta if x['path']==name);expected=row.get('lfs',{}).get('oid')
   if expected:
    digest=hashlib.file_digest(part.open('rb'),'sha256').hexdigest()
    if digest!=expected:raise RuntimeError('SHA256 mismatch')
   part.replace(dest);print('VERIFIED '+str(dest),flush=True);break
  except (requests.RequestException,OSError) as e:
   print('Retry: '+str(e),flush=True);time.sleep(3)
 else:raise RuntimeError('Download retries exhausted')
print('QWEN DOWNLOADS COMPLETE',flush=True)

