import json
from pathlib import Path
out=Path('director_studio/workflows');out.mkdir(exist_ok=True)
def node(t,**kw):return {'class_type':t,'inputs':kw}
# Native H3 graph follows the official Comfy-Org I2V template, without cloud nodes.
h={
 '1':node('UNETLoader',unet_name='MiniMax-H3-FL2VA-pruned_rank8_int8_convrot.safetensors',weight_dtype='default'),
 '2':node('CLIPLoaderGGUF',clip_name='qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf',type='minimax'),
 '3':node('VAELoader',vae_name='minimax_h3_video_vae_int8_convrot.safetensors'),
 '4':node('VAELoader',vae_name='MiniMax-H3-audio_vae_fp32.safetensors'),
 '5':node('LoadImage',image='reference.png'),
 '6':node('MiniMaxH3ImageToVideo',clip=['2',0],vae=['3',0],prompt='',width=768,height=1344,length=124,first_frame=['5',0]),
 '7':node('RandomNoise',noise_seed=42),
 '8':node('BasicGuider',model=['1',0],conditioning=['6',0]),
 '9':node('KSamplerSelect',sampler_name='res_multistep'),
 '10':node('BasicScheduler',model=['1',0],scheduler='simple',steps=20,denoise=1.0),
 '11':node('SamplerCustomAdvanced',noise=['7',0],guider=['8',0],sampler=['9',0],sigmas=['10',0],latent_image=['6',1]),
 '12':node('VAEDecode',samples=['11',0],vae=['3',0]),
 '13':node('VAEDecodeAudio',samples=['11',0],vae=['4',0]),
 '14':node('CreateVideo',images=['12',0],audio=['13',0],fps=24),
 '15':node('SaveVideo',video=['14',0],filename_prefix='JDirector/h3',format='mp4',**{'format.codec':'h264'})}
hspec={'graph':h,'bindings':{'prompt':[['6','prompt']],'reference1':[['5','image']],'width':[['6','width']],'height':[['6','height']],'frames':[['6','length']],'seed':[['7','noise_seed']],'steps':[['10','steps']]},'output_node':'15','source':'https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_i2v.json'}
(out/'h3.json').write_text(json.dumps(hspec,indent=2))
q={
 '1':node('UnetLoaderGGUF',unet_name='qwen-image-edit-2511-Q4_K_M.gguf'),
 '2':node('CLIPLoaderGGUF',clip_name='Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf',type='qwen_image'),
 '3':node('VAELoader',vae_name='qwen_vae.safetensors'),
 '4':node('LoadImage',image='reference.png'),
 '5':node('TextEncodeQwenImageEditPlus',clip=['2',0],vae=['3',0],image1=['4',0],prompt=''),
 '6':node('TextEncodeQwenImageEditPlus',clip=['2',0],vae=['3',0],image1=['4',0],prompt=''),
 '7':node('EmptySD3LatentImage',width=832,height=1472,batch_size=1),
 '8':node('ModelSamplingAuraFlow',model=['1',0],shift=3.0),
 '9':node('KSampler',model=['8',0],seed=42,steps=30,cfg=4.0,sampler_name='euler',scheduler='simple',positive=['5',0],negative=['6',0],latent_image=['7',0],denoise=1.0),
 '10':node('VAEDecode',samples=['9',0],vae=['3',0]),
 '11':node('SaveImage',images=['10',0],filename_prefix='JDirector/qwen')}
qs={'graph':q,'bindings':{'prompt':[['5','prompt']],'negative':[['6','prompt']],'reference1':[['4','image']],'seed':[['9','seed']],'steps':[['9','steps']],'guidance':[['9','cfg']],'width':[['7','width']],'height':[['7','height']]},'reference_encoder_nodes':['5','6'],'output_node':'11','source':'https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_edit_2511.json'}
(out/'qwen.json').write_text(json.dumps(qs,indent=2))
print('Native API workflow manifests created')
