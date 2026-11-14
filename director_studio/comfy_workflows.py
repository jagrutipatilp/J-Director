"""Native local ComfyUI workflow construction; no hosted generation nodes."""
import copy, math

def build(spec, fields, references, kind):
    graph=copy.deepcopy(spec['graph'])
    if kind=='h3' and not references:raise ValueError('Generate the keyframe before the video')
    fields=dict(fields)
    if kind=='h3':fields['frames']=5+17*math.ceil(max(0,round(fields['seconds']*24)-5)/17)
    # Additional Qwen inputs must be attached explicitly; never leave template images.
    if kind=='qwen' and spec.get('mode')!='text':
        if not references:raise ValueError('This Qwen edit workflow requires a reference; configure qwen_text.json for prompt-only generation')
        if len(references)>3:raise ValueError('Qwen accepts at most three composed reference boards')
        for i in range(1,len(references)):
            key='reference_'+str(i+1)
            graph[key]={'class_type':'LoadImage','inputs':{'image':references[i]}}
            for encoder in spec.get('reference_encoder_nodes',[]):graph[encoder]['inputs']['image'+str(i+1)]=[key,0]
    fields.update({'reference'+str(i+1):ref for i,ref in enumerate(references)})
    for field,bindings in spec.get('bindings',{}).items():
        if field in fields:
            for nid,inputname in bindings:graph[str(nid)]['inputs'][inputname]=fields[field]
    return graph

def validate_local(graph,schema):
    for nid,node in graph.items():
        name=node['class_type']
        if name not in schema:raise ValueError('Missing ComfyUI node: '+name)
        if name.startswith('ComfyCloud') or 'Cloud' in name or name.endswith('Api'):raise ValueError('Hosted API generation is disabled: '+name)
        required=schema[name].get('input',{}).get('required',{})
        for key,definition in required.items():
            if key not in node['inputs']:raise ValueError('Missing '+name+'.'+key)
            value=node['inputs'][key]
            if isinstance(definition[0],list) and not isinstance(value,list) and value not in definition[0] and not (name=='LoadImage' and key=='image'):raise ValueError('Unavailable model/option '+name+'.'+key+': '+str(value))


def attach_model_lora(graph,spec,name,strength,key='camera_lora'):
    hook=spec.get('model_lora_hook')
    if not hook:raise ValueError('This workflow has no model adapter hook')
    nid,inputname=hook;source=graph[str(nid)]['inputs'][inputname]
    if key in graph or not isinstance(source,list):raise ValueError('Invalid adapter connection')
    graph[key]={'class_type':'LoraLoaderModelOnly','inputs':{'model':source,'lora_name':name,'strength_model':strength}}
    graph[str(nid)]['inputs'][inputname]=[key,0]
    return graph
