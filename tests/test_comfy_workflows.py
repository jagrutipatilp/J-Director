import unittest
from director_studio.comfy_workflows import build,validate_local
class WorkflowTests(unittest.TestCase):
 def test_qwen_all_references_are_wired(self):
  spec={'graph':{'1':{'class_type':'TextEncode','inputs':{}},'2':{'class_type':'LoadImage','inputs':{'image':'stale'}}},'reference_encoder_nodes':['1'],'bindings':{'reference1':[['2','image']]}}
  g=build(spec,{},['a','b','c'],'qwen')
  self.assertEqual(g['2']['inputs']['image'],'a');self.assertEqual(g['reference_2']['inputs']['image'],'b');self.assertEqual(g['1']['inputs']['image3'],['reference_3',0]);self.assertEqual(spec['graph']['2']['inputs']['image'],'stale')
 def test_uploaded_image_is_not_rejected_by_cached_file_list(self):
  validate_local({'1':{'class_type':'LoadImage','inputs':{'image':'new-upload.jpg'}}},{'LoadImage':{'input':{'required':{'image':[['old-upload.jpg']]}}}})
 def test_camera_adapter_keeps_the_model_sampling_connection(self):
  from director_studio.comfy_workflows import attach_model_lora
  graph={'8':{'class_type':'ModelSamplingAuraFlow','inputs':{'model':['1',0]}}}
  attach_model_lora(graph,{'model_lora_hook':['8','model']},'camera.safetensors',0.9)
  self.assertEqual(graph['8']['inputs']['model'],['camera_lora',0]);self.assertEqual(graph['camera_lora']['inputs']['model'],['1',0])
 def test_missing_reference_is_rejected(self):
  with self.assertRaises(ValueError):build({'graph':{}},{},[],'qwen')
 def test_h3_frame_grid(self):
  spec={'graph':{'1':{'class_type':'H3','inputs':{}}},'bindings':{'frames':[['1','length']]}}
  self.assertEqual(build(spec,{'seconds':5},['a'],'h3')['1']['inputs']['length'],124)
 def test_unavailable_model_fails_before_submission(self):
  with self.assertRaises(ValueError):validate_local({'1':{'class_type':'Loader','inputs':{'model':'missing'}}},{'Loader':{'input':{'required':{'model':[['available']]}}}})
 def test_cloud_node_is_rejected(self):
  with self.assertRaises(ValueError):validate_local({'1':{'class_type':'ComfyCloudVideo','inputs':{}}},{'ComfyCloudVideo':{}})
if __name__=='__main__':unittest.main()
