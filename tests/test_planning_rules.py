import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from director_studio import store,planning_rules,story_assets,production,reference_planner

class PlanningPolicyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);p=patch.object(store,'PROJECTS',Path(self.tmp.name)/'projects');p.start();self.addCleanup(p.stop)
  self.s=store.create('Policy','Story');self.ep=store.add_node(self.s,'episode','Episode');self.scene=store.add_node(self.s,'scene','Scene',parent=self.ep['id']);self.frame=store.add_node(self.s,'keyframe','Frame',parent=self.scene['id'],prompt='A child beside her motionless parent')
 def test_concealed_body_is_incidental_but_recurring_flashback_identity_is_not(self):
  row={'description':'Motionless adult man, face partly concealed. No visible wounds.'};self.assertTrue(planning_rules.incidental(row))
  self.assertFalse(planning_rules.incidental({'description':'Motionless adult, face hidden; recurring flashback identity'}))
  self.assertFalse(planning_rules.incidental({**row,'reference_policy':'persistent'}))
  self.assertFalse(planning_rules.incidental({'description':'Pivotal child, face hidden by hair, speaking through sobs'}))
 def test_incidental_extraction_keeps_shot_detail_without_creating_character(self):
  result={'characters':[{'name':'Anonymous body','description':'Motionless woman, face hidden','used_in':[self.frame['id']],'reference_policy':'prompt_only'}],'backgrounds':[]}
  story_assets.upsert(self.s,result,{self.frame['id']:'Shot'})
  self.assertFalse(any(n['kind']=='character' for n in self.s['nodes'].values()));self.assertIn('Anonymous body',self.frame['incidental_figures'])
 def test_retirement_removes_identity_dependencies_but_preserves_files_and_pose_text(self):
  a=store.add_node(self.s,'character','Parent','Motionless body with concealed face');r=store.add_node(self.s,'reference','Portrait',parent=a['id']);a['primary_reference']=r['id'];self.frame.update(asset_links={'characters':[a['id']],'backgrounds':[]},asset_links_manual=True,references=[r['id']])
  planning_rules.retire(self.s,a['id']);self.assertTrue(a['archived']);self.assertTrue(r['archived']);self.assertIn('Parent',self.frame['incidental_figures']);self.assertEqual(production.ids(self.s,self.frame),[])
 def test_single_location_creates_only_master_but_keeps_supplied_extra_view(self):
  a=store.add_node(self.s,'location','One-off corridor','Interior',view_policy='single');m=store.add_node(self.s,'reference','Master',parent=a['id']);a['primary_reference']=m['id']
  views=reference_planner.ensure_views(self.s,a['id']);self.assertEqual(views,{'master':m['id']});self.assertEqual(len(store.children(self.s,a['id'])),1)
  h=store.add_node(self.s,'reference','User overhead',parent=a['id'],view_kind='high',provided_view=True,output='provided.png');views=reference_planner.ensure_views(self.s,a['id']);self.assertEqual(views['high'],h['id']);self.assertEqual(len(store.children(self.s,a['id'])),2)

 def test_bad_or_duplicate_view_choices_fall_back_within_the_same_location(self):
  batch=[{'keyframe':'a','background':'room','shot':'Overhead view','available_views':[{'reference':'front','view':'Master / front wide view'},{'reference':'high','view':'High angle view'}]},{'keyframe':'b','background':'hall','shot':'Wide shot','available_views':[{'reference':'corridor','view':'Master / front wide view'}]}]
  result={'background_choices':[{'keyframe':'a','background':'room','reference':'wrong-room'},{'keyframe':'b','background':'hall','reference':'corridor','reason':'Valid'},{'keyframe':'b','background':'hall','reference':'front'}]}
  choices,invalid=reference_planner.checked_choices(batch,result);by={c['keyframe']:c for c in choices}
  self.assertEqual(invalid,2);self.assertEqual(by['a']['reference'],'high');self.assertEqual(by['a']['source'],'validated_fallback');self.assertEqual(by['b']['reference'],'corridor');self.assertEqual(by['b']['source'],'ollama')
