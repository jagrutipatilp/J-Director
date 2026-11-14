"""Configure KupkaProd for the existing ComfyUI and a 6 GB GPU."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'video_director_agent'
COMFY = Path(r'C:\src\ai drama\tools\ComfyUI')


def original(name):
    path = APP / name
    backup = path.with_suffix('.upstream.json')
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    return json.loads(backup.read_text())


video = original('workflow_template.json')
video.pop('153:150', None)  # Unused CLIP debug output retains the text encoder.
video['153:146'] = {'class_type': 'UnetLoaderGGUF', 'inputs': {
    'unet_name': 'ltx-2.3-22b-distilled-1.1-Q3_K_S.gguf'}}
for node in ('153:156', '153:157'):
    video[node] = {'class_type': 'VAELoader', 'inputs': {
        'vae_name': video[node]['inputs']['vae_name']}}
video['153:158']['inputs']['clip_name1'] = 'gemma_3_12B_it_fp4_mixed.safetensors'
video['153:158']['inputs']['device'] = 'default'
for node in video.values():
    if node['class_type'] == 'VAEDecodeTiled':
        node['inputs'].update(tile_size=256, overlap=64, temporal_size=16, temporal_overlap=4)
(APP / 'workflow_template.json').write_text(json.dumps(video, indent=2))

image = original('keyframe_template.json')
image.pop('62', None)  # Unconnected LTX encoder from the upstream workflow.
image['57:28'] = {'class_type': 'UnetLoaderGGUF', 'inputs': {
    'unet_name': 'z-image-turbo-Q4_K_M.gguf'}}
image['57:30']['inputs'].update(clip_name='qwen_3_4b_fp4_mixed.safetensors', device='cpu')
(APP / 'keyframe_template.json').write_text(json.dumps(image, indent=2))

settings = {
    'comfyui_root': str(COMFY),
    'comfyui_output_dir': str(COMFY / 'output'),
    'comfyui_host': '127.0.0.1:8190',
    'comfyui_hosts': ['127.0.0.1:8190'],
    'comfyui_launcher': str(ROOT / 'start-comfyui.cmd'),
    'project_output_root': str(APP / 'output'),
    'ollama_host': 'http://127.0.0.1:11434',
    'llm_provider': 'ollama',
    'llm_base_url': 'http://127.0.0.1:11434',
    'llm_creative_drafting_mode': False,
    'ollama_model_creative': 'gemma4:e4b',
    'ollama_model_fast': 'gemma4:e4b',
    'takes_per_scene': 1,
    'scene_min_sec': 2,
    'scene_max_sec': 4,
    'kf_width': 640,
    'kf_height': 384,
    'video_width': 512,
    'video_height': 320,
    'skip_kf_eval': True,
    't2v_only': False,
}
path = APP / 'user_settings.json'
current = json.loads(path.read_text()) if path.exists() else {}
current.update(settings)
path.write_text(json.dumps(current, indent=2))
print('Configured existing ComfyUI, local Ollama and compact workflows.')
