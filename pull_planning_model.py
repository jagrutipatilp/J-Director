"""Install the local planning model using verified, resumable registry transfers."""
import json
import re
import time

import ollama
import requests
from download_local_models import ROOT, download

client = ollama.Client(host='http://127.0.0.1:11434')
for attempt in range(30):
    try:
        client.list()
        break
    except ConnectionError:
        if attempt == 29:
            raise
        time.sleep(2)

response = requests.get('https://registry.ollama.ai/v2/library/gemma4/manifests/e4b', timeout=30)
response.raise_for_status()
manifest = response.json()
blobs = ROOT / 'local-models' / 'ollama' / 'blobs'
blobs.mkdir(parents=True, exist_ok=True)
(ROOT / 'planning-model-manifest.json').write_text(json.dumps(manifest, indent=2))
for layer in sorted([manifest['config'], *manifest['layers']], key=lambda layer: layer['size']):
    digest = layer['digest']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('Unexpected registry digest')
    path = blobs / digest.replace(':', '-')
    download(('https://registry.ollama.ai/v2/library/gemma4/blobs/' + digest,
              path, layer['size'], digest.split(':')[1]))

# Let Ollama register and verify its own manifest after the blobs are in place.
for event in client.pull('gemma4:e4b', stream=True):
    if not event.total:
        print(event.status, flush=True)
print('Local planning model installed.', flush=True)
