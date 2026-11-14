import tempfile, unittest, json
from pathlib import Path
from unittest.mock import patch
from director_studio import store,continuity,library,engines

class ContinuityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
  self.patches=[patch.object(store,'PROJECTS',root/'projects'),patch.object(continuity,'ROOT',root/'continuity'),patch.object(library,'ROOT',root/'library')]
  for p in self.patches:p.start()
  self.s=store.create('Season','A complete story');self.pid=self.s['id']
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def setup_shots(self):
  s=self.s;arc=store.add_node(s,'arc','Arc');episodes=[store.add_node(s,'episode',str(i),parent=arc['id']) for i in range(3)]
  person=store.add_node(s,'character','Mara');ref=store.add_node(s,'reference','Mara face',parent=person['id'],library_asset='mara',library_variant='face',library_version=1,output='face.jpg',status='saved')
  frames=[];clips=[]
  for ep in episodes:
   sc=store.add_node(s,'scene','Scene',parent=ep['id']);sq=store.add_node(s,'sequence','Sequence',parent=sc['id']);frame=store.add_node(s,'keyframe','Frame',parent=sq['id'],references=[ref['id']]);frames.append(frame)
   clips.append(store.add_node(s,'clip','Video',parent=sq['id'],depends_on=frame['id'],status='saved',output='video.mp4',render_quality='final'))
  store.persist(s);return episodes,frames,clips,ref
 def test_approved_real_frame_only_flows_forward_for_same_asset_versions(self):
  eps,frames,clips,ref=self.setup_shots()
  def extract(args,**kwargs):Path(args[-1]).write_bytes(b'approved video frame')
  with patch.object(continuity.subprocess,'run',side_effect=extract):approval=continuity.approve(self.pid,eps[0]['id'])
  self.assertEqual(Path(continuity.previous_frame(self.s,frames[1])['path']).read_bytes(),b'approved video frame')
  self.assertIsNone(continuity.previous_frame(self.s,frames[0]))
  ref['library_version']=2;self.assertIsNone(continuity.previous_frame(self.s,frames[1]))
  self.assertEqual(len(continuity.records(self.pid)),1)
 def test_draft_and_unsaved_videos_cannot_be_approved(self):
  eps,frames,clips,ref=self.setup_shots();self.s['quality']='draft';store.persist(self.s)
  with self.assertRaises(ValueError):continuity.approve(self.pid,eps[0]['id'])
  self.s['quality']='final';clips[0]['status']='succeeded';store.persist(self.s)
  with self.assertRaises(ValueError):continuity.approve(self.pid,eps[0]['id'])
  self.assertEqual(continuity.records(self.pid),[])
 def test_shot_matching_does_not_take_arbitrary_references(self):
  eps,frames,clips,ref=self.setup_shots()
  self.assertEqual(continuity.select_references(self.s,'Mara enters the room'),[ref['id']]);self.assertEqual(continuity.select_references(self.s,'Empty woodland'),[])
 def test_props_are_shared_assets(self):
  asset=library.save_asset({'kind':'prop','name':'Red watch','description':'A recurring watch'});self.assertEqual(asset['kind'],'prop')
 def test_planner_receives_season_and_asset_bible(self):
  eps,frames,clips,ref=self.setup_shots()
  with patch.object(engines,'chat',return_value={'items':[{'title':'Scene','text':'Action','prompt':'Mara'}]}) as chat:
   engines.breakdown(self.s,eps[1]['id'],lambda *a:None)
  data=json.loads(chat.call_args.args[1]);self.assertEqual(len(data['season_outline']),4);self.assertEqual(data['asset_bible'][0]['name'],'Mara')

 def test_direct_episode_timeline_obeys_reordering(self):
  first=store.add_node(self.s,'episode','First');second=store.add_node(self.s,'episode','Second');store.persist(self.s)
  self.assertEqual([e['id'] for e in continuity.timeline(self.s)],[first['id'],second['id']])
  state=store.reorder(self.pid,second['id'],-1);self.assertEqual([e['id'] for e in continuity.timeline(state)],[second['id'],first['id']])

 def test_story_episode_ranges_are_preserved(self):
  self.assertEqual(engines.requested_episode_count('Episodes 1–5: opening. Episodes 36–40: ending.'),40)
  self.assertIsNone(engines.requested_episode_count('A short story without a requested length.'))
  self.s['story_working']='Episodes 1–40: the full season'
  with patch.object(engines,'chat',return_value={'items':[{'title':'Only one','text':'Incomplete','prompt':''}]}):
   with self.assertRaisesRegex(RuntimeError,'40 separate episodes'):engines.breakdown(self.s,None,lambda *a:None)
