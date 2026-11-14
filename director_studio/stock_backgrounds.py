"""Small, cached stock-photo imports using the existing MoneyPrinter connection."""
from __future__ import annotations
import hashlib,io,json,re,time
from pathlib import Path
from urllib.parse import urlparse
import requests
from PIL import Image,ImageOps
from . import store,engines,story_assets,library

LICENSE='https://pixabay.com/service/license-summary/'

def query_for(asset):
 choices=[('living lounge','living room interior'),('corridor hallway','hotel corridor'),('bedroom','luxury bedroom interior'),('cafe café','empty cafe interior'),('office','executive office interior'),('restaurant','restaurant interior'),('farm','farmhouse'),('yacht','yacht deck'),('forest','forest path'),('mansion villa','luxury mansion')]
 for text in (asset['title'].lower(),asset.get('text','').lower()):
  for words,query in choices:
   if any(word in text for word in words.split()):return query
 return ' '.join(re.findall(r'[a-z]{3,}',asset.get('text','').lower())[:7]) or 'landscape'

def score(hit,query):
 tags=set(re.findall(r'[a-z]+',hit.get('tags','').lower()));terms=set(query.lower().split())
 value=3*len(tags&terms)
 if 'corridor' in terms:value+=5*len(tags&{'corridor','hallway'})+2*int('doors' in tags)-4*int('lobby' in tags)-8*len(tags&{'cruise','mosque','church','outdoor'})
 return value

def search(query):
 cfg=engines.settings();keyfile=Path(cfg.get('existing_runtime','C:/src/ai drama'))/'studio/stock-settings.json'
 keys=json.loads(keyfile.read_text(encoding='utf-8')) if keyfile.is_file() else {}
 key=keys.get('pixabay_key')
 if not key:raise ValueError('Connect Pixabay in MoneyPrinter first, or import a photo from your computer.')
 query=query.strip()[:100]
 if not query:raise ValueError('Enter background search words')
 cache=store.ROOT/'.stock-cache'/(hashlib.sha256(('photos-v1:'+query).encode()).hexdigest()+'.json')
 if cache.is_file() and time.time()-cache.stat().st_mtime<86400:return sorted(json.loads(cache.read_text(encoding='utf-8')),key=lambda h:score(h,query),reverse=True)
 try:response=requests.get('https://pixabay.com/api/',params={'key':key,'q':query,'image_type':'photo','safesearch':'true','per_page':16,'min_width':1200,'min_height':720},timeout=25)
 except requests.RequestException:raise ValueError('Pixabay is unavailable; your API key was not logged.') from None
 if response.status_code!=200:raise ValueError('Pixabay photo search returned HTTP '+str(response.status_code))
 hits=[]
 for hit in response.json().get('hits',[]):
  tags=hit.get('tags','').lower()
  if re.search(r'\b(people|person|woman|man|girl|boy|portrait|3d|render|rendering|illustration|ai generated)\b',tags):continue
  if hit.get('type')!='photo':continue
  hits.append({k:hit.get(k) for k in ('id','tags','pageURL','largeImageURL','webformatURL','user','imageWidth','imageHeight')})
 hits.sort(key=lambda h:score(h,query),reverse=True)
 store.atomic(cache,hits)
 return hits

def download(hit):
 url=hit.get('largeImageURL') or hit.get('webformatURL')
 def allowed(value):
  p=urlparse(value or '');return p.scheme=='https' and (p.hostname or '') in ('pixabay.com','cdn.pixabay.com')
 if not allowed(url):raise ValueError('Invalid stock image URL')
 try:
  response=requests.get(url,timeout=45,stream=True);response.raise_for_status()
  if not allowed(response.url):raise ValueError('Unexpected stock-image host')
  chunks=[];size=0
  for chunk in response.iter_content(65536):
   size+=len(chunk)
   if size>30*1024*1024:raise ValueError('Stock image exceeds 30 MB')
   chunks.append(chunk)
 except requests.RequestException:raise ValueError('The selected stock photo could not be downloaded.') from None
 raw=b''.join(chunks)
 try:
  with Image.open(io.BytesIO(raw)) as im:
   if im.width*im.height>40_000_000:raise ValueError('Stock photo is too large')
   im=ImageOps.exif_transpose(im).convert('RGB');out=io.BytesIO();im.save(out,'JPEG',quality=95);return out.getvalue()
 except (OSError,Image.DecompressionBombError):raise ValueError('Provider did not return a valid photo') from None

