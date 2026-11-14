import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import websocket
from director_studio import store,engines,comfy_resume

class ComfyResumeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  p=patch.object(store,'PROJECTS',self.root/'projects');p.start();self.addCleanup(p.stop)
  self.s=store.create('Resume','Story');ep=store.add_node(self.s,'episode','Episode');self.n=store.add_node(self.s,'keyframe','Frame',parent=ep['id'],prompt='A red chair');store.persist(self.s)
  self.work=store.project_dir(self.s['id'])/'.engine'/'task';self.work.mkdir(parents=True)
  store.atomic(self.work/'workflow.json',{'save':{'class_type':'SaveImage','inputs':{}}})
 def record(self):return comfy_resume.record(self.s,self.n,self.work,'exact-task','client','qwen','save')
 def test_existing_prompt_is_reattached_without_new_submission(self):
  r=self.record();self.n['engine_job']=r;result=self.work/'result.png';result.write_bytes(b'image')
  with patch.object(comfy_resume,'wait',return_value=result) as wait,patch.object(engines.requests,'post') as submit:
   self.assertEqual(engines.generate_comfy(self.s,self.n,Mock()),result)
  submit.assert_not_called();self.assertEqual(wait.call_args.args[1]['prompt_id'],'exact-task')
 def test_prompt_edit_changes_resume_signature_but_progress_does_not(self):
  old=comfy_resume.signature(self.s,self.n);self.n.update(status='running',progress=50,stage='Sampling')
  self.assertEqual(comfy_resume.signature(self.s,self.n),old)
  self.n['prompt']='A blue chair';self.assertNotEqual(comfy_resume.signature(self.s,self.n),old)
 def test_finished_task_fetches_only_its_designated_output(self):
  r=self.record();ws=Mock();ws.recv.side_effect=websocket.WebSocketTimeoutException
  history=Mock();history.json.return_value={'exact-task':{'outputs':{'other':{'images':[{'filename':'wrong.png'}]},'save':{'images':[{'filename':'right.png','type':'output'}]}},'status':{'completed':True}}}
  media=Mock(content=b'correct image')
  with patch('websocket.create_connection',return_value=ws),patch.object(comfy_resume.requests,'get',side_effect=[history,media]) as get:
   result=comfy_resume.wait('http://local',r,self.work,Mock())
  self.assertEqual(result.read_bytes(),b'correct image');self.assertEqual(get.call_args.kwargs['params']['filename'],'right.png');ws.close.assert_called()
 def test_lost_task_is_detected_without_resubmitting_from_monitor(self):
  r=self.record();ws=Mock();ws.recv.side_effect=websocket.WebSocketTimeoutException
  empty=Mock();empty.json.return_value={};queue=Mock();queue.json.return_value={'queue_running':[],'queue_pending':[]}
  with patch('websocket.create_connection',return_value=ws),patch.object(comfy_resume.requests,'get',side_effect=[empty,queue]*3),patch.object(comfy_resume.requests,'post') as submit,patch.object(comfy_resume.time,'sleep'):
   with self.assertRaises(comfy_resume.LostPrompt):comfy_resume.wait('http://local',r,self.work,Mock())
  submit.assert_not_called()

 def test_healthy_render_outliving_three_hours_is_still_monitored(self):
  import itertools
  r=self.record();ws=Mock();ws.recv.side_effect=websocket.WebSocketTimeoutException
  missing=Mock();missing.json.return_value={}
  queue=Mock();queue.json.return_value={'queue_running':[[0,'exact-task']], 'queue_pending':[]}
  done=Mock();done.json.return_value={'exact-task':{'status':{'completed':True},'outputs':{'save':{'images':[{'filename':'finished.png'}]}}}}
  media=Mock(content=b'finished');report=Mock()
  with patch('websocket.create_connection',return_value=ws),patch.object(comfy_resume.requests,'get',side_effect=[missing,queue,done,media]),patch.object(comfy_resume.time,'monotonic',side_effect=itertools.chain([0],itertools.repeat(20000))),patch.object(comfy_resume.time,'sleep'):
   result=comfy_resume.wait('http://local',r,self.work,report)
  self.assertEqual(result.read_bytes(),b'finished');self.assertTrue(any('still processing' in c.args[0] for c in report.call_args_list))
 def test_queue_heartbeat_does_not_claim_gpu_is_running_that_node(self):
  from director_studio import jobs
  jobs.report(self.s['id'],'ComfyUI queue: waiting for the previous render',self.n['id'],0)
  self.assertEqual(store.load(self.s['id'])['nodes'][self.n['id']]['status'],'queued')
  jobs.report(self.s['id'],'ComfyUI rendering h3; still processing the current step',self.n['id'],15)
  n=store.load(self.s['id'])['nodes'][self.n['id']];self.assertEqual(n['status'],'running');self.assertEqual(n['progress'],15)

 def test_stop_request_prevents_interrupted_prompt_from_resubmitting(self):
  from director_studio import jobs
  self.n['engine_job']=self.record()
  with patch.object(comfy_resume,'wait',side_effect=comfy_resume.FailedPrompt('Interrupted')),patch.object(jobs,'checkpoint',side_effect=jobs.WorkStopped),patch.object(engines.requests,'post') as submit:
   with self.assertRaises(jobs.WorkStopped):engines.generate_comfy(self.s,self.n,Mock())
  submit.assert_not_called()
