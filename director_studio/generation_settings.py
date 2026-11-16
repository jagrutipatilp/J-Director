"""Lora Film Studio compatible profiles, style references and shot camera choices."""
import json,re
from pathlib import Path
from PIL import Image
from . import store,comfy_workflows
FILE=store.ROOT/'director_studio/generation-settings.json'
CAMERAS=json.loads((Path(__file__).parent/'camera_choices.json').read_text(encoding='utf-8'))
DEFAULTS={'style':'manhwa','image_format':'768x768','image_mode':'turbo','video_format':'square','video_mode':'turbo'}
SIZES=['768x768','576x1024','1024x576','1024x1024','768x1344','1344x768']
QWEN_ADAPTER='qwen/Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors'
H3_ADAPTER='minimax_h3_turbo_v4_step600_ema.safetensors'

def load():return {**DEFAULTS,**(json.loads(FILE.read_text(encoding='utf-8')) if FILE.exists() else {})}
def validate(data):
    if not isinstance(data,dict) or set(data)-set(DEFAULTS):raise ValueError('Unknown generation setting')
    choices={'style':['manhwa','realistic'],'image_format':SIZES,'image_mode':['standard','turbo'],'video_format':['square','portrait','landscape'],'video_mode':['standard','turbo']}
    for k,v in data.items():
        if v not in choices[k]:raise ValueError('Invalid '+k)
    return data

def save(data):
    data={**load(),**validate(data)};store.atomic(FILE,data);return data

def camera_validate(value):
    if not isinstance(value,dict):raise ValueError('Invalid camera selection')
    allowed={g:{r[0] for r in rows} for g,_,rows in CAMERAS}
    if any(g not in allowed or v not in allowed[g] for g,v in value.items()):raise ValueError('Choose a supported camera option')
    return dict(value)

def camera_prompt(value):
    value=camera_validate(value or {})
    words=[r[2] for g,_,rows in CAMERAS for r in rows if value.get(g)==r[0]]
    return ('Camera instructions take priority over conflicting camera wording in the scene prompt or reference. '+' '.join(words)+' Preserve character identity, outfit and requested action when changing the view.') if words else ''

def dimensions(kind,prefs):
    if kind=='qwen':return tuple(map(int,prefs['image_format'].split('x')))
    sizes={'square':((512,512),(640,640)),'portrait':((384,672),(480,832)),'landscape':((672,384),(832,480))}
    return sizes[prefs['video_format']][0 if prefs['video_mode']=='turbo' else 1]

def style_prepare(cfg,prefs,prompt,negative,paths,work):
    mode=prefs['style'];style=json.loads((Path(__file__).parent/('qwen-style.json' if mode=='manhwa' else 'qwen-realistic-style.json')).read_text(encoding='utf-8'))
    paths=list(paths);role=''
    if mode=='manhwa':
        # Keep every inherited identity/background board, reserving one slot for style.
        if len(paths)>2:
            images=[Image.open(p).convert('RGB') for p in paths[1:]]
            board=Image.new('RGB',(768*len(images),768),'#303030')
            from PIL import ImageOps
            for i,image in enumerate(images):board.paste(ImageOps.contain(image,(768,768)),(768*i,0))
            target=work/'combined-scene-references.jpg';board.save(target,quality=95);paths=[paths[0],str(target)]
        ref=Path(cfg['existing_runtime'])/style['reference']
        if not ref.is_file():raise ValueError('Lora manhwa style reference missing: '+str(ref))
        role='Image '+str(len(paths)+1)+' is STYLE ONLY. Other images define identity, outfit and scene. Do not copy the style reference person or composition.'
        paths.append(str(ref))
    prompt=re.split(r'FIXED MANHWA STYLE|REALISTIC PHOTO STYLE',prompt,maxsplit=1)[0].strip()+'\n\n'+style['prompt']+'\n'+role
    return prompt,', '.join(x for x in [negative,style['negative']] if x),paths

def apply_graph(graph,spec,kind,prefs,schema):
    mode=prefs['image_mode' if kind=='qwen' else 'video_mode']
    if mode=='standard':return graph
    name=QWEN_ADAPTER if kind=='qwen' else H3_ADAPTER
    node='LoraLoaderModelOnly' if kind=='qwen' else 'MiniMaxH3TurboLoRA'
    choices=schema.get(node,{}).get('input',{}).get('required',{}).get('lora_name',[[]])[0]
    match=next((n for n in choices if n.replace(chr(92),'/')==name),None)
    if not match:raise ValueError('Turbo adapter/node missing: '+name+'. Select Standard or install the Lora adapter.')
    if kind=='qwen':
        comfy_workflows.attach_model_lora(graph,spec,match,1.0,key='lightning_lora')
        for n in graph.values():
            if n['class_type']=='KSampler':n['inputs'].update(steps=8,cfg=1.0)
    else:
        graph['h3_turbo_lora']={'class_type':'MiniMaxH3TurboLoRA','inputs':{'model':['1',0],'lora_name':match,'strength':1.0,'low_vram':True}}
        graph['8']['inputs']['model']=['h3_turbo_lora',0]
        graph['10']['inputs'].update(model=['h3_turbo_lora',0],scheduler='simple',steps=6)
        graph['9']={'class_type':'MiniMaxH3TurboSampler','inputs':{}}
    return graph
