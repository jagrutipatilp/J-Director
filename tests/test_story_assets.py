import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from director_studio import store,story_assets,production,library,engines,jobs

class StoryAssetTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.a=patch.object(store,'PROJECTS',self.root/'projects');self.b=patch.object(library,'ROOT',self.root/'catalogue');self.a.start();self.b.start();self.s=store.create('Story','Mara works at Eve Cafe.');self.pid=self.s['id']
  self.ep=store.add_node(self.s,'episode','Episode 1','Mara visits Eve Cafe.');self.scene=store.add_node(self.s,'scene','Scene 1','Mara speaks at Eve Cafe.',self.ep['id']);self.frame=store.add_node(self.s,'keyframe','Frame 1',parent=self.scene['id'],prompt='Mara at Eve Cafe');store.persist(self.s)
 def tearDown(self):self.b.stop();self.a.stop();self.tmp.cleanup()
 def extract(self):
  result={'characters':[{'name':'Mara','description':'Black hair, tailored black suit.','used_in':[self.scene['id']]}],'backgrounds':[{'name':'Eve Cafe','description':'Warm cafe interior.','used_in':[self.scene['id']]}]}
  with patch.object(engines,'chat',return_value=result),patch.object(engines,'generate') as gen:story_assets.discover(self.pid,self.scene['id'],lambda *a:None);gen.assert_not_called()
  self.s=store.load(self.pid);return story_assets.asset_nodes(self.s)
 def test_discovery_creates_local_documents_not_catalogue_images(self):
  assets=self.extract();self.assertEqual(len(assets),2);self.assertEqual(library.load()['assets'],[])
  for asset in assets:
   folder=store.node_dir(self.s,asset);self.assertTrue((folder/'requirements.md').is_file());self.assertTrue((folder/'used-in.md').is_file());self.assertIn('ep1s1',asset['used_in']);self.assertFalse(story_assets.reference(self.s,asset['id']).get('output'))
 def test_scene_links_are_inherited_by_keyframes(self):
  assets=self.extract();ids=production.ids(self.s,self.s['nodes'][self.frame['id']]);self.assertEqual(len(ids),2)
  self.assertEqual({self.s['nodes'][rid]['parent'] for rid in ids},{a['id'] for a in assets})
 def test_manual_empty_selection_is_not_overridden(self):
  self.extract();state=store.edit(self.pid,self.frame['id'],{'asset_links':{'characters':[],'backgrounds':[]}});self.assertEqual(production.ids(state,state['nodes'][self.frame['id']]),[])
 def test_manual_description_survives_refinement_and_no_duplicate_assets(self):
  assets=self.extract();char=next(a for a in assets if a['kind']=='character');store.edit(self.pid,char['id'],{'text':'Keep this exact identity.'})
  s=store.load(self.pid);result={'characters':[{'name':'Mara','description':'New requirement, not a replacement identity.','used_in':[self.scene['id']]}],'backgrounds':[]};story_assets.upsert(s,result,{self.scene['id']:s['nodes'][self.scene['id']]['text']});store.persist(s)
  self.assertEqual(s['nodes'][char['id']]['text'],'Keep this exact identity.');self.assertEqual(len([a for a in story_assets.asset_nodes(s) if a['kind']=='character']),1)
 def test_catalogue_choice_copies_without_modifying_catalogue(self):
  char=next(a for a in self.extract() if a['kind']=='character');cat=library.save_asset({'kind':'character','name':'Reusable face','description':'Face'});v=library.save_variant(cat['id'],{'title':'Portrait','category':'Outfits','prompt':'Portrait'})
  import io
  raw=io.BytesIO();Image.new('RGB',(32,32),'red').save(raw,'JPEG');library.save_image(cat['id'],v['id'],raw.getvalue());before=library.load()
  result=story_assets.add_reference(self.pid,char['id'],'catalogue',catalogue_asset=cat['id'],catalogue_variant=v['id']);ref=result['project']['nodes'][result['reference']]
  self.assertTrue(store.contained(self.pid,ref['output']).is_file());self.assertEqual(ref['status'],'saved');self.assertEqual(library.load(),before);self.assertEqual(story_assets.reference(result['project'],char['id'])['id'],ref['id'])
 def test_system_choice_creates_project_placeholder_not_shared_asset(self):
  char=next(a for a in self.extract() if a['kind']=='character');r=story_assets.add_reference(self.pid,char['id'],'system');self.assertEqual(r['project']['nodes'][r['reference']]['kind'],'reference');self.assertEqual(library.load()['assets'],[])
 def test_used_in_video_code_is_specific(self):
  clip=store.add_node(self.s,'clip','Video',parent=self.scene['id'],depends_on=self.frame['id']);self.assertEqual(story_assets.code(self.s,clip['id']),'ep1s1k1kv1')
 def test_editing_scene_refines_requirements_without_generating_images(self):
  assets=self.extract();char=next(a for a in assets if a['kind']=='character');s=store.edit(self.pid,self.scene['id'],{'text':'Mara is tired at Eve Cafe.'});self.assertIn('tired',s['nodes'][char['id']]['requirements'][self.scene['id']]['text'])
 def test_unchanged_source_is_not_rediscovered(self):
  self.extract()
  with patch.object(engines,'chat') as chat:story_assets.discover(self.pid,self.scene['id'],lambda *a:None);chat.assert_not_called()

 def test_three_source_api_can_upload_a_system_image_locally(self):
  from fastapi.testclient import TestClient
  from director_studio.app import app
  import io
  client=TestClient(app)
  try:
   r=client.post('/api/projects/'+self.pid+'/story-assets',json={'kind':'character','name':'Eve','description':'Blonde young adult'});self.assertEqual(r.status_code,200);aid=r.json()['asset']
   r=client.post('/api/projects/'+self.pid+'/story-assets/'+aid+'/references',json={'source':'system'});self.assertEqual(r.status_code,200);rid=r.json()['reference']
   image=io.BytesIO();Image.new('RGB',(20,20),'blue').save(image,'PNG')
   r=client.post('/api/projects/'+self.pid+'/references/'+rid+'/upload',files={'file':('photo.png',image.getvalue(),'image/png')});self.assertEqual(r.status_code,200);self.assertTrue(store.contained(self.pid,r.json()['nodes'][rid]['output']).is_file())
  finally:client.close()
 def test_generate_source_queues_only_the_requested_reference(self):
  from fastapi.testclient import TestClient
  from director_studio.app import app
  char=next(a for a in self.extract() if a['kind']=='character');client=TestClient(app)
  try:
   with patch.object(jobs,'enqueue',return_value={'id':'test-job'}) as enqueue:
    r=client.post('/api/projects/'+self.pid+'/story-assets/'+char['id']+'/references',json={'source':'generate','prompt':'Photorealistic portrait'});self.assertEqual(r.status_code,200);enqueue.assert_called_once_with(self.pid,'run',[r.json()['reference']])
  finally:client.close()

 def test_visible_characters_require_a_ready_reference(self):
  assets=self.extract()
  with self.assertRaisesRegex(ValueError,'Mara'):story_assets.require_character_references(self.s,self.scene['id'])
  char=next(a for a in assets if a['kind']=='character');ref=story_assets.reference(self.s,char['id']);path=store.node_dir(self.s,ref)/'preview.jpg';path.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(16,16),'red').save(path);ref.update(output=str(path.relative_to(store.project_dir(self.pid))),status='succeeded')
  story_assets.require_character_references(self.s,self.scene['id'])
 def test_missing_character_from_another_episode_is_not_required(self):
  self.extract();other=store.add_node(self.s,'episode','Other','Unrelated');story_assets.require_character_references(self.s,other['id'])
 def test_voice_only_character_does_not_require_a_face_image(self):
  assets=self.extract();char=next(a for a in assets if a['kind']=='character');self.s['nodes'][char['id']]['offscreen']=True;story_assets.require_character_references(self.s,self.scene['id'])
