import io,json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from director_studio import store,jobs,character_forge,story_assets
class ForgeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.p=patch.object(store,'PROJECTS',self.root/'projects');self.q=patch.object(jobs,'QUEUE',self.root/'queue.json');self.p.start();self.q.start()
  self.s=store.create('Forge test','Story');self.pid=self.s['id'];self.a=store.add_node(self.s,'character','Person');self.master=store.add_node(self.s,'reference','Uploaded master',parent=self.a['id'],status='saved');dest=store.project_dir(self.pid)/'master.jpg';Image.new('RGB',(64,80),'red').save(dest);self.master['output']='master.jpg';self.a['primary_reference']=self.master['id'];store.persist(self.s);self.before=dest.read_bytes()
 def tearDown(self):self.p.stop();self.q.stop();self.tmp.cleanup()
 def test_sheet_queue_keeps_master(self):
  job=jobs.enqueue(self.pid,'character_sheet',[self.a['id']]);self.assertEqual(job['operation'],'character_sheet');self.assertIn('Character Forge',jobs.job_context(job));self.assertEqual(store.load(self.pid)['nodes'][self.a['id']]['primary_reference'],self.master['id'])
 def test_maintenance_uses_its_queue_directory(self):
  jobs.store.atomic(jobs.QUEUE.with_name('generation-maintenance.json'),{'active':True})
  with self.assertRaises(ValueError):jobs.enqueue(self.pid,'character_sheet',[self.a['id']])
 def test_derived_views_require_review_and_never_replace_master(self):
  def launch(command,**kwargs):
   request=json.loads(Path(command[-1]).read_text());out=Path(request['output']);out.mkdir(parents=True);views=[]
   for name in ['reference_full_body','front_portrait','side_portrait','side_body','rear_body']:
    dest=out/(name+'.jpg');Image.new('RGB',(64,80),'blue').save(dest);views.append({'name':name,'path':str(dest)})
   sheet=out/'sheet.jpg';Image.new('RGB',(64,80),'green').save(sheet);(out/'result.json').write_text(json.dumps({'views':views,'sheet':str(sheet)}))
   class Proc:
    stdout=io.StringIO('FORGE_STAGE '+json.dumps({'stage':1,'message':'Front portrait'})+'\nFORGE_PROGRESS '+json.dumps({'value':15,'max':30})+'\n');stdin=io.StringIO()
    def poll(self):return 0
    def wait(self,**kwargs):return 0
   return Proc()
  checkpoints=[];percentages=[]
  with patch.object(character_forge.engines,'ensure_comfy'),patch.object(character_forge.subprocess,'Popen',side_effect=launch):character_forge.run(self.pid,self.a['id'],'',lambda message,percent:percentages.append(percent),lambda:checkpoints.append(True))
  s=store.load(self.pid);derived=[n for n in s['nodes'].values() if n.get('reference_source')=='character_forge'];self.assertEqual(len(derived),6);self.assertTrue(all(n['requires_review'] for n in derived));self.assertEqual(story_assets.reference(s,self.a['id'])['id'],self.master['id']);self.assertEqual((store.project_dir(self.pid)/'master.jpg').read_bytes(),self.before);self.assertTrue(checkpoints);self.assertIn(30,percentages)
  s['nodes'][self.a['id']].pop('primary_reference');s['nodes'][self.master['id']]['archived']=True;self.assertIsNone(story_assets.reference(s,self.a['id']))
if __name__=='__main__':unittest.main()
