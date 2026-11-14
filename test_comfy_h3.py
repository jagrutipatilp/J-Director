import requests,json
from pathlib import Path
base='http://127.0.0.1:8190';spec=json.loads(Path('director_studio/workflows/h3.json').read_text());g=spec['graph']
source=Path('projects/test1-8922ff/characters/isabella-carter-45404/images/36edfb8a817f/preview.jpg')
with source.open('rb') as f:r=requests.post(base+'/upload/image',files={'image':('isabella.jpg',f)},data={'overwrite':'false'},timeout=30);r.raise_for_status()
g['5']['inputs']['image']=r.json()['name'];g['6']['inputs'].update(prompt='A woman stands still and blinks once. Quiet room, no speech, no music.',width=256,height=256,length=5);g['10']['inputs']['steps']=1
g['15']['inputs']['filename_prefix']='JDirector/migration-h3-smoke'
r=requests.post(base+'/prompt',json={'prompt':g},timeout=30);print(r.status_code);print(r.text[:4000]);Path('logs/comfy-h3-smoke.json').write_text(r.text)
