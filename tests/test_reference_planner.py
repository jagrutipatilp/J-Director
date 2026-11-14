import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from director_studio import store,story_assets,reference_planner,production,jobs,engines
class ReferencePlannerTests(unittest.TestCase):
 def setUp(self):
  from director_studio import stock_backgrounds,library
  for obj,name in [(stock_backgrounds,'prepare'),(library,'reuse_character')]:
   mock=patch.object(obj,name,return_value=False);mock.start();self.addCleanup(mock.stop)
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.p=patch.object(store,'PROJECTS',self.root/'projects');self.q=patch.object(jobs,'QUEUE',self.root/'queue.json');self.p.start();self.q.start();self.s=store.create('Automatic refs','Photorealistic story',2);self.pid=self.s['id'];self.ep=store.add_node(self.s,'episode','Episode 1');self.scene=store.add_node(self.s,'scene','Scene 1',parent=self.ep['id']);self.frame=store.add_node(self.s,'keyframe','High shot',parent=self.scene['id'],prompt='Overhead view of Mara at the cafe');store.add_node(self.s,'clip','Motion',parent=self.scene['id'],depends_on=self.frame['id'],prompt='Natural motion');self.other=store.add_node(self.s,'episode','Episode 2')
  self.char=store.add_node(self.s,'character','Mara','Adult, black hair');self.bg=store.add_node(self.s,'location','Cafe','Warm wood interior',view_policy='multi');self.charref=store.add_node(self.s,'reference','Mara master',parent=self.char['id'],prompt=self.char['text'],category='Outfits');self.bgref=store.add_node(self.s,'reference','Cafe master',parent=self.bg['id'],prompt=self.bg['text'],category='Angles');self.scene['asset_links']={'characters':[self.char['id']],'backgrounds':[self.bg['id']]};store.persist(self.s);self.calls=[]
 def tearDown(self):self.q.stop();self.p.stop();self.tmp.cleanup()
 def chat(self,system,payload,schema):
  data=json.loads(payload)
  if 'reference_plans' in schema['properties']:return {'reference_plans':[{'asset':r['asset'],'reference':r['reference'],'prompt':'Photorealistic master '+r['name']} for r in data['assets']]}
  return {'background_choices':[{'keyframe':r['keyframe'],'background':r['background'],'reference':next(v['reference'] for v in r['available_views'] if v['view']=='High angle view'),'reason':'The shot is overhead.'} for r in data['shots']]}
 def generate(self,state,n,report):
  self.calls.append((n['id'],n['kind']));path=self.root/(n['id']+('.mp4' if n['kind']=='clip' else '.jpg'))
  if n['kind']=='clip':path.write_bytes(b'fake video')
  else:Image.new('RGB',(32,32),'red').save(path)
  return path
 def test_missing_references_are_generated_before_keyframe_and_clip(self):
  with patch.object(jobs,'asset_inventory'),patch.object(engines,'chat',side_effect=self.chat),patch.object(engines,'generate',side_effect=self.generate):jobs.run_episode(self.pid,self.ep['id'])
  s=store.load(self.pid);kinds=[kind for _,kind in self.calls];self.assertEqual(kinds,['reference','reference','reference','keyframe','clip']);self.assertEqual(store.children(s,self.other['id']),[])
  choice=s['nodes'][self.frame['id']]['background_view_selection'][self.bg['id']];self.assertEqual(s['nodes'][choice['reference']]['view_kind'],'high');self.assertIn(choice['reference'],production.ids(s,s['nodes'][self.frame['id']]))
 def test_multiple_angle_entries_share_one_master(self):
  with patch.object(engines,'chat',side_effect=self.chat):reference_planner.prepare(self.pid,self.ep['id'],lambda *a:None)
  s=store.load(self.pid);views=s['nodes'][self.bg['id']]['background_views'];self.assertEqual(len(views),7)
  for kind,rid in views.items():
   if kind!='master':self.assertEqual(s['nodes'][rid]['references'],[views['master']])
 def test_unchanged_view_decisions_and_prompts_are_reused(self):
  with patch.object(engines,'chat',side_effect=self.chat):reference_planner.prepare(self.pid,self.ep['id'],lambda *a:None)
  with patch.object(engines,'chat') as chat:reference_planner.prepare(self.pid,self.ep['id'],lambda *a:None);chat.assert_not_called()
 def test_user_images_and_explicit_background_view_are_preserved(self):
  for ref in (self.charref,self.bgref):
   path=store.project_dir(self.pid)/(ref['id']+'.jpg');Image.new('RGB',(16,16),'blue').save(path);ref.update(output=path.name,status='saved',reference_source='system')
  self.scene['production']={'background':self.bgref['id']};store.persist(self.s)
  with patch.object(engines,'chat') as chat:reference_planner.prepare(self.pid,self.ep['id'],lambda *a:None);chat.assert_not_called()
  state=store.load(self.pid);choice=state['nodes'][self.frame['id']]['background_view_selection'][self.bg['id']];self.assertEqual(choice['reference'],self.bgref['id']);self.assertEqual(choice['source'],'user')
 def test_invalid_llm_view_id_uses_a_valid_location_reference_without_generating(self):
  def bad(system,payload,schema):
   result=self.chat(system,payload,schema)
   if 'background_choices' in result:result['background_choices'][0]['reference']=self.charref['id']
   return result
  with patch.object(engines,'chat',side_effect=bad),patch.object(engines,'generate') as generate:
   reference_planner.prepare(self.pid,self.ep['id'],lambda *a:None)
   state=store.load(self.pid);choice=state['nodes'][self.frame['id']]['background_view_selection'][self.bg['id']]
   self.assertEqual(state['nodes'][choice['reference']]['parent'],self.bg['id']);self.assertEqual(choice['source'],'validated_fallback')
   generate.assert_not_called()
 def test_run_all_api_accepts_missing_user_references(self):
  from fastapi.testclient import TestClient
  from director_studio.app import app
  client=TestClient(app)
  try:
   with patch.object(jobs,'enqueue',return_value={'id':'queued'}) as enqueue:
    r=client.post('/api/projects/'+self.pid+'/action',json={'action':'runAll','node':self.scene['id'],'episode':self.ep['id']});self.assertEqual(r.status_code,200);enqueue.assert_called_once()
  finally:client.close()

 def test_character_selected_without_identity_image_uses_generated_master(self):
  self.scene['production']={'cast':[{'character':self.char['id'],'identity':'','accessories':[]}]};store.persist(self.s)
  with patch.object(jobs,'asset_inventory'),patch.object(engines,'chat',side_effect=self.chat),patch.object(engines,'generate',side_effect=self.generate):jobs.run_episode(self.pid,self.ep['id'])
  state=store.load(self.pid);self.assertIn(self.charref['id'],production.ids(state,state['nodes'][self.frame['id']]))
