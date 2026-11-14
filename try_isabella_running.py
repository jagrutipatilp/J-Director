import json,shutil,time
from pathlib import Path
from director_studio import store,engines
s=store.load('test1-8922ff');n=dict(s['nodes']['1b8bcbb6d7ce'])
n.update(prompt='Use the woman in the supplied reference photograph as the same character. Show her running toward the camera on a quiet tree-lined park path in daylight, captured mid-stride in a medium-full shot. Her right arm swings forward and left arm back, shoulders naturally counter-rotate, hair bounces with her movement. Preserve her recognizable facial features, brown eyes, brown wavy shoulder-length hair, natural skin texture and youthful appearance. Keep her beige knitted sweater from the reference and add plain dark trousers and running shoes. Alert, focused expression with lips slightly parted from exertion. One woman only. Photorealistic candid cinematic action photograph, sharp face, believable anatomy and movement, softly blurred park background. No text, no collage.',references=[],asset_links={'characters':['454048cb46c3'],'backgrounds':[]},asset_links_manual=True,fast_reference_edit=True)
work=store.project_dir(s['id'])/'qa-tests'/('isabella-running-'+str(int(time.time())));work.mkdir(parents=True)
(work/'request.json').write_text(json.dumps({'prompt':n['prompt'],'reference':'36edfb8a817f','quality':s.get('quality'),'overwrites_episode':False},indent=2))
def report(message,*args):print(str(message).encode('ascii','backslashreplace').decode(),flush=True)
output=engines.generate_wangp(s,n,report)
result=work/'running.jpg';shutil.copy2(output,result)
print('RESULT='+str(result),flush=True)
