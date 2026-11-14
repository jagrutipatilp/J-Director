from pathlib import Path
p=Path('director_studio/production.py');t=p.read_text();old="groups={}\n for row in rows:groups.setdefault(row['owner'] or row['id'],[]).append(row)\n chunks=list(groups.values())";new="groups={}\n identities=[row for row in rows if row['role']=='identity'] if identity_first else []\n for row in rows:\n  if row not in identities:groups.setdefault(row['owner'] or row['id'],[]).append(row)\n chunks=[[row] for row in identities]+list(groups.values())";assert old in t;t=t.replace(old,new);p.write_text(t)
p=Path('director_studio/library.py');t=p.read_text();t=t.replace('def attach(pid,aid,vids=None):','def attach(pid,aid,vids=None,target_asset=None):')
needle="    requested=[v['id'] for v in variants]";t=t.replace(needle,needle+"\n    if asset['kind']=='character':\n        defaults={asset.get('primary_variant'),asset.get('default_outfit_variant')}\n        variants += [v for v in asset['variants'] if v['id'] in defaults and v['id'] not in requested and not v.get('archived')]")
old="parent=next((n for n in s['nodes'].values() if n.get('library_asset')==aid and n['kind']==asset['kind']),None)";new="parent=s['nodes'].get(target_asset) if target_asset else next((n for n in s['nodes'].values() if n.get('library_asset')==aid and n['kind']==asset['kind']),None)\n        if target_asset and (not parent or parent['kind']!=asset['kind']):raise ValueError('Choose a matching story character or background')\n        old_refs=[n['id'] for n in s['nodes'].values() if target_asset and n.get('parent')==target_asset and n['kind']=='reference' and n.get('library_asset')!=aid]\n        if target_asset:parent.update(library_asset=aid,catalogue_name=asset['name'])";assert old in t;t=t.replace(old,new)
t=t.replace("n.get('library_variant')==v['id'] and n.get('library_version')==v['version']","n.get('parent')==parent['id'] and n.get('library_variant')==v['id'] and n.get('library_version')==v['version']")
t=t.replace("store.add_node(s,'reference',asset['name']+' / '+v['title']","store.add_node(s,'reference',parent['title']+' / '+v['title']")
needle="        refs[:]=[rid for rid in refs if s['nodes'][rid].get('library_variant') in requested]";insert="""        if asset['kind']=='character':
            imported={n.get('library_variant'):n for n in s['nodes'].values() if n.get('parent')==parent['id'] and n.get('library_asset')==aid and n.get('output')}
            primary=imported.get(asset.get('primary_variant'));outfit=imported.get(asset.get('default_outfit_variant'))
            if primary:parent['primary_reference']=primary['id']
            if outfit:parent['default_outfit']=outfit['id']
            if target_asset and primary:
                for rid in old_refs:s['nodes'][rid]['archived']=True
                for shot in s['nodes'].values():
                    if shot['id'] in old_refs:continue
                    if shot.get('references'):shot['references']=[rid for rid in shot['references'] if rid not in old_refs]
                    for row in shot.get('production',{}).get('cast',[]):
                        if row.get('character')==target_asset:
                            row['identity']=primary['id']
                            if outfit and (not row.get('outfit') or row.get('outfit') in old_refs):row['outfit']=outfit['id']
                    expression=shot.get('production',{}).get('expressions',{})
                    if expression.get(target_asset) in old_refs:expression.pop(target_asset)
                    if shot.get('output') and any(row.get('id') in old_refs for row in shot.get('render_references',[])):
                        shot['reference_update_note']='Character now uses '+asset['name']+' from the catalogue. Existing take was retained; regenerate to use the new reference.'
""";assert needle in t;t=t.replace(needle,insert+needle);p.write_text(t)
p=Path('director_studio/production.py');t=p.read_text();t=t.replace("'accessories':[]} for aid in characters","'accessories':[],'outfit':s['nodes'][aid].get('default_outfit')} for aid in characters");t=t.replace("'accessories':[]} for aid in auto_characters","'accessories':[],'outfit':s['nodes'][aid].get('default_outfit')} for aid in auto_characters");p.write_text(t)
p=Path('director_studio/app.py');t=p.read_text();t=t.replace("return library.attach(pid,aid,data.get('variants'))","return library.attach(pid,aid,data.get('variants'),data.get('target_asset'))");p.write_text(t)
p=Path('director_studio/static/studio.js');t=p.read_text();t=t.replace("if(valid)values().filter(x=>x.kind==='reference'&&x.id!==n.id)","if(valid)values().filter(x=>x.kind==='reference'&&!x.archived&&x.id!==n.id)");t=t.replace("for(const ref of children(a.id).filter(n=>n.kind==='reference'))","for(const ref of children(a.id).filter(n=>n.kind==='reference'&&!n.archived))");needle="row.append(use);card.append(row);root.append(card)";insert="""row.append(use);const target=current();if(project&&target&&target.kind===a.kind&&['character','location'].includes(target.kind)){const assign=node('button','','Use for '+target.title);assign.disabled=!a.variants.some(v=>v.output&&!v.archived)||!!work.length;assign.onclick=()=>safe(async()=>{const result=await api(base()+'/library/'+a.id,'POST',{target_asset:target.id});accept(result.project);toast(a.name+' assigned to '+target.title)});row.append(assign)}card.append(row);root.append(card)""";assert needle in t;t=t.replace(needle,insert);p.write_text(t)
