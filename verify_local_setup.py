"""Check local dependencies; optionally render an image or short video smoke test."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

import requests

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'video_director_agent'
sys.path.insert(0, str(APP))
os.environ['PATH'] = str(ROOT / 'tools' / 'ffmpeg') + os.pathsep + os.environ['PATH']

import config
from comfyui_client import ComfyUIClient, build_workflow, calc_frames, load_workflow_template
from keyframe_gen import build_keyframe_workflow, load_keyframe_template


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--render', choices=['image', 'video'])
    args = parser.parse_args()
    base = 'http://' + config.COMFYUI_HOST
    schemas = requests.get(base + '/object_info', timeout=30)
    schemas.raise_for_status()
    schemas = schemas.json()
    missing = []
    filenames = ('keyframe_template.json',) if args.render == 'image' else ('workflow_template.json', 'keyframe_template.json')
    for filename in filenames:
        graph = json.loads((APP / filename).read_text())
        for node_id, node in graph.items():
            schema = schemas.get(node['class_type'])
            if not schema:
                missing.append((filename, node_id, node['class_type']))
                continue
            inputs = schema.get('input', {})
            for key, rule in {**inputs.get('required', {}), **inputs.get('optional', {})}.items():
                value = node['inputs'].get(key)
                if isinstance(rule[0], list) and value is not None and not isinstance(value, list) and value not in rule[0]:
                    missing.append((filename, node_id, key, value))
    if missing:
        raise RuntimeError('Invalid or missing workflow dependencies: ' + repr(missing))
    print('Selected workflow graphs match the running ComfyUI and installed model names.', flush=True)
    if not args.render:
        response = requests.get(config.OLLAMA_HOST + '/api/tags', timeout=10)
        response.raise_for_status()
        models = {model['name'] for model in response.json()['models']}
        if config.OLLAMA_MODEL_CREATIVE not in models:
            raise RuntimeError('The configured Ollama model is not installed.')
        print('Ollama model available:', config.OLLAMA_MODEL_CREATIVE, flush=True)
    if not args.render:
        return
    prompt = 'A red ceramic teapot on a wooden table beside a bright window. Soft daylight, realistic photography, a slow camera push forward.'
    if args.render == 'image':
        graph = build_keyframe_workflow(load_keyframe_template(), prompt, 42,
                                        width=config.KF_WIDTH, height=config.KF_HEIGHT)
        graph['9']['inputs']['filename_prefix'] = 'kupkaprod_setup_test/storyboard'
    else:
        graph = build_workflow(load_workflow_template(), prompt, calc_frames(2), 42)
        graph['153:124']['inputs']['batch_size'] = 1
        graph['75']['inputs']['filename_prefix'] = 'kupkaprod_setup_test/video'
    client = ComfyUIClient()
    started = time.monotonic()
    try:
        client.connect()
        prompt_id = client.queue_prompt(graph)
        print('Queued', args.render, prompt_id, flush=True)
        history = client.wait_for_completion(prompt_id, timeout=1800)
        if history.get('status', {}).get('status_str') == 'error':
            raise RuntimeError(str(history['status']))
        if args.render == 'video':
            output = client.get_output_path(history)
        else:
            image = history['outputs']['9']['images'][0]
            output = str(Path(config.COMFYUI_OUTPUT_DIR) / image['subfolder'] / image['filename'])
        if not Path(output).is_file():
            raise RuntimeError('ComfyUI reported an output that is missing on disk.')
        result = {'type': args.render, 'seconds': round(time.monotonic() - started, 1),
                  'output': output, 'prompt_id': prompt_id}
        target = ROOT / 'logs' / ('verification-' + args.render + '.json')
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        client.disconnect()


if __name__ == '__main__':
    main()
