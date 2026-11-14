"""Shared library isolation, versioning and cross-story reuse."""
import io,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from director_studio import library,store

class SharedLibraryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.p1=patch.object(library,'ROOT',self.root/'library');self.p1.start()
  self.p2=patch.object(store,'PROJECTS',self.root/'projects');self.p2.start()
 def tearDown(self):self.p2.stop();self.p1.stop();self.temp.cleanup()
 def image(self,color):
  raw=io.BytesIO();Image.new('RGB',(48,64),color).save(raw,'PNG');return raw.getvalue()
 def test_character_can_be_created_before_any_story_and_reused(self):
  a=library.save_asset({'kind':'character','name':'User-chosen character','description':'Stable identity'})
  v=library.save_variant(a['id'],{'title':'Default outfit','category':'Outfits','prompt':'A neutral reference portrait in a black coat'})
  library.save_image(a['id'],v['id'],self.image('red'))
  projects=[store.create('Story '+str(i),'A story.') for i in (1,2)]
  refs=[library.attach(p['id'],a['id']) for p in projects]
  for p,r in zip(projects,refs):
   n=r['project']['nodes'][r['references'][0]];self.assertEqual(n['library_asset'],a['id']);self.assertTrue(n['locked']);self.assertTrue(store.contained(p['id'],n['output']).exists())
  self.assertEqual(len(library.load()['assets']),1)
 def test_new_image_version_does_not_replace_other_story_reference(self):
  a=library.save_asset({'kind':'location','name':'User-chosen location','description':'A room'})
  v=library.save_variant(a['id'],{'title':'Front view','category':'Angles','prompt':'Front view of a room'})
  first=library.save_image(a['id'],v['id'],self.image('red'));p=store.create('Story','A room.')
  r=library.attach(p['id'],a['id']);old=r['project']['nodes'][r['references'][0]];oldbytes=store.contained(p['id'],old['output']).read_bytes()
  second=library.save_image(a['id'],v['id'],self.image('blue'));self.assertEqual(second['version'],2);self.assertTrue(library.media_path(first['output']).exists())
  self.assertEqual(store.contained(p['id'],old['output']).read_bytes(),oldbytes)
  new=library.attach(p['id'],a['id']);self.assertNotEqual(new['references'][0],old['id'])
 def test_camera_view_import_brings_its_master_and_keeps_selection_on_view(self):
  a=library.save_asset({'kind':'location','name':'Cafe','description':'Photographic location'})
  master=library.save_variant(a['id'],{'title':'Master','category':'Angles','prompt':'Original photographic cafe'})
  library.save_image(a['id'],master['id'],self.image('red'))
  view=library.save_variant(a['id'],{'title':'High angle','category':'Angles','prompt':'<sks> front view high-angle shot medium shot'})
  catalog=library.load();library.variant(library.find(catalog,a['id']),view['id'])['provenance']={'master_variant':master['id']};library.persist(catalog)
  p=store.create('A story','A cafe scene.');result=library.attach(p['id'],a['id'],[view['id']])
  self.assertEqual(len(result['references']),1)
  target=result['project']['nodes'][result['references'][0]]
  self.assertEqual(target['library_variant'],view['id']);self.assertEqual(len(target['references']),1)
  source=result['project']['nodes'][target['references'][0]]
  self.assertEqual(source['library_variant'],master['id']);self.assertTrue(source['locked']);self.assertTrue(store.contained(p['id'],source['output']).exists())
 def test_removing_reference_is_recoverable_and_preserves_story_images(self):
  a=library.save_asset({'kind':'character','name':'Character','description':'Identity'})
  v=library.save_variant(a['id'],{'title':'Portrait','category':'Outfits','prompt':'Adult portrait'})
  image=library.save_image(a['id'],v['id'],self.image('red'));p=store.create('Story','A story.')
  attached=library.attach(p['id'],a['id']);ref=attached['project']['nodes'][attached['references'][0]]
  library.archive_variant(a['id'],v['id'])
  self.assertTrue(library.variant(library.find(library.load(),a['id']),v['id'])['archived'])
  self.assertTrue(library.media_path(image['output']).exists());self.assertTrue(store.contained(p['id'],ref['output']).exists())
  with self.assertRaises(ValueError):library.attach(p['id'],a['id'],[v['id']])
  library.archive_variant(a['id'],v['id'],False)
  self.assertFalse(library.variant(library.find(library.load(),a['id']),v['id'])['archived'])
  self.assertEqual(library.attach(p['id'],a['id'],[v['id']])['references'][0],ref['id'])
 def test_empty_name_and_escaped_image_paths_rejected(self):
  with self.assertRaises(ValueError):library.save_asset({'kind':'character','name':'','description':'x'})
  with self.assertRaises(ValueError):library.media_path('../../private.jpg')
 def test_jpeg_upload_preserves_original_bytes(self):
  a=library.save_asset({'kind':'character','name':'Claire','description':'Identity'})
  v=library.save_variant(a['id'],{'title':'Master','category':'Angles','prompt':'Original portrait'})
  raw=io.BytesIO();Image.new('RGB',(48,64),'red').save(raw,'JPEG',quality=97);saved=library.save_image(a['id'],v['id'],raw.getvalue())
  self.assertEqual(library.media_path(saved['output']).read_bytes(),raw.getvalue())
 def test_catalogue_character_can_fill_a_story_role_without_duplicate_actor(self):
  from director_studio import production,story_assets
  a=library.save_asset({'kind':'character','name':'Claire','description':'Canonical appearance'})
  face=library.save_variant(a['id'],{'title':'Face','category':'Angles','prompt':'Face reference'});body=library.save_variant(a['id'],{'title':'Outfit','category':'Outfits','prompt':'Black suit'})
  for v in [face,body]:library.save_image(a['id'],v['id'],self.image('red'))
  catalog=library.load();library.find(catalog,a['id']).update(primary_variant=face['id'],default_outfit_variant=body['id']);library.persist(catalog)
  s=store.create('Story','A story');role=store.add_node(s,'character','Isabella');old=store.add_node(s,'reference','Earlier person',parent=role['id']);role['primary_reference']=old['id'];ep=store.add_node(s,'episode','Episode');frame=store.add_node(s,'keyframe','Frame',parent=ep['id'],asset_links={'characters':[role['id']],'backgrounds':[]},asset_links_manual=True);store.persist(s)
  result=library.attach(s['id'],a['id'],target_asset=role['id']);s=result['project'];self.assertEqual(len([n for n in s['nodes'].values() if n['kind']=='character']),1);self.assertEqual(s['nodes'][role['id']]['title'],'Isabella');self.assertTrue(s['nodes'][old['id']]['archived']);self.assertEqual(story_assets.reference(s,role['id'])['library_variant'],face['id']);self.assertTrue(production.direction(s,s['nodes'][frame['id']])['cast'][0]['outfit'])
  again=library.attach(s['id'],a['id'],target_asset=role['id']);self.assertEqual(set(result['references']),set(again['references']))
 def test_new_story_import_receives_the_same_primary_and_outfit(self):
  a=library.save_asset({'kind':'character','name':'Claire','description':'Shared appearance'})
  face=library.save_variant(a['id'],{'title':'Face','category':'Angles','prompt':'Face reference'});body=library.save_variant(a['id'],{'title':'Body','category':'Outfits','prompt':'Body reference'})
  for v in [face,body]:library.save_image(a['id'],v['id'],self.image('red'))
  catalog=library.load();library.find(catalog,a['id']).update(primary_variant=face['id'],default_outfit_variant=body['id']);library.persist(catalog)
  project=store.create('Other story','Story');s=library.attach(project['id'],a['id'])['project'];role=next(n for n in s['nodes'].values() if n['kind']=='character');self.assertEqual(s['nodes'][role['primary_reference']]['library_variant'],face['id']);self.assertEqual(s['nodes'][role['default_outfit']]['library_variant'],body['id'])

 def test_saved_character_is_registered_once_and_reused_in_next_story(self):
  s=store.create('First','Story');person=store.add_node(s,'character','Reusable actor','Stable adult identity');ref=store.add_node(s,'reference','Master',parent=person['id'],prompt='Neutral portrait',category='Angles',status='succeeded');person['primary_reference']=ref['id'];path=store.node_dir(s,ref)/'preview.jpg';path.parent.mkdir(parents=True);Image.new('RGB',(32,32),'red').save(path);ref['output']=str(path.relative_to(store.project_dir(s['id'])));store.persist(s)
  store.save_box(s['id'],ref['id']);store.save_box(s['id'],ref['id']);catalog=library.load();self.assertEqual(len(catalog['assets']),1);self.assertEqual(catalog['assets'][0]['variants'][0]['version'],1)
  second=store.create('Second','Story');role=store.add_node(second,'character','Reusable actor','Same actor');store.persist(second)
  self.assertTrue(library.reuse_character(second['id'],role['id']));now=store.load(second['id']);self.assertTrue(now['nodes'][now['nodes'][role['id']]['primary_reference']]['output'])

if __name__=='__main__':unittest.main()
