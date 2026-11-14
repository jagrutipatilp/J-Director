"""Maintain readable local production folders for the saved background images."""
from pathlib import Path
import json,re,shutil
from . import library

def export_backgrounds():
 root=library.ROOT/'backgrounds/the-devils-sunshine';root.mkdir(parents=True,exist_ok=True);records=[]
 for asset in library.load()['assets']:
  if asset['kind']!='location' or not asset['name'].startswith('The Devil’s Sunshine'):continue
  name=asset['name'].split('·')[-1].strip();slug=re.sub('[^a-z0-9]+','-',name.lower()).strip('-');folder=root/slug
  for v in asset['variants']:
   if not v.get('output'):continue
   source=v.get('provenance',{});group='master' if source.get('master') else 'generated' if source.get('origin')=='generated view' else 'alternatives'
   title=re.sub('[^a-z0-9]+','-',v['title'].lower()).strip('-');dest=folder/group/(title+'-'+v['id'][:6]+'.jpg');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(library.media_path(v['output']),dest)
   records.append({'location':name,'view':v['title'],'file':str(dest.resolve()),'library_asset':asset['id'],'library_variant':v['id'],'provenance':source})
 (root/'sources-and-images.json').write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf-8')
 (root/'READ-ME.txt').write_text('THE DEVIL’S SUNSHINE — HYPER-REALISTIC LOCATION LIBRARY\n\nmaster/: chosen real photo for this setting.\nalternatives/: other downloaded photos, depicting separate properties or options.\ngenerated/: local Qwen-derived views; check architecture before use.\n\nMaster photos and alternatives are licensed under the Pexels License: https://www.pexels.com/license/\nSource pages and photographers are recorded in sources-and-images.json and in J Director.\nDo not redistribute raw stock files as a standalone asset collection.\n\nUse Locations in J Director to browse images, then attach the desired view to a story project.\n',encoding='utf-8')
 return root,len(records)
if __name__=='__main__':print(export_backgrounds())
