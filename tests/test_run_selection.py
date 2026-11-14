import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from director_studio import store,jobs,engines,production
class SelectedRunTests(unittest.TestCase):
 def setUp(self):
  inventory=patch.object(jobs,'asset_inventory',return_value=None);inventory.start();self.addCleanup(inventory.stop)
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.p=patch.object(store,'PROJECTS',self.root/'projects');self.p.start()
  qp=patch.object(jobs,'QUEUE',self.root/'queue.json');qp.start();self.addCleanup(qp.stop)
  self.s=store.create('Scoped run','Story');self.pid=self.s['id'];self.ep=store.add_node(self.s,'episode','Episode','Episode treatment');self.a=store.add_node(self.s,'scene','Scene 1','Action one',self.ep['id']);self.b=store.add_node(self.s,'scene','Scene 2','Action two',self.ep['id']);store.persist(self.s);self.calls=[]
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def generate(self,state,n,report):
  self.calls.append(n['id']);p=self.root/(n['id']+('.mp4' if n['kind']=='clip' else '.jpg'))
  if n['kind']=='clip':p.write_bytes(b'fake video')
  else:Image.new('RGB',(16,16),'red').save(p)
  return p
 def breakdown(self,state,parent,report):
  self.assertEqual(state['nodes'][parent]['kind'],'scene');self.assertEqual(parent,self.a['id'])
  return 'keyframe',[{'title':'Frame','text':'Action','prompt':'Image','video_prompt':'Move'}],'Context'
 def test_scene_run_does_not_expand_or_generate_other_scenes(self):
  with patch.object(engines,'breakdown',side_effect=self.breakdown),patch.object(engines,'generate',side_effect=self.generate):jobs.run_episode(self.pid,self.a['id'])
  s=store.load(self.pid);self.assertEqual(len(self.calls),2);self.assertEqual(store.children(s,self.b['id']),[]);self.assertFalse(any(n['kind']=='sequence' for n in s['nodes'].values()))
  self.assertEqual([n['kind'] for n in store.children(s,self.a['id'])],['keyframe','clip'])
 def test_episode_keyframe_list_imports_all_without_scenes(self):
  self.ep['text']='## Keyframe 1\nImage prompt: Dawn at cafe\nMotion: Slow push\nDialogue: Hello.\n## Keyframe 2\nImage prompt: Night on road\nMotion: Camera tracks';self.s['nodes'].pop(self.a['id']);self.s['nodes'].pop(self.b['id']);store.persist(self.s)
  with patch.object(engines,'chat') as chat,patch.object(engines,'generate',side_effect=self.generate):jobs.run_episode(self.pid,self.ep['id'])
  chat.assert_not_called();s=store.load(self.pid);self.assertEqual(len(self.calls),4);self.assertFalse(any(n['kind'] in ('scene','sequence') for n in s['nodes'].values()));self.assertEqual([n['prompt'] for n in store.children(s,self.ep['id']) if n['kind']=='keyframe'],['Dawn at cafe','Night on road'])
 def test_single_keyframe_run_does_not_generate_its_sibling(self):
  first=store.add_node(self.s,'keyframe','One',parent=self.a['id'],prompt='One');other=store.add_node(self.s,'keyframe','Two',parent=self.a['id'],prompt='Two');store.persist(self.s)
  with patch.object(engines,'generate',side_effect=self.generate):jobs.run_episode(self.pid,first['id'])
  self.assertEqual(self.calls[0],first['id']);self.assertEqual(len(self.calls),2);self.assertEqual(store.load(self.pid)['nodes'][other['id']]['status'],'idle')

 def test_stale_running_video_and_old_skip_are_retried_before_next_frame(self):
  f=store.add_node(self.s,'keyframe','Frame 1',parent=self.a['id'],prompt='One')
  v=store.add_node(self.s,'clip','Video 1',parent=self.a['id'],prompt='Move',depends_on=f['id']);v['status']='running'
  f2=store.add_node(self.s,'keyframe','Frame 2',parent=self.a['id'],prompt='Two');store.persist(self.s)
  with patch.object(engines,'generate',side_effect=self.generate):jobs.run_episode(self.pid,self.a['id'],[v['id']])
  self.assertEqual(self.calls[:3],[f['id'],v['id'],f2['id']])
  self.assertEqual(store.load(self.pid)['nodes'][v['id']]['status'],'succeeded')
 def test_failed_video_retries_without_redrawing_completed_frame(self):
  f=store.add_node(self.s,'keyframe','Frame',parent=self.a['id'],prompt='One')
  v=store.add_node(self.s,'clip','Video',parent=self.a['id'],prompt='Move',depends_on=f['id']);v['status']='failed'
  path=store.node_dir(self.s,f)/'preview.jpg';path.parent.mkdir(parents=True);Image.new('RGB',(16,16),'blue').save(path);f.update(status='succeeded',output=str(path.relative_to(store.project_dir(self.pid))));store.persist(self.s)
  with patch.object(engines,'generate',side_effect=self.generate):jobs.run_episode(self.pid,self.a['id'])
  self.assertEqual(self.calls,[v['id']])
 def test_recovery_resets_descendants_and_resumes_exact_active_node(self):
  f=store.add_node(self.s,'keyframe','Frame',parent=self.a['id'],prompt='One');v=store.add_node(self.s,'clip','Video',parent=self.a['id'],prompt='Move',depends_on=f['id']);f['status']=v['status']='running';store.persist(self.s)
  store.atomic(jobs.QUEUE,[{'id':'job','project':self.pid,'state':'running','operation':'episode_run','nodes':[self.ep['id']],'skip_nodes':[v['id']],'active_node':f['id']}])
  jobs.recover();q=jobs.queue_state()[0];s=store.load(self.pid)
  self.assertEqual(q['state'],'queued');self.assertEqual(q['skip_nodes'],[]);self.assertEqual(q['resume_node'],f['id'])
  self.assertEqual([s['nodes'][nid]['status'] for nid in (f['id'],v['id'])],['idle','idle'])
 def test_stopped_queue_is_not_resumed_on_restart(self):
  store.atomic(jobs.QUEUE,[{'id':'job','project':self.pid,'state':'running','operation':'episode_run','nodes':[self.ep['id']],'control':'stop'}])
  jobs.recover();self.assertEqual(jobs.queue_state()[0]['state'],'stopped')
 def test_pause_checkpoint_propagates_without_marking_generation_failed(self):
  f=store.add_node(self.s,'keyframe','Frame',parent=self.a['id'],prompt='One');store.persist(self.s)
  with patch.object(jobs,'checkpoint',side_effect=jobs.WorkStopped),patch.object(engines,'generate') as engine:
   with self.assertRaises(jobs.WorkStopped):jobs.generate_node(self.pid,f['id'])
  engine.assert_not_called();self.assertEqual(store.load(self.pid)['nodes'][f['id']]['status'],'idle')

 def test_storyboard_end_frames_do_not_create_unrequested_clips(self):
  start=store.add_node(self.s,'keyframe','A',parent=self.a['id'],prompt='Start',no_auto_clip=True)
  end=store.add_node(self.s,'keyframe','B',parent=self.a['id'],prompt='End',no_auto_clip=True)
  clip=store.add_node(self.s,'clip','Motion',parent=self.a['id'],prompt='Move',depends_on=start['id'])
  store.persist(self.s)
  with patch.object(engines,'generate',side_effect=self.generate):jobs.run_episode(self.pid,self.a['id'])
  s=store.load(self.pid);self.assertEqual(sum(n['kind']=='clip' for n in s['nodes'].values()),1);self.assertEqual(self.calls,[start['id'],clip['id'],end['id']])
