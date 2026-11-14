"""Hierarchy and actual image-board tests, with temporary assets only."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from director_studio import store,production,continuity

class ProductionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.p=patch.object(store,'PROJECTS',self.root/'projects');self.p.start()
  s=store.create('Production test','Story');self.pid=s['id'];self.s=s
  arc=store.add_node(s,'arc','Arc');ep=store.add_node(s,'episode','Episode',parent=arc['id']);self.scene=store.add_node(s,'scene','Scene',parent=ep['id']);self.seq=store.add_node(s,'sequence','Sequence',parent=self.scene['id']);self.frame=store.add_node(s,'keyframe','Shot',parent=self.seq['id'])
  self.people=[store.add_node(s,'character',name) for name in ['Mara','Eve']];loc=store.add_node(s,'location','Cafe');prop=store.add_node(s,'prop','Watch')
  self.bg=self.ref(loc,'Cafe wide','Angles','blue');self.watch=self.ref(prop,'Watch','Accessories','yellow');self.refs=[]
  for person in self.people:self.refs.append({k:self.ref(person,k,category,color) for k,category,color in [('identity','Poses','red'),('outfit','Outfits','green'),('accessory','Accessories','yellow'),('expression','Expressions','pink')]})
  self.scene['production']={'background':self.bg};self.seq['production']={'cast':[{'character':c['id'],'identity':r['identity'],'outfit':r['outfit'],'accessories':[r['accessory']]} for c,r in zip(self.people,self.refs)],'props':[self.watch]};store.persist(s)
 def ref(self,parent,title,category,color):
  n=store.add_node(self.s,'reference',parent['title']+' '+title,parent=parent['id'],category=category,status='saved',locked=True,version=1)
  path=store.project_dir(self.pid)/(n['id']+'.jpg');Image.new('RGB',(64,80),color).save(path);n['output']=path.name;return n['id']
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def test_hierarchy_and_character_exclusion(self):
  self.frame['production']={'characters':[self.people[0]['id']],'expressions':{self.people[0]['id']:self.refs[0]['expression']}}
  rows=production.resolve(self.s,self.frame);ids=[r['id'] for r in rows]
  self.assertEqual(ids,[self.bg,self.refs[0]['identity'],self.refs[0]['outfit'],self.refs[0]['accessory'],self.refs[0]['expression'],self.watch])
  self.assertFalse(set(self.refs[1].values())&set(ids))
  self.frame['production'].update(characters=[],inherit_background=False);self.assertEqual(production.ids(self.s,self.frame),[self.watch])
 def test_all_selected_images_are_in_boards_without_truncation(self):
  self.frame['production']={'expressions':{self.people[0]['id']:self.refs[0]['expression']}}
  folder=self.root/'boards';folder.mkdir();paths,rows,legend=production.boards(self.s,self.frame,folder)
  self.assertEqual(len(paths),3);self.assertEqual(len(rows),9);self.assertEqual(len({r['id'] for r in rows}),9)
  self.assertTrue(all(Path(p).is_file() for p in paths));self.assertTrue(any('expression' in text for text in legend))
  widths=[]
  for path in paths:
   with Image.open(path) as image:widths.append(image.width)
  self.assertTrue(any(width>64 for width in widths))
 def test_identity_first_boards_keep_background_and_character_roles(self):
  folder=self.root/'identity-first';folder.mkdir()
  paths,rows,legend=production.boards(self.s,self.frame,folder,identity_first=True)
  self.assertEqual(rows[0]['role'],'identity')
  self.assertTrue('identity' in legend[0] and 'Mara' in legend[0])
  self.assertEqual({r['id'] for r in rows},set(production.ids(self.s,self.frame)))
  self.assertTrue(any('background' in label for label in legend))
 def test_prompt_only_remains_optional(self):
  self.scene.pop('production');self.seq.pop('production');self.assertEqual(production.resolve(self.s,self.frame),[])
  folder=self.root/'empty';folder.mkdir();self.assertEqual(production.boards(self.s,self.frame,folder),([],[],[]))
 def test_cross_character_expression_is_rejected(self):
  value={'expressions':{self.people[0]['id']:self.refs[1]['expression']}}
  with self.assertRaises(ValueError):production.validate(self.s,self.frame,value)
  with self.assertRaises(ValueError):production.validate(self.s,self.scene,{'background':self.refs[0]['identity']})
 def test_edit_persists_and_protects_rendered_and_running_shots(self):
  state=store.edit(self.pid,self.frame['id'],{'production':{'characters':[]}});self.assertEqual(state['nodes'][self.frame['id']]['production']['characters'],[])
  state['nodes'][self.frame['id']].update(status='running');store.persist(state)
  with self.assertRaises(ValueError):store.edit(self.pid,self.scene['id'],{'production':{'background':''}})
  state['nodes'][self.frame['id']].update(status='succeeded');store.persist(state)
  with self.assertRaises(ValueError):store.edit(self.pid,self.frame['id'],{'production':{'characters':[self.people[0]['id']]}})
 def test_inherited_version_affects_continuity_signature(self):
  before=continuity.signature(self.s,self.frame);self.s['nodes'][self.bg]['version']=2
  self.assertNotEqual(before,continuity.signature(self.s,self.frame))
 def test_missing_selected_reference_is_not_silently_dropped(self):
  self.s['nodes'][self.bg]['output']=None;folder=self.root/'missing';folder.mkdir()
  with self.assertRaises(ValueError):production.boards(self.s,self.frame,folder)
