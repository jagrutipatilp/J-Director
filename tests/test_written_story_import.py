import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from director_studio import store,jobs,engines
SCRIPT='''Story: CEO and Mafia
Format: 2 Episodes | Short AI Drama
Main characters
Isabella and Alexander.
EPISODE 1: Separate worlds
Scene 1: Office
Location: CEO office
Keyframe 1.1: Signing
Keyframe prompt:
Isabella signs a contract in her office.
Video prompt (1.1):
Assistant: "The investors arrived."
Isabella: "Let them wait."
Keyframe 1.2: Leaving
Keyframe prompt:
Isabella looks out of the window.
Video prompt (1.2):
She turns slowly.
EPISODE 1 CLIFFHANGER:
To be continued.
EPISODE 2: Meeting
This is not a 150-episode serial.
Scene 1: Dinner
Location: Rooftop
Keyframe 2.1: Wine
Keyframe prompt:
Alexander pours wine for Isabella.
Video prompt (2.1):
Isabella: "Why dinner?"
Alexander: "I like your company."
THE END.'''
class WrittenStoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=patch.object(store,'PROJECTS',Path(self.tmp.name)/'projects');self.p.start();self.s=store.create('Written test',SCRIPT,2);self.pid=self.s['id'];self.inventory=patch.object(jobs,'asset_inventory');self.inventory.start()
 def tearDown(self):self.inventory.stop();self.p.stop();self.tmp.cleanup()
 def test_authored_hierarchy_is_imported_without_ai_rewriting(self):
  with patch.object(engines,'chat') as chat:jobs.breakdown_job(self.pid,None)
  chat.assert_not_called();s=store.load(self.pid)
  self.assertEqual(sum(n['kind']=='episode' for n in s['nodes'].values()),2);self.assertEqual(sum(n['kind']=='scene' for n in s['nodes'].values()),2);self.assertEqual(sum(n['kind']=='keyframe' for n in s['nodes'].values()),3);self.assertEqual(sum(n['kind']=='clip' for n in s['nodes'].values()),3);self.assertFalse(any(n['kind']=='sequence' for n in s['nodes'].values()))
 def test_image_and_numbered_video_prompts_are_kept_separate(self):
  scene=engines.explicit_scenes(engines.explicit_episodes(SCRIPT)[0]['text'])[0];frame=engines.explicit_keyframes(scene['text'])[0]
  self.assertEqual(frame['prompt'],'Isabella signs a contract in her office.');self.assertIn('"Let them wait."',frame['video_prompt']);self.assertNotIn('Let them wait',frame['prompt'])
 def test_episode_scene_headings_take_priority_over_flat_keyframes(self):
  episode=store.add_node(self.s,'episode','One',engines.explicit_episodes(SCRIPT)[0]['text']);self.assertEqual(engines.breakdown_target(self.s,episode['id']),'scene')
 def test_declared_two_episodes_overrides_incidental_150(self):self.assertEqual(engines.requested_episode_count(SCRIPT),2)
 def test_reimport_preserves_backup_and_rejects_rendered_work(self):
  store.add_node(self.s,'episode','Old AI outline','Old plan');store.persist(self.s)
  jobs.import_written(self.pid);self.assertTrue(list((store.project_dir(self.pid)/'previous-breakdowns').glob('*written-import.json')))
  s=store.load(self.pid);next(n for n in s['nodes'].values() if n['kind']=='keyframe')['output']='existing.jpg';store.persist(s)
  with self.assertRaisesRegex(ValueError,'rendered or active'):jobs.import_written(self.pid)
