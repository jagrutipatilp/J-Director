import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from director_studio import store,engines,jobs

class EpisodeSceneTests(unittest.TestCase):
 def setUp(self):
  inventory=patch.object(jobs,'asset_inventory',return_value=None);inventory.start();self.addCleanup(inventory.stop)
  self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(store,'PROJECTS',Path(self.tmp.name)/'projects');self.p.start()
  self.s=store.create('Scene test','Season story');self.ep=store.add_node(self.s,'episode','Episode 1','Episode introduction\n\n## SCENE 1 — THE CAFE\nLocation: Cafe\nEve says, "Coming!"\n\n### Sequences\n1. Coffee pours.\n\n## SCENE 2 — THE CAR\nLocation: Car\nRailey says, "Father."\n\n## SCENE 3 — NIGHT\nLater that night, she leaves.');store.persist(self.s);self.pid=self.s['id']
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def test_numbered_scene_headings_bypass_ai_and_preserve_dialogue(self):
  with patch.object(engines,'chat') as chat:
   target,items,_=engines.breakdown(self.s,self.ep['id'],lambda *a:None)
  chat.assert_not_called();self.assertEqual(target,'scene');self.assertEqual(len(items),3)
  self.assertIn('"Coming!"',items[0]['text']);self.assertNotIn('"Father."',items[0]['text']);self.assertIn('"Father."',items[1]['text']);self.assertIn('Later that night',items[2]['text'])
 def test_screenplay_slugs_are_boundaries(self):
  items=engines.explicit_scenes('EXT. STREET - DAY\nWalks.\nINT. CAFE - DAY\nSits.');self.assertEqual(len(items),2)
  self.assertEqual(engines.explicit_scenes('She says scene 1 looks fine.\nOne continuous conversation.'),[])
 def test_rebreakdown_archives_bad_scene_and_creates_individual_markdown(self):
  bad=store.add_node(self.s,'scene','Whole episode',self.ep['text'],self.ep['id']);store.persist(self.s)
  jobs.breakdown_job(self.pid,self.ep['id'],replace_existing=True)
  state=store.load(self.pid);scenes=store.children(state,self.ep['id']);self.assertEqual(len(scenes),3);self.assertNotIn(bad['id'],state['nodes'])
  self.assertTrue(list((store.project_dir(self.pid)/'previous-breakdowns').glob('*.json')))
  for scene in scenes:self.assertTrue((store.node_dir(state,scene)/'scene.md').is_file())
  self.assertEqual(state['nodes'][self.ep['id']]['text'],self.ep['text'])
  restored=store.undo(self.pid,'undo');self.assertIn(bad['id'],restored['nodes'])
 def test_developed_scenes_are_never_replaced(self):
  bad=store.add_node(self.s,'scene','Developed',self.ep['text'],self.ep['id']);store.add_node(self.s,'sequence','Keep work',parent=bad['id']);store.persist(self.s)
  with self.assertRaisesRegex(ValueError,'developed or rendered'):jobs.breakdown_job(self.pid,self.ep['id'],replace_existing=True)
  self.assertIn(bad['id'],store.load(self.pid)['nodes'])
 def test_single_prose_scene_uses_ai_with_episode_text(self):
  self.ep['text']='A continuous conversation in one room.'
  with patch.object(engines,'chat',return_value={'items':[{'title':'Room','text':self.ep['text'],'prompt':''}]}) as chat:
   _,items,_=engines.breakdown(self.s,self.ep['id'],lambda *a:None)
  self.assertEqual(len(items),1);self.assertIn(self.ep['text'],chat.call_args.args[1])
