from pathlib import Path
p=Path('director_studio/omnichar_assets.py');t=p.read_text();p.write_text(t.replace("'cloths' if row['role']=='outfit'", "'cloth' if row['role']=='outfit'"))
p=Path('director_studio/engines.py');t=p.read_text(encoding='utf-8');needle="    spec=json.loads(specpath.read_text(encoding='utf-8'))\n    schema_response=";replacement="""    spec=json.loads(specpath.read_text(encoding='utf-8'))
    if kind=='qwen':
        from . import omnichar_assets
        characters=omnichar_assets.export_selected(s,n,Path(cfg.get('comfy_root',str(Path(cfg['existing_runtime'])/'tools/ComfyUI')))/'models/characters')
        store.atomic(work/'omnichar-manifest.json',characters)
        for character in characters:report('Omnichar character snapshot: '+s['nodes'][character['character']]['title']+' / '+character['signature'])
    schema_response=""";assert needle in t;t=t.replace(needle,replacement);p.write_text(t,encoding='utf-8')
