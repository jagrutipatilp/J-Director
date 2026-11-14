import requests,hashlib,time
from pathlib import Path
url='https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors'
p=Path(r'C:\src\ai drama\tools\ComfyUI\models\vae\minimax_h3_audio_vae_fp32.safetensors');part=p.with_suffix('.part')
r=requests.get(url,stream=True,timeout=(30,90));r.raise_for_status()
with part.open('wb') as f:
 for c in r.iter_content(8*1024*1024):f.write(c)
info=requests.get('https://huggingface.co/api/models/Comfy-Org/MiniMax-H3/tree/main/vae',timeout=30).json();row=next(x for x in info if x['path']=='vae/minimax_h3_audio_vae_fp32.safetensors');assert part.stat().st_size==row['size'];expected=row.get('lfs',{}).get('oid');assert not expected or hashlib.file_digest(part.open('rb'),'sha256').hexdigest()==expected
part.replace(p);print('VERIFIED '+str(p))
