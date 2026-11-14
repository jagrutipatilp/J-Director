import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from director_studio import store,library,jobs,engines,project_management
class ProjectManagementTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.patches=[patch.object(store,'PROJECTS',self.root/'projects'),patch.object(library,'ROOT',self.root/'catalogue'),patch.object(jobs,'QUEUE',self.root/'queue.json')]
  for p in self.patches:p.start()
  self.s=store.create('Two episode test','A small story.',2);self.pid=self.s['id'];self.char=store.add_node(self.s,'character','Mara','Black hair, exact identity.');self.bg=store.add_node(self.s,'location','Cafe','Warm windows.')
  self.ref=store.add_node(self.s,'reference','Mara portrait',parent=self.char['id'],prompt='Portrait',category='Outfits',status='saved',locked=True)
  file=store.node_dir(self.s,self.ref)/'preview.jpg';file.parent.mkdir(parents=True);Image.new('RGB',(48,64),'red').save(file,'JPEG');self.ref['output']=str(file.relative_to(store.project_dir(self.pid)));self.original=file.read_bytes();store.persist(self.s)
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def test_delete_exports_assets_and_images_before_hiding_project(self):
  result=project_management.delete(self.pid);self.assertEqual(result['preserved_assets'],2);self.assertNotIn(self.pid,[p['id'] for p in store.listing()]);self.assertTrue(store.project_dir(self.pid).is_dir())
  assets=library.load()['assets'];self.assertEqual({a['kind'] for a in assets},{'character','location'});char=next(a for a in assets if a['kind']=='character');image=next(v for v in char['variants'] if v['output']);self.assertEqual(library.media_path(image['output']).read_bytes(),self.original)
  self.assertTrue(project_management.deleted());self.assertEqual(char['description'],self.char['text'])
 def test_restore_and_repeat_delete_are_recoverable_and_idempotent(self):
  first=project_management.delete(self.pid);project_management.restore(self.pid);self.assertIn(self.pid,[p['id'] for p in store.listing()]);second=project_management.delete(self.pid);self.assertEqual(first['catalogue_assets'],second['catalogue_assets']);self.assertEqual(len(library.load()['assets']),2)
 def test_active_work_blocks_deletion(self):
  jobs.enqueue(self.pid,'assets')
  with self.assertRaisesRegex(ValueError,'Stop active'):project_management.delete(self.pid)
  self.assertFalse(store.is_deleted(self.pid));self.assertEqual(library.load()['assets'],[])
 def test_missing_image_aborts_deletion(self):
  store.contained(self.pid,self.ref['output']).unlink()
  with self.assertRaisesRegex(ValueError,'missing'):project_management.delete(self.pid)
  self.assertFalse(store.is_deleted(self.pid));self.assertIn(self.pid,[p['id'] for p in store.listing()])
 def test_same_name_catalogue_identity_is_not_overwritten(self):
  original=library.save_asset({'kind':'character','name':'Mara','description':'A different identity'});project_management.delete(self.pid)
  catalog=library.load();self.assertEqual(library.find(catalog,original['id'])['description'],'A different identity');self.assertEqual(len([a for a in catalog['assets'] if a['name']=='Mara']),2)
 def test_preserved_assets_can_be_used_in_new_project(self):
  result=project_management.delete(self.pid);new=store.create('New story','New outline',2);asset=library.find(library.load(),result['catalogue_assets'][0]);attached=library.attach(new['id'],asset['id']);self.assertTrue(attached['references'])
  ref=attached['project']['nodes'][attached['references'][0]];self.assertTrue(store.contained(new['id'],ref['output']).is_file())
 def test_deleted_project_cannot_be_edited_or_queued(self):
  project_management.delete(self.pid)
  with self.assertRaises(ValueError):store.edit(self.pid,self.char['id'],{'text':'Changed'})
  with self.assertRaises(ValueError):jobs.enqueue(self.pid,'assets')
 def test_two_episode_setting_overrides_inference(self):
  self.assertEqual(self.s['episode_count'],2)
  result={'items':[{'title':'Episode '+str(i),'text':'Beat','prompt':''} for i in (1,2)]}
  with patch.object(engines,'chat',return_value=result) as chat:engines.breakdown(self.s,None,lambda *a:None)
  schema=chat.call_args.args[2];self.assertEqual(schema['properties']['items']['minItems'],2);self.assertEqual(schema['properties']['items']['maxItems'],2)
 def test_api_delete_restore_and_new_episode_count(self):
  from fastapi.testclient import TestClient
  from director_studio.app import app
  client=TestClient(app)
  try:
   self.assertEqual(client.delete('/api/projects/'+self.pid).status_code,200);self.assertEqual(client.get('/api/deleted-projects').json()[0]['id'],self.pid);self.assertEqual(client.post('/api/projects/'+self.pid+'/restore',json={}).status_code,200)
   r=client.post('/api/projects',json={'title':'Fresh','story':'Small story','episode_count':2});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['episode_count'],2)
   self.assertEqual(client.post('/api/projects',json={'title':'Bad','story':'Story','episode_count':0}).status_code,400)
  finally:client.close()