def fetch(pid,aid,query=None,report=lambda message:None,photo_id=None,replace_stock=False):
 s=store.load(pid);asset=s['nodes'].get(aid,{})
 if asset.get('kind')!='location':raise ValueError('Select a story background')
 master=story_assets.reference(s,aid)
 if master and master.get('output') and not replace_stock:return {'project':s,'reference':master['id'],'kept_existing':True}
 if replace_stock and master and master.get('reference_source')!='stock':raise ValueError('Existing user/generated master is preserved; choose a new reference instead.')
 query=query or query_for(asset);report('Searching Pixabay photos: '+query)
 hits=search(query)
 if not hits:raise ValueError('No suitable stock photo found for '+query)
 hit=next((h for h in hits if h['id']==photo_id),None) if photo_id else hits[0]
 if not hit:raise ValueError('That stock photo is not in these search results')
 raw=download(hit)
 provenance={'origin':'downloaded photograph','provider':'Pixabay','source_page':hit['pageURL'],'license_url':LICENSE,'author':hit.get('user'),'stock_id':hit['id'],'query':query,'tags':hit.get('tags',''),'master':True,'matching_camera_angle':False}
 catalog=library.load();shared=next((a for a in catalog['assets'] if a['kind']=='location' and a['name']==asset['title']),None)
 if not shared:shared=library.save_asset({'kind':'location','name':asset['title'],'description':asset['text']})
 v=next((v for v in shared['variants'] if v.get('provenance',{}).get('stock_id')==hit['id']),None)
 if not v:
  v=library.save_variant(shared['id'],{'title':'Stock photo master — Pixabay','category':'Angles','prompt':asset['text']})
  v=library.save_image(shared['id'],v['id'],raw)
  with library.LOCK:
   catalog=library.load();a=library.find(catalog,shared['id']);library.variant(a,v['id'])['provenance']=provenance;a['primary_variant']=v['id'];library.persist(catalog)
 def apply(state):
  a=state['nodes'][aid];ref=state['nodes'].get(master['id']) if master else None
  if not ref:ref=store.add_node(state,'reference',a['title']+' / Stock photo master',parent=aid,prompt=a['text'],category='Angles')
  target=store.node_dir(state,ref)/'preview.jpg';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
  ref.update(status='saved',locked=True,output=str(target.relative_to(store.project_dir(pid))).replace('\\','/'),version=ref.get('version',0)+1,reference_source='stock',source_provenance=provenance,library_asset=shared['id'],library_variant=v['id'],library_version=v['version'],view_kind='master')
  a.update(primary_reference=ref['id'],library_asset=shared['id'],catalogue_name=shared['name']);store.log(state,'Downloaded Pixabay background: '+a['title']+' — '+hit['pageURL']);return ref['id']
 refs=[]
 def capture(state):refs.append(apply(state))
 state=store.mutate(pid,capture,False)
 return {'project':state,'reference':refs[0],'source':hit['pageURL']}

def prepare(pid,aids,report):
 if engines.settings().get('background_source')!='stock_first':return
 for aid in sorted(aids):
  s=store.load(pid);asset=s['nodes'][aid]
  if asset['kind']!='location':continue
  ref=story_assets.reference(s,aid)
  if ref and (ref.get('output') or ref.get('reference_source') in ('system','catalogue','generate')):continue
  try:fetch(pid,aid,report=report)
  except ValueError as error:report('Stock background unavailable: '+str(error)+'; using the existing generation fallback.')
