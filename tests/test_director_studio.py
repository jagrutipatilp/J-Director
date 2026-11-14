"""Behavior tests use temporary projects and fake engines, never user assets or GPU jobs."""
import json, tempfile, time, unittest, threading
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image
from director_studio import store,jobs,engines
from director_studio.app import app

class DirectorBehavior(unittest.TestCase):
 def setUp(self):
  inventory=patch.object(jobs,'asset_inventory',return_value=None);inventory.start();self.addCleanup(inventory.stop)
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.patch1=patch.object(store,'PROJECTS',self.root/'projects');self.patch1.start()
  self.patch2=patch.object(jobs,'QUEUE',self.root/'queue.json');self.patch2.start()
  self.client=TestClient(app);self.client.__enter__()
  self.story='Original story.\n\nKeep every line exactly. '
  response=self.client.post('/api/projects',json={'title':'Test film','story':self.story});self.assertEqual(response.status_code,200);self.s=response.json();self.pid=self.s['id'];self.api='/api/projects/'+self.pid
 def tearDown(self):
  self.client.__exit__(None,None,None);self.patch2.stop();self.patch1.stop();self.temp.cleanup()
 def wait(self):
  for _ in range(60):
   if not jobs.pending(self.pid):return
   time.sleep(.1)
  self.fail('Worker did not complete')
 def test_project_read_recovers_from_transient_windows_sharing_denial(self):
  original=Path.read_text;attempts=[];target=store.project_dir(self.pid)/'project.json'
  def read(path,*args,**kwargs):
   if path==target:
    attempts.append(1)
    if len(attempts)<3:raise PermissionError('Temporary Windows sharing violation')
   return original(path,*args,**kwargs)
  with patch.object(Path,'read_text',autospec=True,side_effect=read):
   recovered=store.load(self.pid)
  self.assertEqual(recovered['id'],self.pid);self.assertEqual(len(attempts),3)
 def make_pair(self):
  ids={}
  def fn(s):
   parent=None
   for kind in ('arc','episode','scene','sequence'):
    n=store.add_node(s,kind,kind,'context',parent);parent=n['id'];ids[kind]=parent
   image=store.add_node(s,'keyframe','Frame',parent=parent,prompt='A red teapot');clip=store.add_node(s,'clip','Motion',parent=parent,prompt='Slow push in',depends_on=image['id']);ids.update(image=image['id'],clip=clip['id'])
  store.mutate(self.pid,fn);return ids
 def test_pause_resume_and_stop_preserve_current_output(self):
  ids=self.make_pair();started=threading.Event();release=threading.Event();calls=[]
  def generate(state,n,report):
   calls.append(n['id']);started.set();release.wait(4)
   p=self.root/(n['id']+'.jpg');Image.new('RGB',(16,16),'red').save(p);return p
  with patch.object(engines,'generate',side_effect=generate):
   self.client.post(self.api+'/action',json={'action':'run','node':ids['image']})
   self.assertTrue(started.wait(3))
   self.assertEqual(self.client.post(self.api+'/action',json={'action':'pause'}).status_code,200);release.set()
   for _ in range(60):
    if any(j.get('waiting') for j in jobs.pending(self.pid)):break
    time.sleep(.05)
   self.assertTrue(any(j.get('waiting') for j in jobs.pending(self.pid)))
   self.assertEqual(store.load(self.pid)['nodes'][ids['image']]['status'],'succeeded')
   self.assertEqual(self.client.post(self.api+'/action',json={'action':'resume'}).status_code,200);self.wait()
   started.clear();release.clear()
   self.client.post(self.api+'/action',json={'action':'redo','node':ids['image']})
   jobs.enqueue(self.pid,'run',[ids['image'],ids['clip']]);self.assertTrue(started.wait(3))
   self.assertEqual(self.client.post(self.api+'/action',json={'action':'stop'}).status_code,200);release.set();self.wait()
  self.assertEqual(calls,[ids['image'],ids['image']]);state=store.load(self.pid)
  self.assertEqual(state['nodes'][ids['image']]['status'],'succeeded');self.assertEqual(state['nodes'][ids['clip']]['status'],'idle')
  self.assertEqual(jobs.queue_state()[-1]['state'],'stopped')
 def test_story_planning_creates_direct_editable_episodes_and_stops(self):
  calls=[]
  def breakdown(state,parent,report):
   calls.append(parent);self.assertIsNone(parent)
   return 'episode',[{'title':'Episode 1','text':'Opening'},{'title':'Episode 2','text':'Conclusion'}],'Summary'
  with patch.object(engines,'breakdown',side_effect=breakdown),patch.object(engines,'generate') as generate:
   self.assertEqual(self.client.post(self.api+'/action',json={'action':'breakdown'}).status_code,200);self.wait()
   state=store.load(self.pid);eps=store.children(state,None);self.assertEqual([n['kind'] for n in eps],['episode','episode'])
   generate.assert_not_called();self.assertEqual(calls,[None])
   for ep in eps:self.assertTrue((store.node_dir(state,ep)/'episode.md').is_file())
   self.assertIn('Episode 1',(store.project_dir(self.pid)/'outline/episodes.md').read_text(encoding='utf-8'))
   self.assertEqual(self.client.patch(self.api+'/nodes/'+eps[0]['id'],json={'title':'Edited title','text':'Detailed episode dialogue'}).status_code,200)
   self.client.post(self.api+'/action',json={'action':'move','node':eps[1]['id'],'direction':'up'})
   state=store.load(self.pid);self.assertEqual(store.children(state,None)[0]['id'],eps[1]['id']);self.assertEqual(state['nodes'][eps[0]['id']]['text'],'Detailed episode dialogue')
   self.assertEqual(self.client.post(self.api+'/action',json={'action':'breakdown'}).status_code,200);self.wait();self.assertEqual(calls,[None])
 def test_reorder_episodes_does_not_swap_with_shared_assets(self):
  s=store.load(self.pid);first=store.add_node(s,'episode','First');store.add_node(s,'character','Cast');last=store.add_node(s,'episode','Last');store.persist(s)
  state=store.reorder(self.pid,last['id'],-1)
  self.assertEqual([n['id'] for n in store.children(state,None) if n['kind']=='episode'],[last['id'],first['id']])
 def test_undo_handles_curly_quotes_in_story(self):
  state=store.load(self.pid);state['story_working']='The “Devil” and her sunshine';store.persist(state)
  store.mutate(self.pid,lambda s:s.update(story_working='Changed'))
  self.assertEqual(store.undo(self.pid,'undo')['story_working'],'The “Devil” and her sunshine')
 def test_browser_assets_and_project_state_are_not_cached(self):
  for url in ('/','/static/studio.js',self.api):self.assertEqual(self.client.get(url).headers.get('cache-control'),'no-store')
 def test_manual_root_episode_is_supported(self):
  r=self.client.post(self.api+'/nodes',json={'kind':'episode','title':'Manual episode','text':'My episode','parent':None})
  self.assertEqual(r.status_code,200);self.assertEqual(store.children(r.json(),None)[0]['kind'],'episode')
 def test_run_all_builds_missing_stages_for_only_selected_episode(self):
  ids=self.make_pair();s=store.load(self.pid);ep=next(n for n in s['nodes'].values() if n['kind']=='episode');scene=next(n for n in s['nodes'].values() if n['kind']=='scene')
  # Keep an episode outline, remove only this fixture's prebuilt lower stages.
  for nid in list(s['nodes']):
   if s['nodes'][nid]['kind'] in ('sequence','keyframe','clip'):del s['nodes'][nid]
  other=store.add_node(s,'episode','Other episode','Other',ep['parent']);store.persist(s);calls=[]
  def breakdown(state,parent,report):
   self.assertIn('Breaking down',store.load(self.pid)['activity']['task'])
   kind={'episode':'scene','scene':'sequence','sequence':'keyframe'}[state['nodes'][parent]['kind']]
   return kind,[{'title':'New '+kind,'text':'Details','prompt':'An image','video_prompt':'Natural motion'}],'context'
  def generate(state,n,report):
   activity=store.load(self.pid)['activity'];self.assertIn(ep['title'],activity['task']);self.assertIn('Generating',activity['task']);report('Denoising',25);self.assertEqual(store.load(self.pid)['activity']['detail'],'Denoising')
   calls.append(n['kind']);p=self.root/('render-'+n['id']+('.mp4' if n['kind']=='clip' else '.jpg'))
   if n['kind']=='clip':p.write_bytes(b'test video')
   else:Image.new('RGB',(16,16),'red').save(p)
   return p
  with patch.object(engines,'breakdown',side_effect=breakdown),patch.object(engines,'generate',side_effect=generate):
   r=self.client.post(self.api+'/action',json={'action':'runAll','episode':ep['id']});self.assertEqual(r.status_code,200);self.wait()
  state=store.load(self.pid);self.assertFalse(state['activity']['active']);self.assertEqual(calls,['keyframe','clip']);self.assertEqual(store.children(state,other['id']),[])
 def test_run_all_keeps_completed_unsaved_and_saved_takes(self):
  ids=self.make_pair();s=store.load(self.pid);ep=next(n for n in s['nodes'].values() if n['kind']=='episode')
  for key in ('image','clip'):
   n=s['nodes'][ids[key]];folder=store.node_dir(s,n);folder.mkdir(parents=True,exist_ok=True);p=folder/('preview.jpg' if key=='image' else 'preview.mp4');p.write_bytes(b'previous');n.update(output=str(p.relative_to(store.project_dir(self.pid))),status='succeeded')
  s['nodes'][ids['image']].update(status='saved',locked=True);store.persist(s);calls=[]
  def generate(state,n,report):
   calls.append(n['id']);p=self.root/'new.mp4';p.write_bytes(b'new');return p
  with patch.object(engines,'generate',side_effect=generate):
   r=self.client.post(self.api+'/action',json={'action':'runAll','episode':ep['id']});self.assertEqual(r.status_code,200);self.wait()
  self.assertEqual(calls,[]);state=store.load(self.pid);self.assertEqual(state['nodes'][ids['image']]['status'],'saved');self.assertEqual(state['nodes'][ids['clip']]['status'],'succeeded')
  takes=list(store.node_dir(state,state['nodes'][ids['clip']]).glob('previous-takes/*'));self.assertEqual(takes,[]);self.assertEqual(store.contained(self.pid,state['nodes'][ids['clip']]['output']).read_bytes(),b'previous')
 def test_raw_story_fixed_root_and_path_protection(self):
  self.assertEqual((store.project_dir(self.pid)/'story.md').read_text(),self.story)
  self.assertEqual(self.client.get(self.api+'/asset',params={'path':'../../secrets.jpg'}).status_code,400)
  self.assertEqual(self.client.post(self.api+'/action',json={'action':'breakdown','node':'missing'}).status_code,400)
 def test_saved_box_locks_redo_invalidates_dependent_and_undo_does_not_claim_missing_media(self):
  ids=self.make_pair();s=store.load(self.pid)
  for key in ('image','clip'):
   n=s['nodes'][ids[key]];folder=store.node_dir(s,n);folder.mkdir(parents=True,exist_ok=True);path=folder/('result.jpg' if key=='image' else 'result.mp4');path.write_bytes(b'asset');n.update(output=str(path.relative_to(store.project_dir(self.pid))),status='succeeded')
  unrelated=store.project_dir(self.pid)/'keep.txt';unrelated.write_text('keep');store.persist(s)
  self.assertEqual(self.client.post(self.api+'/action',json={'action':'save','node':ids['image']}).status_code,200)
  self.assertEqual(self.client.patch(self.api+'/nodes/'+ids['image'],json={'prompt':'changed'}).status_code,400)
  self.assertEqual(self.client.post(self.api+'/action',json={'action':'redo','node':ids['image']}).status_code,200)
  s=store.load(self.pid);self.assertEqual(s['nodes'][ids['image']]['status'],'redo');self.assertEqual(s['nodes'][ids['clip']]['status'],'idle');self.assertTrue(unrelated.exists())
  self.client.post(self.api+'/action',json={'action':'undo'});s=store.load(self.pid);self.assertIsNone(s['nodes'][ids['image']]['output']);self.assertFalse(s['nodes'][ids['image']]['locked'])
 def test_outline_creates_paired_frames_and_runs_image_through_worker(self):
  ids=self.make_pair()
  created={}
  def add(s):created['node']=store.add_node(s,'sequence','Second sequence','Another scene beat',ids['scene'])['id']
  store.mutate(self.pid,add)
  with patch.object(engines,'breakdown',return_value=('keyframe',[{'title':'New frame','text':'Narrative','prompt':'Tea','video_prompt':'Steam rises','seconds':4}],'summary')),patch.object(jobs,'asset_inventory'):
   self.client.post(self.api+'/action',json={'action':'breakdown','node':created['node']});self.wait()
  pair=store.children(store.load(self.pid),created['node']);self.assertEqual([n['kind'] for n in pair],['keyframe','clip']);self.assertEqual(pair[1]['depends_on'],pair[0]['id'])
  def generate(s,n,report):
   path=store.project_dir(self.pid)/'.engine/test.jpg';Image.new('RGB',(64,64),'red').save(path);report('Sampling',50);return path
  with patch.object(engines,'generate',side_effect=generate):
   r=self.client.post(self.api+'/action',json={'action':'run','node':ids['image']});self.assertEqual(r.status_code,200);self.wait()
  s=store.load(self.pid);self.assertEqual(s['nodes'][ids['image']]['status'],'succeeded');self.assertTrue(store.contained(self.pid,s['nodes'][ids['image']]['output']).exists())
 def test_external_prompt_survives_progress_then_refresh_reads_it(self):
  ids=self.make_pair();s=store.load(self.pid);n=s['nodes'][ids['image']];path=store.node_dir(s,n)/'prompt.md';path.write_text('Changed in a text editor',encoding='utf-8')
  jobs.report(self.pid,'Progress only')
  self.assertEqual(path.read_text(),'Changed in a text editor')
  s=store.refresh(self.pid);self.assertEqual(s['nodes'][ids['image']]['prompt'],'Changed in a text editor')
 def test_remote_access_requires_owner_identity(self):
  r=self.client.get('/api/projects',headers={'host':'example.ts.net'})
  self.assertEqual(r.status_code,403)
 def test_cross_site_write_rejected(self):
  self.assertEqual(self.client.post('/api/projects',json={'title':'x','story':'y'},headers={'origin':'https://unrelated.example'}).status_code,403)

if __name__=='__main__':unittest.main()
