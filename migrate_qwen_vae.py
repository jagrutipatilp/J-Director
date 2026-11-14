import requests,hashlib,json
from pathlib import Path
repo='Comfy-Org/Qwen-Image_ComfyUI';name='split_files/vae/qwen_image_vae.safetensors';p=Path(r'C:\src\ai drama\tools\ComfyUI\models\vae\qwen_image_vae.safetensors');part=p.with_suffix('.part')
r=requests.get(f'https://huggingface.co/{repo}/resolve/main/{name}',stream=True,timeout=(30,90));r.raise_for_status()
with part.open('wb') as f:
 for c in r.iter_content(8*1024*1024):f.write(c)
rows=requests.get(f'https://huggingface.co/api/models/{repo}/tree/main/split_files/vae',timeout=30).json();row=next(x for x in rows if x['path']==name);assert part.stat().st_size==row['size'];expected=row.get('lfs',{}).get('oid');assert not expected or hashlib.file_digest(part.open('rb'),'sha256').hexdigest()==expected;part.replace(p)
for filename in ['qwen.json','qwen_text.json']:
 f=Path('director_studio/workflows')/filename;d=json.loads(f.read_text());d['graph']['3']['inputs']['vae_name']=p.name;f.write_text(json.dumps(d,indent=2))
print('VERIFIED '+str(p))
