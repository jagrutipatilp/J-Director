"""Finish the explicitly requested local background-view build and publish its images."""
from pathlib import Path
import json,time,requests,sys
ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:8790';sys.path.insert(0,str(ROOT))
def call(path,body=None):
 for attempt in range(5):
  try:
   r=requests.post(BASE+path,json=body,timeout=30) if body is not None else requests.get(BASE+path,timeout=30)
  except requests.RequestException:
   if body is not None or attempt==4:raise
   time.sleep(1);continue
  if r.status_code>=500 and body is None and attempt<4:time.sleep(1);continue
  if not r.ok:raise RuntimeError(str(r.status_code)+' '+r.text[:200])
  return r.json()
def main():
 buildpath=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'logs/background-library-build.json';build=json.loads(buildpath.read_text(encoding='utf-8'));pid=build['project'];completed=[];failures=[]
 for item in build['items']:
  while True:
   state=call('/api/projects/'+pid)['project'];n=state['nodes'][item['node']]
   if n['status'] in ('succeeded','saved'):
    result=call('/api/projects/'+pid+'/references/'+item['node']+'/publish',{})
    completed.append({'group':item['group'],'output':result['variant']['output']});break
   if n['status']=='failed':failures.append({'group':item['group'],'error':n.get('error')});break
   if n['status'] in ('idle','redo'):call('/api/projects/'+pid+'/action',{'action':'run','node':n['id']})
   report={'state':'generating','current':item['group'],'stage':n.get('stage'),'progress':n.get('progress'),'completed':completed,'failures':failures}
   (ROOT/'logs/background-library-progress.json').write_text(json.dumps(report,indent=2),encoding='utf-8');time.sleep(8)
 from director_studio.background_export import export_backgrounds
 export_backgrounds()
 result={'state':'complete' if not failures else 'partial','completed':completed,'failures':failures}
 (ROOT/'logs/background-library-progress.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)
if __name__=='__main__':main()
