import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from director_studio import generation_settings as g,comfy_workflows as w
class GenerationSettingsTests(unittest.TestCase):
 def test_format_profiles_match_lora(self):
  self.assertEqual(g.dimensions('h3',dict(g.DEFAULTS,video_format='portrait')),(384,672))
  self.assertEqual(g.dimensions('h3',dict(g.DEFAULTS,video_format='portrait',video_mode='standard')),(480,832))
  self.assertEqual(g.dimensions('qwen',dict(g.DEFAULTS,image_format='768x1344')),(768,1344))
 def test_invalid_preferences_and_camera_rejected(self):
  for value in [{'style':'unknown'},{'image_format':'99999x99999'},{'token':'secret'}]:
   with self.assertRaises(ValueError):g.validate(value)
  with self.assertRaises(ValueError):g.camera_validate({'height':'invented'})
 def test_camera_prompt_contains_only_selected_groups(self):
  text=g.camera_prompt({'height':'overhead','framing':'wide'})
  self.assertIn('directly overhead',text);self.assertIn('Wide establishing',text)
  self.assertEqual(g.camera_prompt({}),'')
 def test_missing_turbo_is_not_silently_standard(self):
  with self.assertRaises(ValueError):g.apply_graph({}, {},'h3',g.DEFAULTS,{})
 def test_qwen_actual_lightning_settings(self):
  spec={'graph':{},'model_lora_hook':['sample','model']};graph={'sample':{'class_type':'KSampler','inputs':{'model':['base',0],'steps':30,'cfg':4}}}
  schema={'LoraLoaderModelOnly':{'input':{'required':{'lora_name':[[g.QWEN_ADAPTER]]}}}}
  graph=g.apply_graph(graph,spec,'qwen',g.DEFAULTS,schema)
  self.assertEqual(graph['sample']['inputs']['steps'],8);self.assertEqual(graph['sample']['inputs']['cfg'],1)
  self.assertEqual(graph['lightning_lora']['inputs']['strength_model'],1)
 def test_h3_turbo_adapter_guider_scheduler_sampler(self):
  spec=json.loads((g.store.ROOT/'director_studio/workflows/h3.json').read_text())
  schema={'MiniMaxH3TurboLoRA':{'input':{'required':{'lora_name':[[g.H3_ADAPTER]]}}}}
  graph=g.apply_graph(spec['graph'],spec,'h3',g.DEFAULTS,schema)
  self.assertEqual(graph['10']['inputs']['steps'],6);self.assertEqual(graph['8']['inputs']['model'],['h3_turbo_lora',0]);self.assertEqual(graph['9']['class_type'],'MiniMaxH3TurboSampler')
 def test_manhwa_keeps_all_boards_and_reserves_style_slot(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'assets/styles').mkdir(parents=True)
   Image.new('RGB',(20,20)).save(root/'assets/styles/manhwa-style.png')
   paths=[]
   for i in range(3):
    p=root/(str(i)+'.jpg');Image.new('RGB',(20,20),(i*50,0,0)).save(p);paths.append(str(p))
   prompt,negative,refs=g.style_prepare({'existing_runtime':temp},g.DEFAULTS,'scene','',paths,root)
   self.assertEqual(len(refs),3);self.assertEqual(refs[0],paths[0]);self.assertIn('STYLE ONLY',prompt)
   self.assertTrue(Path(refs[1]).exists());self.assertIn('photograph',negative)
 def test_realistic_adds_no_style_reference(self):
  prompt,negative,refs=g.style_prepare({},dict(g.DEFAULTS,style='realistic'),'scene','',['identity.jpg'],Path('.'))
  self.assertEqual(refs,['identity.jpg']);self.assertIn('REALISTIC PHOTO STYLE',prompt)
if __name__=='__main__':unittest.main()
