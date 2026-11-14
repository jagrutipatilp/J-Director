"""Reconnect to an existing local ComfyUI prompt without submitting it twice."""
from __future__ import annotations
import hashlib,json,time
from pathlib import Path
import requests
from . import store

class LostPrompt(RuntimeError):pass
class FailedPrompt(RuntimeError):pass

def signature(state,node):
    fields={k:node.get(k) for k in ('prompt','negative','dialogue','sound','seconds','seed','camera_angle','references','production','asset_links','depends_on')}
    fields['quality']=state.get('quality','final')
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()

def record(state,node,work,prompt_id,client_id,kind,output_node):
    record={'prompt_id':prompt_id,'client_id':client_id,'work':str(work.relative_to(store.project_dir(state['id']))),'kind':kind,'output_node':output_node,'signature':signature(state,node)}
    store.atomic(work/'comfy-job.json',record)
    store.mutate(state['id'],lambda s:s['nodes'][node['id']].update(engine_job=record),False)
    return record

def wait(base,record,work,report,graph=None):
    import websocket
    prompt_id=record['prompt_id'];kind=record['kind'];ws=None;missing=0;last_connection=time.monotonic();last_heartbeat=0;progress=record.get('progress')
    try:
        try:ws=websocket.create_connection(base.replace('http','ws',1)+'/ws?clientId='+record['client_id'],timeout=2)
        except (OSError,websocket.WebSocketException):pass
        while True:
            if ws:
                try:
                    event=ws.recv()
                    if isinstance(event,str):
                        event=json.loads(event);data=event.get('data',{})
                        if data.get('prompt_id')==prompt_id:
                            if event['type']=='progress':
                                progress=round(100*data['value']/max(data['max'],1));record['progress']=progress;store.atomic(work/'comfy-job.json',record);report('ComfyUI sampling '+kind,progress)
                            elif event['type']=='executing' and data.get('node'):report('ComfyUI '+kind+': '+(graph or {}).get(str(data['node']),{}).get('class_type',str(data['node'])))
                            elif event['type']=='execution_error':raise FailedPrompt(str(data.get('exception_message','ComfyUI execution failed')))
                except websocket.WebSocketTimeoutException:pass
                except (OSError,websocket.WebSocketConnectionClosedException):ws.close();ws=None
            try:
                response=requests.get(base+'/history/'+prompt_id,timeout=10);response.raise_for_status();result=response.json().get(prompt_id);last_connection=time.monotonic()
                if not result:
                    response=requests.get(base+'/queue',timeout=10);response.raise_for_status();queue=response.json()
                    running=any(item[1]==prompt_id for item in queue.get('queue_running',[]));queued=any(item[1]==prompt_id for item in queue.get('queue_pending',[]));active=running or queued
                    if active and time.monotonic()-last_heartbeat>=30:
                        report(('ComfyUI rendering '+kind+'; still processing the current step') if running else 'ComfyUI queue: waiting for the previous render',progress if running else 0);last_heartbeat=time.monotonic()
                    missing=0 if active else missing+1
                    if missing>=3:raise LostPrompt('The previous ComfyUI task is no longer in its queue or history.')
                    time.sleep(1);continue
                if result.get('status',{}).get('status_str')=='error':raise FailedPrompt('ComfyUI workflow failed: '+json.dumps(result.get('status'))[:1200])
                outputs=result.get('outputs',{})
                if record.get('output_node'):outputs={str(record['output_node']):outputs.get(str(record['output_node']),{})}
                for output in outputs.values():
                    for entries in output.values():
                        if not isinstance(entries,list):continue
                        for item in entries:
                            if not isinstance(item,dict) or not item.get('filename'):continue
                            ext=Path(item['filename']).suffix.lower()
                            if ext not in (('.mp4',) if kind=='h3' else ('.png','.jpg','.jpeg')):continue
                            response=requests.get(base+'/view',params={k:item[k] for k in ('filename','subfolder','type') if k in item},timeout=120);response.raise_for_status()
                            path=work/('result'+ext);path.write_bytes(response.content);return path
                if result.get('status',{}).get('completed'):raise FailedPrompt('Workflow completed without the expected image/video output')
            except requests.RequestException:
                if time.monotonic()-last_connection>300:raise RuntimeError('Local generation connection unavailable for five minutes; task '+prompt_id+' was retained for reconnection.')
                if time.monotonic()-last_heartbeat>=30:report('Waiting for the local generation connection; retaining task '+prompt_id);last_heartbeat=time.monotonic()
            time.sleep(.5)
    finally:
        if ws:ws.close()
